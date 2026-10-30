# Headway MT5 demo feed (read-only)

This collector connects to the **locally running MetaTrader 5 desktop terminal** on a Windows host. It does not log in with credentials supplied to the script and contains no order-placement calls.

## Verified broker endpoint

Headway's help centre lists the MT5 demo server as:

- Display name: `Headway-Demo`
- Server host: `mt5.demo.trade-hw.online`

In MT5, confirm the account is the demo account and that the server shown in Account Information is `Headway-Demo`. Do not use a real account for this collector.

## Why a Windows VPS is required

The official `MetaTrader5` Python package communicates with an installed, running MT5 desktop terminal. GitHub Actions' standard Ubuntu runner and iPhone/Android MT5 apps are not substitutes for that terminal. Run this collector on a Windows VPS (or a Windows PC that remains online) with MT5 installed and already logged into the Headway demo account.

## Installation

Open PowerShell on the Windows host:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
py -m pip install MetaTrader5
```

Copy this repository to the Windows host, open MT5, log in to the **Headway-Demo** account, and leave the terminal running. Then run:

```powershell
py research\headway_mt5_collector.py --date 2026-10-29
```

Omit `--date` to collect the previous completed Africa/Lagos calendar day. The default symbol list follows MercuryEdge's configured market universe. If Headway uses a suffix such as `.m` or `#`, the collector accepts it only when the match is unique; ambiguous symbols are reported and skipped rather than guessed.

## Output

Files are written under `research_data/headway_mt5/YYYY-MM-DD/`:

- `feed-report.json`: server/account checks, broker symbol mapping, contract metadata and coverage.
- Per-symbol `ticks.csv`: UTC timestamp, BID, ASK, LAST, volume and flags.
- Per-symbol `m1.csv`, `m5.csv`, `h1.csv`, `h4.csv`: broker-server candles.

Keep this directory private if it contains account-specific operational data. Do not commit account credentials or MT5 terminal data folders to Git.

## Safety and interpretation

- The collector requires the MT5 account to report both the exact Headway demo server name and demo account mode. It stops otherwise.
- It only calls MT5 initialization, account/terminal/symbol metadata, symbol selection, tick-history and candle-history read methods. It does not contain trade/order APIs.
- BUY entry/exit evaluation must use ASK to enter and BID to exit. SELL entry/exit evaluation must use BID to enter and ASK to exit.
- Replay should use tick sequence where available. If only OHLC bars exist and stop/target are both inside a candle, label the result ambiguous rather than inventing the order of touches.
- Demo quotes are broker-specific research data, not proof of live-account execution quality or fills.
- This collector is a local/VPS job. It is not run by the repository's Ubuntu GitHub Actions workflows.
