import numpy as np
import pandas as pd

from mercuryedge.analysis import add_indicators, analyze
from scripts.research_historical import _current_rule_signals


def _sample_market(n=760):
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    x = np.arange(n, dtype=float)
    close = 100 + 0.025 * x + 3.2 * np.sin(x / 8.0) + 1.1 * np.sin(x / 2.7)
    return pd.DataFrame({
        "Open": close - 0.08,
        "High": close + 0.45,
        "Low": close - 0.45,
        "Close": close,
        "Volume": 1000.0,
    }, index=idx)


def test_historical_rule_replay_matches_live_core_signals():
    frame = _sample_market()
    replay = _current_rule_signals(frame)
    replay_by_ts = {ts: row for ts, row in replay.iterrows()}

    # Re-run the live core analyzer on every prefix. This compares point-in-time
    # direction, setup, score and levels, rather than comparing final-bar state.
    for end in range(420, len(frame) + 1, 7):
        prefix = add_indicators(frame.iloc[:end])
        live = analyze(prefix)
        ts = prefix.index[-1]
        historical = replay_by_ts.get(ts)
        if live is None:
            assert historical is None
            continue
        assert historical is not None
        assert historical["direction"] == live["direction"]
        assert historical["setup"] == live["setup"].replace(" ", "_")
        assert int(historical["score"]) == live["score"]
        assert historical["entry"] == live["entry"]
        assert np.isclose(historical["sl"], live["sl"])
        assert np.isclose(historical["tp1"], live["tp1"])
        assert np.isclose(historical["tp2"], live["tp2"])


def test_historical_replay_respects_live_enriched_warmup():
    # 400 raw hourly bars yield fewer than 220 non-NaN enriched bars because
    # EMA200 is part of the indicator set; the live engine emits no signals.
    assert _current_rule_signals(_sample_market(400)).empty
