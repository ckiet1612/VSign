import json
from pathlib import Path

import pytest
from PIL import Image

from ml.body_framing import (
    PREPROCESSING_VERSION, apply_box, body_box, center_square, draw_plan, frame_clip, trim_span,
)

GOLDEN = json.loads((Path(__file__).resolve().parents[1] / "contracts/v1/framing_golden.json").read_text(encoding="utf-8"))


def test_golden_version():
    assert GOLDEN["version"] == PREPROCESSING_VERSION


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=lambda case: case["name"])
def test_golden_span_and_box(case):
    # Regenerate contracts/v1/framing_golden.json after an intentional algorithm change.
    assert list(trim_span(case["frames"], case["width"], case["height"])) == case["expected"]["span"]
    box = body_box(case["frames"], case["width"], case["height"])
    if case["expected"]["box"] is None:
        assert box is None
    else:
        assert box == pytest.approx(case["expected"]["box"], abs=1e-12)


def test_golden_draw_plans():
    for item in GOLDEN["draw_plans"]:
        plan = draw_plan(item["box"], item["width"], item["height"], item["size"])
        if item["expected"] is None:
            assert plan is None
        else:
            assert list(plan[0]) == pytest.approx(item["expected"]["source"], abs=1e-9)
            assert list(plan[1]) == item["expected"]["destination"]


def test_apply_box_pads_outside_the_image_black():
    image = Image.new("RGB", (100, 100), (200, 100, 50))
    framed = apply_box(image, {"x": -0.5, "y": 0.0, "width": 1.0, "height": 1.0}, size=20)
    assert framed.size == (20, 20)
    assert framed.getpixel((2, 10)) == (0, 0, 0)
    assert framed.getpixel((17, 10)) == (200, 100, 50)
    assert apply_box(image, center_square(100, 100), size=20).getpixel((0, 0)) == (200, 100, 50)


def test_frame_clip_samples_inside_the_span():
    pose = [[0.5, 0.3, 0.99], [0.62, 0.45, 0.99], [0.38, 0.45, 0.99], [0.66, 0.6, 0.9],
            [0.34, 0.6, 0.9], [0.64, 0.97, 0.9], [0.36, 0.97, 0.9]]
    frames = [{"t": index * 100.0, "pose": pose, "hands": [[0.5, 0.5, 0.4, 0.4, 0.6, 0.6]] if 10 <= index <= 20 else []}
              for index in range(30)]
    images = [Image.new("RGB", (64, 48), (index, 0, 0)) for index in range(30)]
    record = {"path": "clip.mp4", "width": 64, "height": 48, "frames": frames}
    clip = frame_clip(images, record, sample_count=4, size=32)
    reds = [image.getpixel((16, 16))[0] for image in clip]
    assert reds == [9, 13, 17, 21]
    with pytest.raises(ValueError):
        frame_clip(images[:-1], record)
