# Apex Trader Funding — Rules & Compliance Reference

**Account:** APEX4406280000015
**Account Size:** $50,000 Evaluation
**Status:** Evaluation (not PA yet)
**Date:** February 10, 2026

---

## ACCOUNT-BLOWING LIMITS (Know These Cold)

| Parameter | Value | Notes |
|-----------|-------|-------|
| **Starting Balance** | $50,000 | |
| **Trailing Drawdown** | $2,500 | Follows highest unrealized intraday balance |
| **Blow-Up Level** | Highest Balance - $2,500 | If balance drops below this, account is DONE |
| **Profit Target** | $3,000 (balance = $53,000) | Pass eval and move to PA |
| **Drawdown Stops Trailing** | When threshold reaches $53,000 | After that, floor is locked |
| **Minimum Trading Days** | 7 | Must trade at least 7 days to pass |

### How Trailing Drawdown Works
- Starts at $47,500 ($50,000 - $2,500)
- If your balance peaks at $51,000, new floor = $48,500 ($51,000 - $2,500)
- Tracks UNREALIZED intraday highs (not just closed P&L)
- Once the floor reaches $53,000, it STOPS trailing (locked in place)
- If balance ever touches the floor = account terminated

### Example Scenario
```
Start:    $50,000  →  floor = $47,500
Peak:     $50,800  →  floor = $48,300
Peak:     $51,500  →  floor = $49,000
Drop to:  $49,100  →  SAFE (above $49,000 floor)
Drop to:  $48,900  →  ACCOUNT BLOWN (below $49,000 floor)
```

---

## EVALUATION ACCOUNT RULES

### Trading Hours
- **Session:** 6:00 PM ET → 4:59 PM ET (next day)
- **Must flatten** all positions by 4:59 PM ET
- Our system flattens at 4:55 PM ET (4-minute safety buffer)
- No new trades opened after 4:45 PM ET

### Position Limits ($50k Account)
- **Max contracts:** 80 micros OR 10 minis
- Our system uses micros (MYM, MNQ, MGC) — well within limits

### What's Allowed During Evaluation
- Automated trading tools (more permissive than PA)
- PickMyTrade webhook execution
- Any CME futures contracts
- News trading (but no opposing positions on same news event)

### What's NOT Allowed (Even During Eval)
- No holding positions through market close (4:59 PM ET)
- No account sharing
- No HFT or market manipulation
- No simultaneous opposing positions on same/correlated instruments

---

## PA ACCOUNT RULES (After Passing Eval)

### Critical Automation Rule
> **Fully automated trading is PROHIBITED on PA accounts.**
> Semi-automated tools are allowed IF the trader is present and actively monitoring.

**Our system handles this with `confirmation_mode: true`:**
- Bot generates signal → posts to Discord → waits for your approval
- You react with checkmark to execute, X to reject
- Auto-rejects after 60 seconds if no response
- This makes it a "semi-automated tool with human oversight"

### PA-Specific Rules
| Rule | Details |
|------|---------|
| **30% Consistency Rule** | No single day's profit > 30% of total at payout time |
| **30% MAE Rule** | No trade's unrealized loss > 30% of profit balance |
| **5:1 Risk-Reward** | Max risk-to-reward ratio is 5:1 per trade |
| **Contract Scaling** | Start at 50% of max contracts until threshold is met |
| **Safety Net** | First 3 payouts: balance must stay above drawdown + $100 |

### PA Payout Rules ($50k Account)
- Minimum 8 trading days between payouts
- At least 5 of those 8 days must show $100+ profit
- Minimum payout: $500
- Payouts 1-5: capped at $2,000 each
- Payout 6+: uncapped, 100% profit share

---

## PROHIBITED ACTIVITIES (Complete List)

### Account Violations
1. Sharing MAC addresses, computers, IPs, or credit cards with other traders
2. Anyone other than registered owner trading the account
3. Creating multiple user accounts
4. Sharing login credentials

### Trading Violations
5. Fully automated trading on PA/Live (AI, algorithms, bots, HFT)
6. "Set-and-forget" systems running unattended
7. Copy trading / trade mirroring from other traders
8. Holding opposing positions simultaneously (long + short on same/correlated)
9. Taking opposing positions on the same news event
10. "All-in" trades with max contracts at account start
11. Using account threshold as a stop-loss (riding to liquidation)
12. Trading WITHOUT stop losses
13. HFT or market manipulation
14. Holding positions through market close (must be flat by 4:59 PM ET)
15. DCA across multiple markets simultaneously for one-tick gains

### Payout Abuse
16. Cycling first payouts across multiple accounts
17. Purchasing multiple discounted evals to blow up for windfall profits
18. Cycling PA accounts (big size → lose → reset → repeat)

### Consequences
- Account closure
- Forfeiture of ALL funds and balances
- Potential permanent ban

---

## OUR SYSTEM'S COMPLIANCE STATUS

### Enforced by Code (risk/apex_compliance.py)
- [x] Hard flatten at 4:55 PM ET
- [x] No new trades after 4:45 PM ET
- [x] 5:1 max R:R ratio enforcement
- [x] 30% MAE rule (tracks profit balance)
- [x] Correlated instrument guard (MYM/MNQ can't oppose each other)
- [x] Confirmation mode for PA accounts (Discord approval required)
- [x] Stop losses on every trade (built into signal generator)
- [x] Position size limits (risk manager)
- [x] Daily loss circuit breaker

### Tracked but Not Auto-Enforced
- [ ] Trailing drawdown level (displayed in Discord, alerts when close)
- [ ] 30% consistency rule (tracked, warns at payout time)
- [ ] Minimum trading days counter

### Compliant by Design
- Single account, single user, single machine
- 5-minute prediction cycles (not HFT)
- Directional trades only (no simultaneous long+short)
- Micro contracts well within 80-micro limit

---

## WHEN TO SWITCH TO CONFIRMATION MODE

```yaml
# In config/settings.yaml:

# EVALUATION (current) — auto-execute is OK:
execution:
  confirmation_mode: false

# PA ACCOUNT (after passing) — MUST enable:
execution:
  confirmation_mode: true
```
