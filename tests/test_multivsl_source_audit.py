from pathlib import Path

import pytest

from ml.scripts.audit_multivsl_source import _parse_signer


def test_parse_signer_from_official_filename() -> None:
    path = Path("labels.csv")
    filename = "17_Vu_1-200___center_device11_signer17_center_ord1_42.mp4"

    assert _parse_signer(filename, path) == 17


def test_parse_signer_rejects_unknown_filename() -> None:
    with pytest.raises(RuntimeError, match="Không đọc được signer"):
        _parse_signer("video_without_signer.mp4", Path("labels.csv"))
