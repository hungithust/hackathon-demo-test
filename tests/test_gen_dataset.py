import json
from pathlib import Path

from config.settings import load_settings


def test_build_dataset_writes_split_jsonl_with_oracle_labels(tmp_path):
    from scripts.gen_dataset import build_dataset

    settings = load_settings({})
    out = build_dataset(settings, n_seeds=2, out_dir=str(tmp_path),
                        holdout_frac=0.5, use_teacher=False)   # $0 templated path

    train_path = Path(tmp_path) / "train.jsonl"
    test_path = Path(tmp_path) / "test.jsonl"
    assert train_path.exists() and test_path.exists()

    train_rows = [json.loads(l) for l in train_path.read_text().splitlines() if l]
    assert train_rows, "expected at least one informative training example"
    row = train_rows[0]
    assert set(row) == {"system", "user", "assistant"}
    assert set(row["assistant"]) == {"action", "reasoning", "added_delay_min"}

    # report carries coverage + informative fraction
    assert out["n_train"] == len(train_rows)
    assert 0.0 <= out["informative_fraction"] <= 1.0
    assert out["event_types"]                     # coverage by event type, non-empty


def test_build_dataset_is_deterministic(tmp_path):
    from scripts.gen_dataset import build_dataset
    settings = load_settings({})
    a = build_dataset(settings, n_seeds=2, out_dir=str(tmp_path / "a"),
                      holdout_frac=0.5, use_teacher=False)
    b = build_dataset(settings, n_seeds=2, out_dir=str(tmp_path / "b"),
                      holdout_frac=0.5, use_teacher=False)
    assert (Path(tmp_path / "a" / "train.jsonl").read_text()
            == Path(tmp_path / "b" / "train.jsonl").read_text())


def test_build_dataset_dpo_writes_prefs(tmp_path):
    from scripts.gen_dataset import build_dataset
    settings = load_settings({})
    out = build_dataset(settings, n_seeds=2, out_dir=str(tmp_path),
                        holdout_frac=0.5, use_teacher=False, dpo=True)

    prefs = Path(tmp_path) / "prefs.jsonl"
    assert prefs.exists()
    rows = [json.loads(l) for l in prefs.read_text().splitlines() if l]
    assert rows, "expected at least one preference pair"
    r = rows[0]
    assert set(r) == {"system", "user", "chosen", "rejected"}
    assert set(r["chosen"]) == {"action", "reasoning", "added_delay_min"}
    assert r["chosen"]["action"] != r["rejected"]["action"]   # informative pair
    assert out["n_prefs"] == len(rows)


def test_build_dataset_consequential_improves_multi_event_coverage(tmp_path):
    from scripts.gen_dataset import build_dataset
    settings = load_settings({"ORACLE_HORIZON_TICKS": "12", "ORACLE_MIN_GAP": "1.0"})
    out = build_dataset(settings, n_seeds=2, out_dir=str(tmp_path),
                        holdout_frac=0.5, use_teacher=False, consequential=True)
    assert out["consequential"] is True
    assert len(out["event_types"]) >= 4
    assert out["informative_fraction"] > 0.5


def test_build_dataset_reports_runtime_knobs(tmp_path):
    from scripts.gen_dataset import build_dataset
    settings = load_settings({
        "ROUTING_ENGINE": "cpu",
        "CONSEQUENTIAL_MIN_HORIZON_TICKS": "24",
    })
    out = build_dataset(settings, n_seeds=1, out_dir=str(tmp_path),
                        holdout_frac=0.5, use_teacher=False, consequential=True,
                        workers=1)
    assert out["workers"] == 1
    assert out["routing_engine"] == "cpu"
    assert out["consequential_min_horizon_ticks"] == 24
