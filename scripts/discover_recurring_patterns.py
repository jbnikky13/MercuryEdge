"""Discover recurring long-horizon market patterns from downloaded daily OHLC.

Outputs are descriptive research candidates, not automatic trade instructions.
The analysis uses only the data supplied to the workflow and explicitly reports
sample size, year-to-year persistence, and uncertainty proxies.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(os.getenv("RESEARCH_OUTPUT", "research_data"))
MIN_OBSERVATIONS = 30
MIN_YEARS = 5


def _load_daily(root: Path = ROOT) -> dict[str, pd.DataFrame]:
    frames = {}
    folder = root / "daily"
    if not folder.exists():
        return frames
    for path in sorted(folder.glob("*.csv")):
        try:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            if "Close" not in df.columns:
                continue
            df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
            df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
            df = df[~df.index.isna()].dropna(subset=["Close"])
            df = df[~df.index.duplicated(keep="last")].sort_index()
            if len(df) >= 100:
                frames[path.stem.upper()] = df
        except (OSError, ValueError, pd.errors.ParserError):
            continue
    return frames


def _summarize_group(group: pd.DataFrame, key: str, label: str) -> dict:
    returns = group["return_1d"].dropna()
    annual = returns.groupby(group.loc[returns.index, "year"]).mean()
    years = int(annual.size)
    mean = float(returns.mean()) if len(returns) else float("nan")
    std = float(returns.std(ddof=1)) if len(returns) > 1 else float("nan")
    se = std / np.sqrt(len(returns)) if len(returns) > 1 else float("nan")
    # Normal-approximation interval is a descriptive uncertainty indicator;
    # serial dependence means it is not a definitive significance test.
    return {
        "pattern": key,
        "value": label,
        "observations": int(len(returns)),
        "years_observed": years,
        "mean_daily_return_pct": round(mean * 100, 5),
        "positive_day_pct": round(float((returns > 0).mean() * 100), 2) if len(returns) else None,
        "approx_ci95_low_pct": round((mean - 1.96 * se) * 100, 5) if np.isfinite(se) else None,
        "approx_ci95_high_pct": round((mean + 1.96 * se) * 100, 5) if np.isfinite(se) else None,
        "annual_mean_positive_years": int((annual > 0).sum()),
        "annual_mean_years": years,
        "annual_positive_year_pct": round(float((annual > 0).mean() * 100), 2) if years else None,
    }


def discover_patterns(frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    patterns = []
    returns_by_symbol = {}
    for symbol, raw in frames.items():
        df = raw.copy()
        close = pd.to_numeric(df["Close"], errors="coerce")
        df["return_1d"] = close.pct_change()
        df["year"] = df.index.year
        df["month"] = df.index.month
        df["weekday"] = df.index.day_name()
        df["day_of_month_bucket"] = pd.cut(
            df.index.day, bins=[0, 5, 10, 15, 20, 25, 31],
            labels=["01-05", "06-10", "11-15", "16-20", "21-25", "26-end"],
        )
        returns_by_symbol[symbol] = df["return_1d"].rename(symbol)

        for month, group in df.dropna(subset=["return_1d"]).groupby("month"):
            row = _summarize_group(group, "calendar_month", f"{int(month):02d}")
            row["symbol"] = symbol
            if row["observations"] >= MIN_OBSERVATIONS and row["years_observed"] >= MIN_YEARS:
                patterns.append(row)

        for weekday, group in df.dropna(subset=["return_1d"]).groupby("weekday"):
            row = _summarize_group(group, "weekday", str(weekday))
            row["symbol"] = symbol
            if row["observations"] >= MIN_OBSERVATIONS and row["years_observed"] >= MIN_YEARS:
                patterns.append(row)

        for (month, weekday), group in df.dropna(subset=["return_1d"]).groupby(["month", "weekday"]):
            row = _summarize_group(group, "calendar_month+weekday", f"{int(month):02d}+{weekday}")
            row["symbol"] = symbol
            if row["observations"] >= MIN_OBSERVATIONS and row["years_observed"] >= MIN_YEARS:
                patterns.append(row)

        for bucket, group in df.dropna(subset=["return_1d"]).groupby("day_of_month_bucket", observed=True):
            row = _summarize_group(group, "day_of_month_bucket", str(bucket))
            row["symbol"] = symbol
            if row["observations"] >= MIN_OBSERVATIONS and row["years_observed"] >= MIN_YEARS:
                patterns.append(row)

    pattern_df = pd.DataFrame(patterns)
    if not pattern_df.empty:
        pattern_df = pattern_df[
            ["symbol", "pattern", "value", "observations", "years_observed",
             "mean_daily_return_pct", "positive_day_pct", "approx_ci95_low_pct",
             "approx_ci95_high_pct", "annual_mean_positive_years",
             "annual_mean_years", "annual_positive_year_pct"]
        ].sort_values(["symbol", "pattern", "value"]).reset_index(drop=True)

    joined = pd.concat(returns_by_symbol.values(), axis=1).dropna(how="all")
    correlations = joined.corr(min_periods=100)
    corr_rows = []
    for i, left in enumerate(correlations.columns):
        for right in correlations.columns[i + 1:]:
            value = correlations.loc[left, right]
            pair = joined[[left, right]].dropna()
            if pd.notna(value) and len(pair) >= 100:
                corr_rows.append({
                    "symbol_a": left, "symbol_b": right,
                    "daily_return_correlation": round(float(value), 4),
                    "overlapping_daily_observations": int(len(pair)),
                })
    corr_df = pd.DataFrame(corr_rows)
    if not corr_df.empty:
        corr_df = corr_df.sort_values("daily_return_correlation", key=lambda s: s.abs(), ascending=False)

    report = {
        "markets_with_daily_history": len(frames),
        "markets_with_reportable_patterns": int(pattern_df["symbol"].nunique()) if not pattern_df.empty else 0,
        "reported_pattern_rows": int(len(pattern_df)),
        "cross_market_pairs": int(len(corr_df)),
        "minimum_pattern_observations": MIN_OBSERVATIONS,
        "minimum_distinct_years": MIN_YEARS,
        "data_source": "Yahoo Finance via yfinance daily OHLC downloaded by research workflow",
        "limitations": [
            "Provider symbols and adjusted prices may differ from broker instruments and futures contracts.",
            "Calendar patterns can be unstable across market regimes and may disappear after costs.",
            "Approximate confidence intervals do not fully account for serial dependence or multiple testing.",
            "Correlations are descriptive, not proof of causal or stable lead-lag relationships.",
            "No pattern is automatically used to alter live signals; candidates require walk-forward validation."
        ],
    }
    return pattern_df, corr_df, report


def main() -> int:
    frames = _load_daily()
    if not frames:
        raise FileNotFoundError(f"No usable daily history found in {ROOT / 'daily'}")
    patterns, correlations, report = discover_patterns(frames)
    patterns.to_csv(ROOT / "recurring-patterns.csv", index=False)
    correlations.to_csv(ROOT / "cross-market-correlation.csv", index=False)
    (ROOT / "pattern-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("\nTop pattern candidates by year-to-year persistence (descriptive only):")
    if not patterns.empty:
        ranked = patterns.assign(
            persistence=patterns["annual_positive_year_pct"].where(
                patterns["mean_daily_return_pct"] >= 0,
                100 - patterns["annual_positive_year_pct"],
            )
        ).sort_values(["persistence", "observations"], ascending=False)
        print(ranked.head(20).to_string(index=False))
    print("\nHighest absolute cross-market return correlations:")
    if not correlations.empty:
        print(correlations.head(20).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
