"""
NAS100 FVG-AT-LEVEL — TradeLocker Bot Studio / Backtrader sandbox. Paste this whole file as one bot.

Rule = edge-hunt cell `1h_L2_E2_edge_rr3to1` (h_ema_vwap_scalper_htf), the one NAS100 cell that was
positive in all 3 folds and beat random entries. Use 1-HOUR candles, UTC (TradeLocker default).

  1. FVG (3-candle fair value gap), known at the CLOSE of candle 3 (bar k):
       bullish  low[k]  > high[k-2]   zone = [high[k-2], low[k]]
       bearish  high[k] < low[k-2]    zone = [high[k], low[k-2]]
  2. AT A LEVEL: the zone lies within 0.25 x ATR14 of any of
       session VWAP, prior-day pivot P / R1 / S1, prior-day high / low, prior-week high / low.
     Session day starts 22:00 UTC (as the backtest's data).
  3. ENTRY: pending LIMIT at the gap's near edge (low[k] for a bullish gap, high[k] for bearish),
     in the gap's direction. It must sit on the pullback side of the close. Expires after 6 bars.
  4. SIZE of the move: d = |entry - far side of candle 1| (low[k-2] bullish / high[k-2] bearish).
     Skip if d < 0.25 ATR or d > 3 ATR.
     TARGET = entry + d (1x)     STOP = entry - rr_stop x d   (rr_stop = 3 -> risk 3 : reward 1)
  5. One position or pending order at a time. No new orders in the last 60 min of the session;
     flat 45 min before the session ends (21:15 UTC). Max hold 24 bars.

DIFFERENCES FROM THE BACKTEST (read before trusting a Bot Studio number):
  * The backtest filled and exited on 1-MINUTE bars: a limit filled only if price traded THROUGH it,
    and a bar touching both stop and target counted as a STOP. On 1h candles Bot Studio can't see
    inside the bar, so this script applies the same pessimism itself (see _manage):
    fill only if the bar trades through, and stop-first when one bar hits both.
  * VWAP uses the candle volume Bot Studio supplies (tick volume), like the backtest.
  * The tested sample is SMALL: 88 trades over 4 months (Jan-Apr 2024). Treat any Bot Studio
    result as a new out-of-sample check, not a confirmation. Do not tune the params to make it green.

Costs, estimated and printed in the summary (Bot Studio may not charge them):
  commission_per_lot (Genesis NAS100 $6 round trip), spread_pts (~1.15 pts).

SANDBOX: only backtrader + math + datetime.
"""
import backtrader as bt
import datetime as dt
import math


class Nas100FvgLevel(bt.Strategy):
    params = dict(
        lots=1.0,
        point_value=10.0,               # Genesis NAS100: $10 per point per lot
        commission_per_lot=6.0,         # $ round trip
        spread_pts=1.15,                # points per round trip
        rr_stop=3.0,                    # stop = rr_stop x target distance (tested: 3)
        level_tol_atr=0.25,
        min_d_atr=0.25, max_d_atr=3.0,
        pending_bars=6,
        max_hold_bars=24,
        atr_n=14,
        session_start_utc=22,           # session day rolls at 22:00 UTC
        flat_utc_h=21, flat_utc_m=15,   # flat 45 min before the 22:00 roll
        no_new_utc_h=21, no_new_utc_m=0,
        mirror_orders=True,             # also send real bracket orders so Bot Studio's own report shows trades
        verbose=False,
    )

    def __init__(self):
        self.dd = self.datas[0]
        self._hist = []                 # closed bars: (t, o, h, l, c, v)
        self._atr = None
        self._sday = None
        self._cur = None                # current session: [high, low, close, pv_sum, v_sum]
        self._daily = []                # finished sessions: (sday, high, low, close)
        self._week_hl = {}              # iso (year, week) of session day -> [high, low]
        self._lv = None                 # prior-day / prior-week levels for the current session
        self._order = None              # dict: side, entry, tp, sl, expires
        self._pos = None                # dict: side, entry, tp, sl, bars
        self._res = []                  # (side, entry, exit, reason)
        self._bo = []                   # live platform bracket orders [main, stop, limit]
        self._prev_t = None
        self._wrong_tf = None           # set once the candle size is known

    # ------------------------------------------------------------------ helpers
    def _sday_of(self, t):
        return (t + dt.timedelta(hours=24 - self.p.session_start_utc)).date()

    def _roll_session(self, sday):
        if self._cur is not None:
            h, l, c = self._cur[0], self._cur[1], self._cur[2]
            self._daily.append((self._sday, h, l, c))
            wk = self._sday.isocalendar()[:2]
            w = self._week_hl.setdefault(wk, [h, l])
            w[0], w[1] = max(w[0], h), min(w[1], l)
        self._sday, self._cur = sday, None
        if self._daily:
            _, h, l, c = self._daily[-1]
            P = (h + l + c) / 3.0
            prev_wk = (sday - dt.timedelta(days=7)).isocalendar()[:2]
            pw = self._week_hl.get(prev_wk)
            self._lv = dict(P=P, R1=2 * P - l, S1=2 * P - h, PDH=h, PDL=l,
                            PWH=pw[0] if pw else None, PWL=pw[1] if pw else None)

    def _levels(self):
        out = []
        if self._lv:
            out += [v for v in self._lv.values() if v is not None]
        if self._cur and self._cur[4] > 0:
            out.append(self._cur[3] / self._cur[4])  # session VWAP
        return out

    def _cost(self):
        return (self.p.commission_per_lot + self.p.spread_pts * self.p.point_value) * self.p.lots

    def _book(self, px, reason):
        if reason in ("FLAT", "TIME"):
            self._mirror_flatten()
        s = self._pos
        self._res.append((s["side"], s["entry"], px, reason))
        if self.p.verbose:
            self.log("%s %s %.2f -> %.2f (%+.1f pts)" % (
                reason, "LONG" if s["side"] > 0 else "SHORT", s["entry"], px, (px - s["entry"]) * s["side"]))
        self._pos = None

    # ------------------------------------------------------------------ main loop
    def next(self):
        t = self.dd.datetime.datetime(0)
        if self._wrong_tf is None:
            if self._prev_t is None:
                self._prev_t = t
                return
            gap = (t - self._prev_t).total_seconds() / 60.0
            self._prev_t = t
            if gap <= 0:
                return
            self._wrong_tf = abs(gap - 60.0) > 1e-6 and gap < 60.0 * 2
            if self._wrong_tf:
                print("!!! Nas100FvgLevel needs 1H candles; this feed is %.0f-minute. "
                      "Re-run the backtest with Resolution = 1H. No trades will be placed." % gap)
        if self._wrong_tf:
            return
        o, h, l, c = self.dd.open[0], self.dd.high[0], self.dd.low[0], self.dd.close[0]
        v = max(self.dd.volume[0], 1e-9)

        sday = self._sday_of(t)
        if sday != self._sday:
            self._roll_session(sday)
        tp_ = (h + l + c) / 3.0
        if self._cur is None:
            self._cur = [h, l, c, tp_ * v, v]
        else:
            self._cur[0], self._cur[1], self._cur[2] = max(self._cur[0], h), min(self._cur[1], l), c
            self._cur[3] += tp_ * v
            self._cur[4] += v

        prev_c = self._hist[-1][4] if self._hist else c
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        self._atr = tr if self._atr is None else self._atr + (tr - self._atr) / self.p.atr_n

        self._manage(t, o, h, l, c)
        self._hist.append((t, o, h, l, c, v))
        if len(self._hist) > 50:
            self._hist.pop(0)
        self._signal(t, c)

    def _manage(self, t, o, h, l, c):
        """Simulate the pending limit and the open trade on this bar (the backtest's rules)."""
        close_t = t + dt.timedelta(hours=1)
        flat = close_t.replace(hour=self.p.flat_utc_h, minute=self.p.flat_utc_m, second=0, microsecond=0)
        at_flat = close_t >= flat and t < flat
        # 1) pending limit: fill only if price trades THROUGH it
        if self._order and not self._pos:
            s = self._order
            if (s["side"] > 0 and l < s["entry"]) or (s["side"] < 0 and h > s["entry"]):
                self._pos = dict(side=s["side"], entry=s["entry"], tp=s["tp"], sl=s["sl"], bars=0)
                self._order = None
                # fill bar: only the stop can trigger
                if (s["side"] > 0 and l <= s["sl"]) or (s["side"] < 0 and h >= s["sl"]):
                    self._book(s["sl"], "STOP")
                    return
                if at_flat:
                    self._book(c, "FLAT")
                return
            s["expires"] -= 1
            if s["expires"] <= 0 or at_flat:
                self._order = None
                self._mirror_cancel_entry()
        # 2) open trade: stop first if one bar hits both
        if self._pos:
            s = self._pos
            s["bars"] += 1
            hit_sl = (s["side"] > 0 and l <= s["sl"]) or (s["side"] < 0 and h >= s["sl"])
            hit_tp = (s["side"] > 0 and h >= s["tp"]) or (s["side"] < 0 and l <= s["tp"])
            if hit_sl:
                self._book(s["sl"], "STOP")
            elif hit_tp:
                self._book(s["tp"], "TARGET")
            elif at_flat:
                self._book(c, "FLAT")
            elif s["bars"] >= self.p.max_hold_bars:
                self._book(c, "TIME")

    def _signal(self, t, c):
        if self._order or self._pos or len(self._hist) < 3 or self._atr is None:
            return
        close_t = t + dt.timedelta(hours=1)
        no_new = close_t.replace(hour=self.p.no_new_utc_h, minute=self.p.no_new_utc_m, second=0, microsecond=0)
        roll = close_t.replace(hour=self.p.session_start_utc, minute=0, second=0, microsecond=0)
        if no_new < close_t <= roll:
            return
        _, _, h2, l2, _, _ = self._hist[-3]      # candle 1
        _, _, hk, lk, _, _ = self._hist[-1]      # candle 3 (just closed)
        if lk > h2:
            side, near, far, base = 1, lk, h2, l2
        elif hk < l2:
            side, near, far, base = -1, hk, l2, h2
        else:
            return
        a = self._atr
        lo, hi = min(near, far), max(near, far)
        tol = self.p.level_tol_atr * a
        if not any(lo - tol <= L <= hi + tol for L in self._levels()):
            return
        entry = near
        if (side > 0 and not entry < c) or (side < 0 and not entry > c):
            return
        d = abs(entry - base)
        if d < self.p.min_d_atr * a or d > self.p.max_d_atr * a:
            return
        tp = entry + side * d
        sl = entry - side * self.p.rr_stop * d
        assert (tp - entry) * side > 0 and (entry - sl) * side > 0
        self._order = dict(side=side, entry=entry, tp=tp, sl=sl, expires=self.p.pending_bars)
        if self.p.mirror_orders and not self.position and not self._bo:
            f = self.buy_bracket if side > 0 else self.sell_bracket
            self._bo = list(f(size=self.p.lots, exectype=bt.Order.Limit, price=entry,
                              stopprice=sl, limitprice=tp))
        if self.p.verbose:
            self.log("ARM %s limit %.2f tp %.2f sl %.2f (d=%.1f, ATR=%.1f)" % (
                "BUY" if side > 0 else "SELL", entry, tp, sl, d, a))

    # ------------------------------------------------------------------ platform mirror
    def _mirror_cancel_entry(self):
        if self._bo and self._bo[0].alive():
            self.cancel(self._bo[0])            # children cancel with the parent

    def _mirror_flatten(self):
        for o in self._bo:
            if o.alive():
                self.cancel(o)
        if self.position:
            self.close()

    def notify_order(self, o):
        if self._bo and not any(x.alive() for x in self._bo):
            self._bo = []

    # ------------------------------------------------------------------ summary
    def stop(self):
        p = self.p
        n = len(self._res)
        if self._wrong_tf:
            print("=== Nas100FvgLevel === NOT RUN: wrong resolution. Use 1H candles.")
            return
        if not n:
            print("=== Nas100FvgLevel === no trades (1h candles? enough history for prior-week levels?)")
            return
        net = [(x - e) * s * p.point_value * p.lots - self._cost() for s, e, x, _ in self._res]
        wins = [x for x in net if x > 0]
        losses = [-x for x in net if x <= 0]
        pf = sum(wins) / sum(losses) if sum(losses) > 0 else float("inf")
        eq = peak = dd = 0.0
        for x in net:
            eq += x; peak = max(peak, eq); dd = max(dd, peak - eq)
        k = n // 3
        thirds = (sum(net[:k]), sum(net[k:2 * k]), sum(net[2 * k:]))
        reasons = {}
        for r in self._res:
            reasons[r[3]] = reasons.get(r[3], 0) + 1
        be = p.rr_stop / (1.0 + p.rr_stop)
        print("=== Nas100FvgLevel === trades=%d  exits=%s" % (n, reasons))
        print("  NET $%.0f after $%.0f costs | win %.1f%% (break-even before costs %.0f%%) | PF %.2f | max DD $%.0f"
              % (sum(net), self._cost() * n, 100.0 * len(wins) / n, 100 * be, pf, dd))
        print("  thirds (oldest -> newest): $%.0f / $%.0f / $%.0f" % thirds)
        print("  ^ HONEST number (through-fills, stop-first). Bot Studio's own report uses its touch fills "
              "and next-bar exits, so it will differ; trust this line.")

    def log(self, m):
        print("[%s] %s" % (self.dd.datetime.datetime(0).isoformat(), m))
