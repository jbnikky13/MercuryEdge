from mercuryedge.walkforward import walk_forward


def row(i, status, historical, crossmarket, agreement, score=60):
    return {
        "signal_time": f"2026-01-{i + 1:02d}T00:00:00+00:00",
        "status": status,
        "historical_score": historical,
        "crossmarket_score": crossmarket,
        "crossmarket_agreement": agreement,
        "score": score,
    }


def test_walk_forward_separates_train_and_test():
    rows = []
    for i in range(80):
        rows.append(row(i, "TP1" if i % 2 == 0 else "SL", 5 if i % 3 else -5, 5, 0.8))
    report = walk_forward(rows, train_size=40, test_size=20, min_bucket=5)
    assert report["fold_count"] == 2
    first = report["folds"][0]
    assert first["train_end"] < first["test_start"]
    assert first["selected_test_samples"] >= 0
