import json
from pathlib import Path

import pytest

from ml.personal_finetune import apply_curation


def row(label, source, split, name):
    return {"path": f"clips/{label}/{name}.mp4", "label": label, "source": source, "split": split}


ROWS = [
    row("Mua", "personal", "train", "p1"), row("Mua", "seated", "train", "HA_rep01"),
    row("Mua", "seated", "validation", "Nhu_rep01"), row("Mua", "standing", "test", "001"),
    row("Nồi cơm điện", "seated", "validation", "Nhu_rep01"), row("Nồi cơm điện", "seated", "train", "HA_rep01"),
    row("Gạo", "seated", "validation", "Nhu_rep01"),
]


def test_repository_curation_drops_other_mua_variants_and_nhu_rice_cooker():
    curation = json.loads(Path("ml/data/curation/sales30_curation_v1.json").read_text(encoding="utf-8"))
    kept, summary = apply_curation(ROWS, curation)
    assert [(r["label"], r["source"], Path(r["path"]).stem) for r in kept] == [
        ("Mua", "personal", "p1"), ("Nồi cơm điện", "seated", "HA_rep01"), ("Gạo", "seated", "Nhu_rep01")]
    assert sum(item["clips"] for item in summary["dropped"]) == 4


@pytest.mark.parametrize("rules", [[], [{"label": "Không có", "drop_sources": ["seated"], "reason": "x"}],
                                   [{"label": "Mua", "drop_sources": [], "reason": "x"}],
                                   [{"label": "Gạo", "drop_sources": ["personal"], "reason": "x"}]])
def test_curation_rejects_empty_unknown_or_no_op_rules(rules):
    with pytest.raises(ValueError):
        apply_curation(ROWS, {"rules": rules})
