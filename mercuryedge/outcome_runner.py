from __future__ import annotations

import argparse

from .config import MARKETS
from .data import load_market
from .outcomes import resolve_journal
from .walkforward import calibrate, load_outcomes


def candle_loader(symbol: str, signal_time: str):
    # Load a sufficiently long 1H window. Filtering to post-signal candles is
    # handled by evaluate_signal, preventing look-ahead.
    return load_market(symbol)


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve MercuryEdge signals and recalibrate factors")
    parser.add_argument("--horizon", type=int, default=24)
    args = parser.parse_args()

    report = resolve_journal(candle_loader, horizon=args.horizon)
    outcomes = load_outcomes()
    calibration = calibrate(outcomes)

    print("MERCURYEDGE OUTCOME INTELLIGENCE")
    print(f"New resolutions: {report['new_resolutions']}")
    print(f"Total resolved: {report['total_resolved']}")
    print(f"Calibration samples: {calibration['samples']}")
    print(calibration["factors"])


if __name__ == "__main__":
    main()
