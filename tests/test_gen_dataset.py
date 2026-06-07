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
