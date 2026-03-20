# LaT-PFN Signals — dApp Marketplace Listings

Prepared listing materials for submitting to Base ecosystem directories and dApp aggregators.

---

## 1. DappRadar Listing

**Submit at:** https://dappradar.com/dashboard/submit-dapp

### Required Fields

| Field | Value |
|-------|-------|
| **Project Name** | LaT-PFN Signals |
| **Website URL** | https://latpfn.xyz *(update with actual domain)* |
| **Category** | DeFi |
| **Tags** | Trading Signals, AI, Futures, On-Chain Verification, Subscription |
| **Blockchain** | Base |
| **Smart Contract** | `0x901c169aa21a9eC593c52bc6F0eaA814eDf41091` |
| **Logo** | 250x250 PNG (see below) |
| **Screenshots** | Up to 3 (see below) |

### Short Description (150 chars)
```
AI-powered futures trading signals verified on-chain. LaT-PFN zero-shot forecasting for MNQ, MYM, MES, MBT micro futures on Base L2.
```

### Full Description
```
LaT-PFN Signals is the first on-chain verified AI trading signal platform for micro futures.

HOW IT WORKS:
Every 5 minutes during CME Globex market hours (Sun 6PM — Fri 5PM ET), the LaT-PFN zero-shot time-series forecasting model analyzes 240 bars of 5-minute OHLCV data and generates directional forecasts for micro futures contracts: MNQ (Micro Nasdaq), MYM (Micro Dow), MES (Micro S&P 500), and MBT (Micro Bitcoin).

Each forecast is hashed and posted to the Base L2 blockchain BEFORE delivery to subscribers — creating an immutable, verifiable record that eliminates hindsight bias. Anyone can verify signal integrity on Basescan.

SIGNAL PIPELINE:
1. LaT-PFN model predicts next 60 bars → direction + confidence
2. Composite confidence scoring: 40% model + 30% trend clarity + 30% uncertainty
3. Regime detection: ADX + volatility → trending/ranging/volatile
4. NBA shot-tier classification: layup, short_range, free_throw, three_pointer
5. EMA trend filter rejects counter-trend signals
6. Forecast hash posted on-chain via Base L2

LIVE PERFORMANCE (Broker-Confirmed):
• 187 trades | 56.7% Win Rate | 1.61 Profit Factor | +$3,205 P&L
• All 4 instruments profitable
• MNQ: 61.1% WR, +$1,668 | MBT: 80.0% WR, +$263
• Running live since February 2026

SUBSCRIPTION:
• Basic: 0.005 ETH/month — all signals, entry/SL/TP levels, tier classification
• Premium: 0.01 ETH/month — adds regime detection, confidence breakdown, priority API

TECHNOLOGY:
• LaT-PFN (Large-scale Tabular Prior-Fitted Network) — zero-shot forecasting
• Solidity smart contract on Base L2 for subscriptions + forecast verification
• Next.js frontend with TradingView-style terminal
• Privy auth (email, Google, Twitter, Apple + 300+ wallets)
```

### Social Media
| Platform | URL |
|----------|-----|
| GitHub | https://github.com/moltbot47/latpfn-trading |
| Twitter/X | *(add if available)* |
| Discord | *(add channel link)* |

---

## 2. Base Ecosystem Page

**How to apply:** No public form exists. Two paths:

### Option A: awesome-base GitHub PR
Submit a PR to https://github.com/wbnns/awesome-base adding LaT-PFN to the dApps list.

**PR content to add:**
```markdown
- [LaT-PFN Signals](https://latpfn.xyz) - AI-powered futures trading signals verified on-chain via Base L2. Zero-shot LaT-PFN forecasting with immutable forecast hashing.
```

### Option B: Base Discord
Join https://discord.com/invite/buildonbase and post in the #showcase or #builders channel.

**Discord post:**
```
🔗 LaT-PFN Signals — AI Trading Signals Verified On-Chain

We built the first on-chain verified AI trading signal platform on Base.

• LaT-PFN zero-shot forecasting for micro futures (MNQ, MYM, MES, MBT)
• Every forecast hashed on Base L2 BEFORE delivery — no hindsight bias
• 187 live trades, 56.7% WR, 1.61 PF, +$3,205 broker-confirmed P&L
• Privy auth — email/social login, no wallet required to sign up
• On-chain subscription: 0.005 ETH/month via smart contract

Contract: https://basescan.org/address/0x901c169aa21a9eC593c52bc6F0eaA814eDf41091
GitHub: https://github.com/moltbot47/latpfn-trading
```

---

## 3. Basescan dApp Directory

**How to apply:** https://info.basescan.org/

### Steps:
1. Create a Basescan account at https://basescan.org/register
2. Verify contract ownership (the deployer address)
3. Go to contract page → "Update Token Info" or "Update dApp Info"
4. Submit logo, description, social links, website URL

### Required Info:
| Field | Value |
|-------|-------|
| Contract Address | `0x901c169aa21a9eC593c52bc6F0eaA814eDf41091` |
| Project Name | LaT-PFN Signals |
| Website | https://latpfn.xyz |
| Description | AI-powered futures trading signals with on-chain forecast verification on Base L2 |
| Category | DeFi / Trading |
| Logo | 250x250 PNG |

---

## 4. Rayo (The Dapp List)

**Submit at:** https://rayo.gg (formerly The Dapp List)

Lists 447+ Base projects. Submit through their platform after creating an account.

---

## 5. Alchemy dApp Store

**Submit at:** https://www.alchemy.com/dapps (Apply to list)

Alchemy maintains a curated directory of dApps by chain. Base is a supported chain.

---

## 6. DefiLlama (if applicable)

**Submit at:** https://github.com/DefiLlama/DefiLlama-Adapters

Only relevant if the contract holds TVL (subscription fees locked). Submit a PR with an adapter that reads the contract balance.

---

## Assets Needed

### Logo (250x250 PNG)
Create a logo with these specs:
- 250x250px PNG, max 150KB
- Dark background (#0c0c0c)
- Cyan "L" text (#61d6d6) — matching the terminal theme
- Green pulse dot (#16c60c) — representing "live"
- Clean, monospace aesthetic

### Screenshots (3 required for DappRadar)
Capture these pages at 1280x720:
1. **Landing page** — Hero section with "AI Trading Signals Verified On-Chain"
2. **Trading terminal** — TUI-themed terminal with chart, watchlist, positions
3. **Dashboard** — Portfolio overview with sparklines and performance stats

---

## Launch Checklist

- [ ] Deploy frontend to production domain (Vercel recommended)
- [ ] Get a real WalletConnect project ID from https://cloud.walletconnect.com
- [ ] Create 250x250 logo PNG
- [ ] Take 3 screenshots at 1280x720
- [ ] Create DappRadar account → Submit listing
- [ ] Verify contract ownership on Basescan → Submit dApp info
- [ ] PR to awesome-base GitHub repo
- [ ] Post in Base Discord #showcase
- [ ] Submit to Rayo.gg
- [ ] Submit to Alchemy dApp Store
- [ ] Set up Twitter/X account for project updates
