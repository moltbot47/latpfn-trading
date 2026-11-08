"""
OVERNIGHT DRIFT — TradeLocker Bot Studio / Backtrader sandbox. Paste this whole file as one bot.

Rule (edge-hunt `overnight_drift`, variant on_16_9_L_all, the fold-1 pick on MNQ/MES/MYM/MGC):
  * Every weekday, go LONG at the 16:00 New York bar open.
  * Exit at the 09:00 New York bar open the next trading morning (Friday entries exit Monday).
  * No stop, no target, no filters. One position at a time. Fixed lots.

Feed: any symbol (NAS100 / US30 / XAUUSD), 15m or 1h candles, UTC timestamps (TradeLocker).
Candle timestamps are bar OPEN times; orders placed in next() fill at the NEXT bar's open, so the
script sends the order on the bar BEFORE 16:00 / 09:00 and it fills exactly on the scheduled bar.
New York time is DST-aware.

COSTS the Bot Studio backtest may NOT charge, estimated here and printed in the summary:
  * commission_per_lot  — round trip (Genesis: NAS100 $6, XAUUSD $10)
  * spread_pts          — paid once per round trip (NAS100 ~1.15 pts)
  * swap_per_lot_night  — CFD overnight financing, charged per night held (Fri->Mon = 3 nights).
    THIS DECIDES IT on a CFD: the futures backtest paid no swap. Enter Genesis's real swap-long
    value (in $ per lot per night, as a positive cost) before trusting the result.

SANDBOX: only backtrader + math + datetime.
"""
import backtrader as bt
import datetime as dt
import math


class OvernightDrift(bt.Strategy):
    params = dict(
        entry_h=16, entry_m=0,          # New York time
        exit_h=9, exit_m=0,             # New York time, next trading morning
        lots=1.0,
        point_value=10.0,               # $ per 1.0 price point per lot (Genesis NAS100 = 10, XAUUSD = 100)
        commission_per_lot=6.0,         # $ round trip per lot
        spread_pts=1.15,                # price points paid per round trip
        swap_per_lot_night=0.0,         # $ cost per lot per night held; 0 = ignore (unknown!)
        skip_friday=False,              # True = don't hold over the weekend
        verbose=False,
    )

    def __init__(self):
        self.d = self.datas[0]
        self._bar = None                # bar length, detected from the feed
        self._prev_t = None
        self._entry_px = None
        self._entry_t = None
        self._pending = None
        self._od_trades = []               # (entry_t, exit_t, entry_px, exit_px, nights)

    # ------------------------------------------------------------------ time helpers
    def _et_offset(self, t):
        """US Eastern offset from UTC: 4h in DST, 5h otherwise."""
        mar1 = t.replace(month=3, day=1)
        dst_start = 1 + (6 - mar1.weekday()) % 7 + 7   # second Sunday of March
        nov1 = t.replace(month=11, day=1)
        dst_end = 1 + (6 - nov1.weekday()) % 7         # first Sunday of November
        md = (t.month, t.day)
        return dt.timedelta(hours=4 if (3, dst_start) <= md < (11, dst_end) else 5)

    def _to_et(self, t_utc):
        return t_utc - self._et_offset(t_utc)

    def _hits(self, et, h, m):
        """True if the NEXT bar opens inside [h:m, h:m + one bar)."""
        start = et.replace(hour=h, minute=m, second=0, microsecond=0)
        return start <= et < start + self._bar

    # ------------------------------------------------------------------ main loop
    def next(self):
        t = self.d.datetime.datetime(0)
        if self._bar is None:
            if self._prev_t is not None and t > self._prev_t:
                self._bar = t - self._prev_t
            self._prev_t = t
            return
        # the bar after this one opens at t + bar; that is when an order sent now fills
        nxt_et = self._to_et(t + self._bar)
        if self._pending:
            return

        if not self.position:
            wd = nxt_et.weekday()
            if wd > 4 or (self.p.skip_friday and wd == 4):
                return
            if self._hits(nxt_et, self.p.entry_h, self.p.entry_m):
                self._pending = self.buy(size=self.p.lots)
        else:
            entry_date = self._to_et(self._entry_t).date()
            hm = (nxt_et.hour, nxt_et.minute)
            # exit on the 09:00 bar, or the first weekday bar after it if 09:00 is missing
            # (never on the Sunday-evening reopen)
            if nxt_et.date() > entry_date and nxt_et.weekday() <= 4 and (
                    self._hits(nxt_et, self.p.exit_h, self.p.exit_m)
                    or (self.p.exit_h, self.p.exit_m) < hm < (self.p.entry_h, self.p.entry_m)):
                self._pending = self.close()

    # ------------------------------------------------------------------ bookkeeping
    def notify_order(self, o):
        if o.status in (o.Submitted, o.Accepted):
            return
        if o.status == o.Completed:
            t = bt.num2date(o.executed.dt)
            if o.isbuy():
                self._entry_px, self._entry_t = o.executed.price, t
            else:
                e_et, x_et = self._to_et(self._entry_t).date(), self._to_et(t).date()
                nights = max(1, (x_et - e_et).days)
                self._od_trades.append((self._entry_t, t, self._entry_px, o.executed.price, nights))
                if self.p.verbose:
                    self.log("CLOSED %.2f -> %.2f (%+.2f pts, %d night%s)" % (
                        self._entry_px, o.executed.price, o.executed.price - self._entry_px,
                        nights, "" if nights == 1 else "s"))
                self._entry_px = self._entry_t = None
        self._pending = None

    def stop(self):
        p, lots = self.p, self.p.lots
        n = len(self._od_trades)
        if not n:
            print("=== OvernightDrift === no completed trades (check the feed is 15m or 1h, UTC)")
            return
        gross = [(x - e) * p.point_value * lots for _, _, e, x, _ in self._od_trades]
        costs = [(p.commission_per_lot + p.spread_pts * p.point_value) * lots
                 + p.swap_per_lot_night * nights * lots for _, _, _, _, nights in self._od_trades]
        net = [g - c for g, c in zip(gross, costs)]
        wins = [x for x in net if x > 0]
        losses = [-x for x in net if x <= 0]
        pf = sum(wins) / sum(losses) if losses and sum(losses) > 0 else float("inf")
        eq = peak = dd = 0.0
        for x in net:
            eq += x
            peak = max(peak, eq)
            dd = max(dd, peak - eq)
        # chronological thirds: the edge must show in each, not just overall
        k = n // 3
        thirds = [sum(net[:k]), sum(net[k:2 * k]), sum(net[2 * k:])]
        nights = sum(t[4] for t in self._od_trades)
        print("=== OvernightDrift === trades=%d  %s -> %s" % (
            n, self._od_trades[0][0].date(), self._od_trades[-1][1].date()))
        print("  gross $%.0f | commission+spread $%.0f | swap $%.0f (%d nights x $%.2f/lot)" % (
            sum(gross), sum(costs) - p.swap_per_lot_night * nights * lots,
            p.swap_per_lot_night * nights * lots, nights, p.swap_per_lot_night))
        print("  NET $%.0f | win %.1f%% | PF %.2f | max DD $%.0f | avg/trade $%.1f" % (
            sum(net), 100.0 * len(wins) / n, pf, dd, sum(net) / n))
        print("  thirds (oldest -> newest): $%.0f / $%.0f / $%.0f" % tuple(thirds))
        if p.swap_per_lot_night == 0:
            be = sum(gross) - (sum(costs))
            print("  swap NOT charged. Break-even swap = $%.2f per lot per night -- "
                  "if Genesis charges more than that, this loses on the CFD." % (be / (nights * lots)))

    def log(self, m):
        print("[%s] %s" % (self.d.datetime.datetime(0).isoformat(), m))
