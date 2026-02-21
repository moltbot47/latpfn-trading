# Prop Firm & Trading Platform API Research
## Instant Funding + Full Two-Way API Access for Futures Trading
### Research Date: February 2026

---

## Executive Summary

Finding a platform that combines **all four criteria** (instant funding, prop firm compatibility, full two-way API/WebSocket, and micro futures support) is challenging. No single solution perfectly satisfies everything out of the box. However, several viable paths exist, ranked below by feasibility:

**Best Overall Path:** Rithmic API + Instant-Funded Prop Firm (Tradeify Lightning, FundingTicks Zero, or Thrive Trading)

**Runner-Up:** TopstepX/ProjectX API (requires passing eval, but has the most complete API + prop firm integration)

**Third Option:** Tradovate API via third-party vendors (PickMyTrade/TradersPost) with prop firms that use Tradovate

---

## A) Tradovate API

### Overview
Tradovate offers both REST and WebSocket APIs for futures trading, now owned by NinjaTrader/NT Technologies (acquired by Kraken in March 2025 for $1.5B).

### API Capabilities
- **API Type:** REST + WebSocket (v1.0.0)
- **WebSocket Endpoint:** `wss://live.tradovateapi.com/v1/websocket`
- **Replay Endpoint:** `wss://replay.tradovateapi.com`
- **Data You Can Receive:**
  - Order fills and state changes
  - Position updates
  - DOM updates
  - Real-time quotes (limited on some account types)
  - User sync data (WebSocket-only via `user/syncrequest`)
- **Order Capabilities:** Full order management including bracket orders, OCO, trailing stops
- **Execution Latency:** 200-300ms (sub-second)

### Known Limitations
1. **CRITICAL: Prop firm accounts do NOT allow direct API access.** This is confirmed on the Tradovate community forums. Prop accounts are blocked from generating their own API keys.
2. **Rate Limits:** 500 requests per minute. Exceeding this causes "Too Many Requests" errors and potential P-ticket penalties (temporary API access suspension).
3. **Market Data:** Some integrations (e.g., TradersPost) cannot fetch market data quotes through the API.
4. **Multi-Account Issues:** Each Tradovate login needs its own API connection; trading multiple prop firm accounts increases rate limit risk.
5. **Stability:** API/WebSocket update issues surged 15% in 2025 due to stricter prop firm limits and platform changes.
6. **CME Compliance:** All automated orders must flag `isAutomated: true`.

### Prop Firm API Access Workaround
- **PickMyTrade** is an authorized Tradovate vendor with built-in API access. When you connect a Tradovate-based prop firm account through PickMyTrade, API access is included (no separate API key purchase required). However, this routes through their intermediary, not direct API access.
- **TradersPost** offers similar TradingView-to-Tradovate automation for prop accounts.
- These are NOT the same as direct programmatic API access -- they are webhook-based automation platforms.

### Prop Firm Compatibility
- Apex Trader Funding (Tradovate option: $105/month)
- My Funded Futures
- Take Profit Trader
- TradeDay
- Elite Trader Funding
- Tradeify

### Micro Futures Support
Yes -- MES, MNQ, MYM, M2K, MGC, and all standard CME micro contracts.

### Cost
- Tradovate platform: Free (web) or paid tiers for desktop
- API access: Requires active Tradovate account with API entitlement (not available on prop accounts directly)

### Verdict
**Not recommended for direct API trading on prop firm accounts.** The API itself is capable, but prop firm accounts are explicitly blocked from direct API access. The workaround through PickMyTrade/TradersPost is webhook-based, not true programmatic control.

---

## B) Rithmic API

### Overview
Rithmic is the dominant infrastructure provider for futures prop firms. Their API uses WebSockets with Google Protocol Buffers for high-performance, low-latency trading.

### API Types
1. **R|API+** -- C++ software libraries for direct integration. Highest performance. Used by institutional traders.
2. **R|Protocol API** -- WebSocket + Protocol Buffers. Language-agnostic (works with Python, JavaScript, Rust, etc.). Designed for mobile/web apps.
3. **R|Diamond API** -- Advanced version with additional features.

### Architecture (R|Protocol API)
The API splits functionality across separate **Plants**, each requiring its own WebSocket connection:
- **TICKER_PLANT** -- Live tick/market data streaming
- **HISTORY_PLANT** -- Historical tick data
- **ORDER_PLANT** -- Order management, execution, fills
- **PNL_PLANT** -- P&L calculations (inferred from libraries)

### Data You Can Receive
- **Order fills** (execution reports)
- **Position updates** (real-time)
- **Account/balance data**
- **Market data** (Level 1 and Level 2 / DOM)
- **Historical data** (tick, bar)
- **Order status changes** (working, filled, cancelled, rejected)

### Python Libraries
- **pyrithmic** (PyPI) -- Lightweight Python wrapper. Supports tick data streaming, historical downloads, and order management.
- **async_rithmic** (PyPI) -- Robust async Python API. Complete rewrite of pyrithmic. Supports all plants with async/await pattern.
- **python_rithmic_trading_app** (GitHub) -- Example trading application.

### Known Limitations
1. **Documentation Access:** Official documentation requires contacting Rithmic directly (rapi@rithmic.com) and signing an NDA/agreement. Not publicly available.
2. **API Request Process:** Must formally request API access through rithmic.com/api-request.
3. **No Public Rate Limit Documentation:** Rate limits are not publicly documented; likely negotiated per agreement.
4. **Platform Restriction:** R|API+ is C++ only. R|Protocol API is language-agnostic via WebSocket/protobuf.
5. **Colocation:** For lowest latency, Rithmic colocation is available but adds cost.
6. **Prop Firm API Access:** Whether a prop firm account gets API access depends on the PROP FIRM's agreement with Rithmic, not the trader directly. Some firms allow it, others do not.

### Prop Firm Compatibility (Rithmic-based)
- **Apex Trader Funding** (Rithmic option: $85/month) -- Allows automated trading bots, must be "actively managed" (no pure set-and-forget). DCA bots explicitly permitted. HFT prohibited.
- **Bulenox** -- Rithmic-based. Supports algo/copy trading and EAs.
- **My Funded Futures** -- Supports Rithmic. As of July 2025, permits algo trading on both eval and funded accounts.
- **Take Profit Trader** -- Rithmic-based.
- **Earn2Trade** -- Rithmic-based (Gauntlet Mini program).
- **FundingTicks** -- Rithmic-based. Permits automated strategies.
- **Thrive Trading** -- Rithmic-based. Instant funding available.

### Micro Futures Support
Yes -- Full support for all CME micro futures (MES, MNQ, MYM, M2K, MGC, etc.) through all Rithmic-connected exchanges (CME, CBOT, NYMEX, COMEX).

### Cost
- Rithmic data feed: ~$20/month (through brokers like EdgeClear) + per-contract fees (~$0.10/contract)
- API access: Free with Rithmic agreement (but requires formal application)
- Prop firm fees: Vary by firm ($85-$150/month typical)

### Verdict
**BEST OPTION for direct API access with prop firms.** Rithmic is the most widely supported infrastructure among futures prop firms. The R|Protocol API provides full two-way WebSocket communication with order execution, fill reports, and position tracking. The main hurdle is getting API access approved (formal application required) and confirming your specific prop firm allows API trading on their Rithmic accounts.

---

## C) CQG API

### Overview
CQG provides exchange connectivity, market data, and trade execution for 45+ exchanges worldwide. Being acquired by Broadridge Financial Solutions (announced February 2026).

### API Types
1. **CQG Web API** -- WebSocket-based using Google Protocol Buffers. Similar architecture to Rithmic.
2. **CQG FIX Connect** -- Standard FIX protocol for order routing. Institutional-grade.
3. **CQG Desktop API (CQG IC/QTrader API)** -- COM-based API for desktop integration.

### Data You Can Receive
- **Execution reports** (order status, fills)
- **Position reports** (current day fills, FCM-confirmed positions)
- **Market data** (Level 1, Level 2 / DOM, historical)
- **Account summaries** and order history
- **Post-trade analysis data**

### Known Limitations
1. **Higher Cost:** CQG is generally more expensive than Rithmic for data feeds.
2. **Less Prop Firm Adoption:** Fewer prop firms use CQG compared to Rithmic.
3. **Documentation:** Available through partners.cqg.com but requires partner/developer registration.
4. **Complexity:** The protocol buffer interface is optimized for bandwidth efficiency but has a steeper learning curve.

### Prop Firm Compatibility (CQG-based)
- Topstep (historical -- now transitioning to TopstepX/ProjectX)
- Take Profit Trader
- Alpha Futures
- TickTick Trader
- FuturesElite

### Micro Futures Support
Yes -- Full support through CME exchange gateways.

### Cost
- CQG data feeds: Generally more expensive than Rithmic ($25-50+/month depending on exchange data packages)
- API access: Requires developer agreement

### Verdict
**Viable but not optimal.** CQG has capable APIs but fewer prop firms use it compared to Rithmic, and the cost is typically higher. The Broadridge acquisition may change the landscape, but for now, Rithmic is the better choice for prop firm API trading.

---

## D) TopStep (TopstepX / ProjectX)

### Overview
Topstep is one of the largest futures prop firms. In 2025-2026, they transitioned to their proprietary **TopstepX** platform built on **ProjectX** technology. ProjectX went exclusive to TopstepX in November 2025.

### API Capabilities (ProjectX/TopstepX API)
- **API Type:** REST + WebSocket
- **Python SDK:** `project-x-py` (PyPI, v3.3.4) -- High-performance async SDK
- **Also Available:** `projectx-api` (PyPI), `tsxapi4py` (GitHub)
- **Gateway API Docs:** gateway.docs.projectx.com

### What You Can Do
- **Send orders** (market, limit, stop, brackets)
- **Receive real-time fills** (order status changes detected immediately)
- **Track positions** (real-time P&L, risk management, position lifecycle)
- **Stream market data** (Level 2 orderbook, 50ms refresh, unfiltered DOM)
- **Build custom dashboards and monitoring**
- **Copy trades across accounts**
- **Automate order execution**

### Known Limitations
1. **NO INSTANT FUNDING.** Topstep requires passing a Trading Combine evaluation (minimum 5-7 trading days, though can be as fast as 1 day during promotional sales).
2. **API costs $29/month** (or $14.50/month with "topstep" discount code).
3. **VPS/VPN PROHIBITED.** All activity must be from your own device. No remote servers, no VPS, no VPN.
4. **Orders via API are FINAL.** Topstep will not review, adjust, or reverse API-executed orders.
5. **Activation Fee:** $149 after passing the Combine.
6. **Platform Lock-In:** Starting March 2026, ProjectX is exclusive to Topstep.

### Evaluation Structure (NOT Instant Funded)
- 50K Account: $49/month
- 100K Account: $99/month
- 150K Account: $149/month
- Must hit profit target without hitting max drawdown
- Minimum trading days required
- After passing: Express Funded Account ($149 activation)

### Micro Futures Support
Yes -- Full support for all CME micro futures.

### Profit Split
- 100% of first $10,000 (on Express Funded)
- 90/10 split after that

### Verdict
**Excellent API but requires evaluation.** The ProjectX/TopstepX API is arguably the most modern and developer-friendly option available. Full REST + WebSocket with comprehensive Python SDK. However, the lack of instant funding and VPS prohibition are significant drawbacks. If you can tolerate passing an evaluation, this is one of the best API options.

---

## E) Instant Funding Prop Firms

### Tradeify (Lightning Funded) -- BEST INSTANT FUNDING OPTION

- **Instant Funding:** Yes -- "Lightning Funded" accounts. One-time payment, no evaluation.
- **Pricing:**
  - 25K account: ~$349 one-time
  - 50K account: ~$449 one-time
  - 100K account: ~$599 one-time
  - 150K account: ~$729 one-time
  - No monthly subscription after purchase
- **Platforms:** Tradovate, NinjaTrader, Quantower, ProjectX, TradingView
- **Automated Trading:** Permitted (EAs, algos allowed). HFT and arbitrage PROHIBITED.
- **API Access:** Uses Tradovate or NinjaTrader as backend. Direct API access depends on platform choice. Via Tradovate: same API restrictions apply (no direct prop account API). Via NinjaTrader: NinjaScript C# automation available.
- **Micro Futures:** Yes (MES, MNQ, MYM, M2K, MGC). Cannot mix mini and micro simultaneously.
- **Profit Split:** 100% of first $15,000, then 90/10
- **Key Rules:** Daily profit cap of 20% (1st payout), 25% (2nd), 30% (3rd+). Max total profit per Lightning account: $80,000.
- **Drawdown:** Trailing drawdown. No daily loss limit on some plans.
- **Verdict:** Good instant funding option but API access is limited by the underlying platform (Tradovate restrictions apply). Best for webhook-based automation via PickMyTrade/TradersPost rather than direct API.

### FundingTicks (Zero Program) -- BEST FOR RITHMIC + INSTANT FUNDING

- **Instant Funding:** Yes -- "Zero" program provides direct-funded accounts with no evaluation.
- **Platforms:** Rithmic-based (NinjaTrader, Quantower, R|Trader Pro)
- **Automated Trading:** Permitted (EAs, algorithmic scripts allowed within rules)
- **API Access:** Because FundingTicks uses Rithmic, the R|Protocol API should be accessible if the firm's Rithmic agreement allows it. **This is the strongest candidate for instant funding + direct API access.**
- **Micro Futures:** Yes -- Rithmic provides full CME micro futures access.
- **Profit Split:** 90/10 across all programs
- **Payouts:** Every 5-7 trading days depending on program
- **Account Sizes:** Up to $300,000
- **Pricing:** Varies by account size. Direct-funded accounts cost 2-3x evaluation pricing.
- **Key Limitation:** Must confirm with FundingTicks whether their Rithmic accounts support R|Protocol API access for automated trading.
- **Verdict:** MOST PROMISING option combining instant funding + Rithmic API potential. Needs verification that their specific Rithmic setup allows API trading.

### Bulenox

- **Instant Funding:** Occasionally runs instant funding promotions. Not a standard offering. Standard path requires evaluation (no minimum trading days).
- **Platforms:** Rithmic-based. Supports 18+ trading platforms.
- **Automated Trading:** Supports algo/copy trading and EAs.
- **API Access:** Rithmic-based, so R|Protocol API could be available. Unclear official stance.
- **Micro Futures:** Yes -- 40+ futures products across CME, NYMEX, COMEX, CBOT.
- **Profit Split:** 100% of first $10,000, then 90/10
- **Cost:** Evaluation from ~$96 + $148 activation. Account sizes $10K-$250K.
- **Verdict:** Not reliably instant-funded. When promotions run, could be viable with Rithmic API. Standard eval path is fast (no minimum days).

### My Funded Futures (MFFU)

- **Instant Funding:** No. Single-step evaluation required. Near-instant automated payout approval after passing.
- **Platforms:** Tradovate, NinjaTrader, Rithmic, TradingView
- **Automated Trading:** As of July 2025, algo trading and third-party automation tools are permitted on both eval and funded accounts. Must comply with CME guidelines. No HFT.
- **API Access:** Depends on platform choice (Tradovate API restrictions apply; Rithmic API may be available).
- **Micro Futures:** Yes
- **Profit Split:** 90/10
- **Account Sizes:** Up to $600K
- **Verdict:** No instant funding, but one of the most algo-friendly prop firms. Good candidate if you can tolerate a single-step eval.

### The Funded Trader

- **Instant Funding:** No for futures. Multiple evaluation challenges required.
- **Platforms:** Restricted to non-U.S. clients for some products.
- **API Access:** Limited information available.
- **Verdict:** Not suitable for this use case.

### Thrive Trading Group -- STRONG INSTANT FUNDING + RITHMIC

- **Instant Funding:** Yes. No evaluation phases. Start trading immediately.
- **Platforms:** NinjaTrader, Bookmap, powered by Rithmic for execution.
- **Automated Trading:** Not explicitly confirmed or denied in research. Hard-wired risk controls (EOD limits, max drawdown, daily loss limits) suggest automated strategies may work within limits.
- **API Access:** Rithmic-based infrastructure with sub-millisecond execution. If API trading is permitted, R|Protocol API would apply.
- **Micro Futures:** Yes -- Direct access to CME, CBOT, NYMEX.
- **Latency:** Sub-0.5ms round-trip execution times.
- **Payout Requirements:** Minimum trading days, profit target, daily performance thresholds.
- **Verdict:** Strong candidate for instant funding + Rithmic API. Must confirm automated/API trading policy directly with the firm.

### Instant Funding (instantfunding.com)

- **Instant Funding:** Yes (by definition)
- **Details:** Limited information. Newer firm focused on simplifying rules for 2026.
- **Verdict:** Insufficient data. Research further before committing.

---

## F) NinjaTrader API

### Overview
NinjaTrader was acquired by Kraken for $1.5B in March 2025. It launched **NinjaTrader Prop** and **Tradovate Prop** under NT Technologies in October 2025.

### API Types
1. **NinjaScript (C#)** -- Primary development framework. Create custom indicators, strategies, and add-ons within NinjaTrader desktop. Deep platform integration but locked to C#.
2. **NinjaTrader Trade API** -- REST API with WebSocket for market data. Swagger definitions available. Available at developer.ninjatrader.com.
3. **CrossTrade API** -- Third-party REST API for NinjaTrader 8. Supports Python, JavaScript, Go, etc. Endpoints for account management, position control, order management, and execution analytics.

### Data You Can Receive
- Account summaries, balances, performance metrics
- Position queries and management
- Order management (place, cancel, modify)
- Fill information and execution analytics
- Real-time market data via WebSocket
- Historical data

### Known Limitations
1. **Prop Firm API Access Uncertain:** Community discussions indicate NinjaTrader API may NOT be available to prop firm traders. This is an active question on the NinjaTrader forums with no definitive answer.
2. **NinjaScript Lock-In:** Primary automation requires C# and NinjaTrader desktop running.
3. **New Prop Firm Restrictions:** NinjaTrader will no longer onboard new prop firms, and existing prop firm services will be phased out by mid-2026.
4. **Platform Fee:** NinjaTrader desktop requires license or lease.

### Prop Firm Compatibility
- NinjaTrader Prop (own prop firm)
- Apex Trader Funding
- My Funded Futures
- Tradeify
- FundingTicks
- Take Profit Trader

### Micro Futures Support
Yes -- Full support for all CME micro futures.

### Verdict
**Uncertain for prop firm API access.** The NinjaScript ecosystem is powerful but may not be available on prop firm accounts. The upcoming restrictions on new prop firm integrations add risk. CrossTrade API offers a workaround but adds another dependency. Not recommended as primary path.

---

## G) Other Notable Platforms

### Cannon Trading API Prime
- **Type:** Institutional futures brokerage with API-first approach
- **Target:** Algorithmic trading firms and prop businesses
- **Features:** Production-ready APIs, deep market data, automation-native risk controls, kill-switch procedures
- **Risk Controls:** Price-band checks, throttle limits, max-position rules, daily loss locks, auto-flatten
- **Prop Firm:** Not a prop firm itself; it's a broker. Could potentially be used alongside prop firm arrangements.
- **Verdict:** Professional-grade but aimed at established firms, not individual traders seeking prop funding.

### EdgeClear (Rithmic Broker)
- **Type:** Futures broker providing Rithmic access
- **Cost:** $20/month + $0.10/contract
- **API Access:** R|API+ and R|Protocol API available through Rithmic agreement
- **Platforms:** Sierra Chart, Bookmap, Quantower, NinjaTrader, and many more
- **Prop Firm:** Not a prop firm. Personal trading accounts with full Rithmic API access.
- **Verdict:** Good for personal trading with Rithmic API. Not instant-funded prop trading.

### Interactive Brokers TWS API
- **Type:** Full-featured broker API (REST, WebSocket, FIX)
- **Languages:** Python, Java, C++, C#
- **v10.42 (Dec 2025):** Enhanced Python bindings, 30% faster WebSocket polling
- **Prop Firm:** Not compatible with futures prop firms. Personal accounts only.
- **Verdict:** Best API for personal trading. Not applicable to prop firm use case.

---

## Comparison Matrix

| Platform/Firm | Instant Funded | API Type | Fills | Positions | Balances | Micro Futures | API on Prop Account | Monthly Cost |
|---|---|---|---|---|---|---|---|---|
| **Rithmic (via prop firm)** | Depends on firm | WebSocket + Protobuf | Yes | Yes | Yes | Yes | Depends on firm | $85-150 |
| **TopstepX/ProjectX** | NO (eval required) | REST + WebSocket | Yes | Yes | Yes | Yes | YES ($29/mo) | $49-149 + $29 API |
| **Tradovate (direct)** | N/A | REST + WebSocket | Yes | Yes | Yes | Yes | NO (blocked) | Varies |
| **Tradovate (via vendor)** | Depends on firm | Webhook (indirect) | Partial | Partial | No | Yes | Via vendor only | $20-50/mo vendor |
| **CQG** | Depends on firm | WebSocket + Protobuf + FIX | Yes | Yes | Yes | Yes | Depends on firm | $25-50+ |
| **NinjaTrader** | Depends on firm | REST + WebSocket + C# | Yes | Yes | Yes | Yes | UNCERTAIN | License fees |
| **FundingTicks (Zero)** | YES | Rithmic-based | Likely | Likely | Likely | Yes | NEEDS VERIFICATION | Varies |
| **Tradeify (Lightning)** | YES | Tradovate-based | Limited | Limited | Limited | Yes | Via vendor | $349-729 one-time |
| **Thrive Trading** | YES | Rithmic-based | Likely | Likely | Likely | Yes | NEEDS VERIFICATION | Varies |
| **Apex (Rithmic)** | NO (eval) | Rithmic-based | Yes | Yes | Yes | Yes | Allowed (with rules) | $85/mo |
| **Bulenox** | Occasional promos | Rithmic-based | Yes | Yes | Yes | Yes | NEEDS VERIFICATION | ~$244 total |
| **MFFU** | NO (1-step eval) | Tradovate/Rithmic | Depends | Depends | Depends | Yes | Depends on platform | Varies |

---

## Recommended Strategy

### Path 1: Fastest to Full API Trading (Instant Funded)

1. **Sign up for FundingTicks "Zero" (instant funded) account** on Rithmic
2. **Apply for Rithmic R|Protocol API access** (rithmic.com/api-request)
3. **Verify with FundingTicks** that their Rithmic accounts support API trading
4. **Use `async_rithmic` Python library** for WebSocket-based order execution and fill tracking
5. **Trade micro futures** (MES, MNQ, MYM, M2K, MGC) within firm rules

**Estimated Cost:** FundingTicks Zero account fee (2-3x eval price) + Rithmic data ($0-20/mo depending on setup)

**Risk:** FundingTicks may not allow direct API access on their Rithmic accounts. Verify BEFORE paying.

### Path 2: Best API Experience (Requires Eval)

1. **Sign up for TopstepX Trading Combine** ($49-149/month)
2. **Pass evaluation** (minimum 1-7 trading days depending on promotions)
3. **Activate API access** ($14.50/month with discount code)
4. **Use `project-x-py` Python SDK** for full trading automation
5. **Trade micro futures** with comprehensive position/fill tracking

**Estimated Cost:** $49-149 eval + $149 activation + $14.50/month API
**Risk:** Must pass evaluation. VPS/VPN prohibited (must run from personal device).

### Path 3: Rithmic API with Fast Eval

1. **Sign up for Apex Trader Funding** (Rithmic plan, $85/month)
2. **Pass evaluation** (as few as 1-7 trading days)
3. **Apply for Rithmic API access** and confirm Apex allows it on funded accounts
4. **Use `async_rithmic` or `pyrithmic`** for automated trading
5. **Follow Apex rules:** Active management required, no pure set-and-forget, no HFT

**Estimated Cost:** $85/month + Rithmic API access (if additional fees apply)
**Risk:** API access on Apex Rithmic accounts is not guaranteed. Must verify.

### Path 4: Hybrid Approach

1. **Open personal EdgeClear account** ($20/month + $0.10/contract) for Rithmic API development/testing
2. **Simultaneously get instant-funded account** at FundingTicks or Thrive Trading
3. **Develop and test strategies** on personal EdgeClear account with full API access
4. **Deploy to prop firm account** once confirmed API access works

---

## Critical Questions to Ask Each Prop Firm Before Signing Up

1. "Do your Rithmic-connected accounts support R|Protocol API access for automated order execution?"
2. "Can I use custom software (Python scripts) to send orders and receive fills via WebSocket on my funded account?"
3. "Are there any restrictions on API-based automated trading beyond your standard trading rules?"
4. "What is the process to get Rithmic API credentials for my funded account?"
5. "Do you restrict the number of API connections or messages per second?"

---

## Sources

### Tradovate
- [Tradovate API Documentation](https://api.tradovate.com/)
- [Tradovate API Access Support](https://support.tradovate.com/s/article/Tradovate-API-Access?language=en_US)
- [API Access for Prop Firm Accounts (Forum)](https://community.tradovate.com/t/api-access-for-propfirm-accounts/10348)
- [Prop Account API Access (Forum)](https://community.tradovate.com/t/prop-account-api-access/10430)
- [Apex Tradovate API Request Limit](https://support.apextraderfunding.com/hc/en-us/articles/15219616639515-Tradovate-API-Request-Limit)
- [Tradovate Partner API WebSocket](https://partner.tradovate.com/overview/core-concepts/web-sockets/connection-overview)
- [Tradovate Bots Guide 2025 (PickMyTrade)](https://blog.pickmytrade.trade/tradovate-bots-automated-trading-guide-2025/)
- [Tradovate Review 2026](https://propfirmapp.com/trading-tools/tradovate)

### Rithmic
- [Rithmic APIs Official](https://www.rithmic.com/apis)
- [Rithmic API Request](https://www.rithmic.com/api-request)
- [pyrithmic (GitHub)](https://github.com/jacksonwoody/pyrithmic)
- [async_rithmic (PyPI)](https://pypi.org/project/async-rithmic/1.2.4/)
- [async_rithmic Documentation](https://async-rithmic.readthedocs.io/)
- [python_rithmic_trading_app (GitHub)](https://github.com/rayeni/python_rithmic_trading_app)
- [EdgeClear Rithmic Access](https://edgeclear.com/rithmic/)
- [Rithmic Review 2026](https://propfirmapp.com/trading-tools/rithmic)
- [Prop Firms Supporting Rithmic](https://vettedpropfirms.com/prop-firms-that-support-rithmic/)

### CQG
- [CQG APIs Official](https://www.cqg.com/products/cqg-apis)
- [CQG Web API Partners](https://partners.cqg.com/api-resources/web-api)
- [CQG FIX Connect](https://help.cqg.com/apihelp/Documents/fixconnectorderrouting.htm)
- [CQG WebAPI Documentation](https://help.cqg.com/apihelp/Documents/cqgwebapi.htm)
- [Broadridge to Acquire CQG (2026)](https://www.broadridge.com/press-release/2026/broadridge-to-acquire-cqg)
- [Prop Firms Using CQG](https://vettedpropfirms.com/prop-firms-that-use-cqg/)
- [CQG API on AMP Futures](https://www.ampfutures.com/trading-platform/cqg-api)

### TopStep / ProjectX
- [TopstepX API Access](https://help.topstep.com/en/articles/11187768-topstepx-api-access)
- [ProjectX Python SDK Docs](https://project-x-py.readthedocs.io/en/stable/)
- [ProjectX Gateway API Docs](https://gateway.docs.projectx.com/)
- [project-x-py (PyPI)](https://pypi.org/project/project-x-py/)
- [tsxapi4py (GitHub)](https://github.com/mceesincus/tsxapi4py)
- [ProjectX Setup Guide 2025](https://blog.pickmytrade.io/projectx-setup-guide-2025-automation-checklist/)
- [Topstep Review 2026](https://www.proptradingvibes.com/prop-firms/topstep)

### Prop Firms
- [Tradeify Lightning Funded](https://help.tradeify.co/en/articles/10495938-lightning-funded-accounts)
- [FundingTicks Official](https://www.fundingticks.com/)
- [FundingTicks Review 2026](https://www.proptradingvibes.com/prop-firms/fundingticks)
- [Thrive Trading Official](https://thrivetrading.com/)
- [Thrive Trading Review 2026](https://propfirmfutures.com/thrive-trading-group-review/)
- [Bulenox Official](https://bulenox.com/)
- [My Funded Futures Official](https://myfundedfutures.com/)
- [Apex Trader Funding Official](https://apextraderfunding.com/)
- [Apex Automated Trading Bots](https://www.quantvps.com/blog/apex-trader-funding-automated-trading-bots)
- [Straight-to-Funded Prop Firms (QuantVPS)](https://www.quantvps.com/blog/straight-to-funded-futures-prop-firms)
- [Instant Funding Prop Firms 2026 (LuxAlgo)](https://www.luxalgo.com/blog/instant-funding-prop-firms-2025/)
- [Best APIs for Automated Futures Trading 2026](https://www.quantvps.com/blog/best-apis-for-automated-futures-trading)

### NinjaTrader
- [NinjaTrader Developer API](https://developer.ninjatrader.com/products/api)
- [NinjaTrader Trade API Docs](https://developer.ninjatrader.com/docs/api)
- [NinjaTrader API for Prop Firm Traders (Forum)](https://discourse.ninjatrader.com/t/is-ninjatrader-api-available-to-ninjatrader-prop-firm-traders/3826)
- [CrossTrade API](https://crosstrade.io/crosstrade-api)
- [NinjaTrader Review 2026](https://propfirmapp.com/trading-tools/ninjatrader)

### Automation Platforms
- [PickMyTrade](https://pickmytrade.trade/)
- [TradersPost (Topstep)](https://traderspost.io/connections/topstep)
- [Cannon Trading API](https://www.cannontrading.com/software/futures-trading-api)
