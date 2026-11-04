"""Find text on one image, and name its script, with two small CPU models.

A PP-OCRv6 tiny detector finds the text boxes. A Tesseract-style line model names the script
of the longest lines. One Tesseract call then reads a stack of those lines with the script
model, so the worker can identify the language from the output.

The detector steps follow the PaddleOCR DB post-process as RapidOCR 3.10.0 packages it, and
the line steps follow `modules/detection/script_detection.py` of ogkalu2/comic-translate.
Both are Apache-2.0. The expansion of a box uses the rectangle form of the same formula.

Each model session uses one thread. The service pool bounds the number of images at a time,
and without this limit ONNX Runtime spends about 4 CPU seconds on one page.
"""

import json
import os
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image

MODELS = Path(os.getenv("TEXT_DETECTION_MODELS", str(Path(__file__).resolve().parent / "models")))

#: Longest side of the detector input.
DETECTOR_SIDE = 960
#: A pixel with this probability belongs to a text region.
PIXEL_THRESHOLD = 0.3
#: A box under this score is dropped.
BOX_THRESHOLD = 0.5
#: The unclip ratio of the DB post-process.
UNCLIP_RATIO = 1.6
MAX_CONTOURS = 1000

#: An image has text with this many boxes of a score of `CONFIDENT_SCORE` or more.
#: Measured on real scans: no false positive on 40 images, and the misses hold few words.
MIN_CONFIDENT_BOXES = 3
CONFIDENT_SCORE = 0.6

#: Lines that vote on the script.
SCRIPT_LINES = 6
#: Lines of the winning script that Tesseract reads.
READ_LINES = 4
#: Height of a line in the stack that Tesseract reads, in pixels.
STACK_LINE_HEIGHT = 48
STACK_GUTTER = 16

SCRIPT_INPUT_HEIGHT = 48
SCRIPT_NULL = 0
SCRIPT_BLANK = 2

#: Labels of the line model that name no script.
NOT_SCRIPTS = {"Common", "Joined", "Broken", "NULL"}

#: A script name for each script model where the two differ.
SCRIPT_NAMES = {"HanS": "Han", "HanT": "Han", "Fraktur": "Latin", "Vietnamese": "Latin"}


@dataclass
class Detection:
    has_text: bool
    box_count: int
    confident_boxes: int
    script: str = ""
    model: str = ""
    text: str = ""


def _session(name: str) -> ort.InferenceSession:
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    return ort.InferenceSession(str(MODELS / name), options, providers=["CPUExecutionProvider"])


@lru_cache(maxsize=1)
def _detector() -> ort.InferenceSession:
    return _session("PP-OCRv6_det_tiny.onnx")


@lru_cache(maxsize=1)
def _script_model() -> Tuple[ort.InferenceSession, List[str]]:
    labels = json.loads((MODELS / "osd_labels.json").read_text(encoding="utf-8"))
    return _session("osd_lstm.onnx"), labels


def _detector_input(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    ratio = min(1.0, DETECTOR_SIDE / max(height, width))
    sized_height = max(32, int(round(int(height * ratio) / 32) * 32))
    sized_width = max(32, int(round(int(width * ratio) / 32) * 32))
    sized = cv2.resize(image, (sized_width, sized_height))
    return ((sized.astype("float32") / 255.0 - 0.5) / 0.5).transpose(2, 0, 1)[None].astype(np.float32)


def _box_score(probability: np.ndarray, points: np.ndarray) -> float:
    height, width = probability.shape
    x_min = int(np.clip(np.floor(points[:, 0].min()), 0, width - 1))
    x_max = int(np.clip(np.ceil(points[:, 0].max()), 0, width - 1))
    y_min = int(np.clip(np.floor(points[:, 1].min()), 0, height - 1))
    y_max = int(np.clip(np.ceil(points[:, 1].max()), 0, height - 1))
    mask = np.zeros((y_max - y_min + 1, x_max - x_min + 1), dtype=np.uint8)
    cv2.fillPoly(mask, (points - [x_min, y_min]).reshape(1, -1, 2).astype(np.int32), 1)
    return cv2.mean(probability[y_min:y_max + 1, x_min:x_max + 1], mask)[0]


def find_boxes(image: np.ndarray) -> List[Tuple[np.ndarray, float]]:
    """Text boxes in image pixels as `(corners, score)`. `image` is BGR."""
    session = _detector()
    input_name = session.get_inputs()[0].name
    probability = session.run(None, {input_name: _detector_input(image)})[0][0, 0]
    mask = cv2.dilate((probability > PIXEL_THRESHOLD).astype(np.uint8), np.ones((2, 2), np.uint8))
    contours = cv2.findContours(mask * 255, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[-2]
    map_height, map_width = probability.shape
    scale = np.array([image.shape[1] / map_width, image.shape[0] / map_height])
    limits = np.array([image.shape[1], image.shape[0]])
    boxes = []
    for contour in contours[:MAX_CONTOURS]:
        center, (width, height), angle = cv2.minAreaRect(contour)
        if min(width, height) < 3:
            continue
        score = _box_score(probability, cv2.boxPoints((center, (width, height), angle)))
        if score < BOX_THRESHOLD:
            continue
        grow = UNCLIP_RATIO * width * height / (width + height)
        corners = cv2.boxPoints((center, (width + grow, height + grow), angle))
        boxes.append((np.clip(np.round(corners * scale), 0, limits).astype(np.int32), score))
    return boxes


def _crops(image: np.ndarray, boxes: Sequence[Tuple[np.ndarray, float]]) -> Tuple[List[np.ndarray], bool]:
    """The longest lines, and whether they stand on end."""
    flat, tall = [], []
    for corners, _ in boxes:
        x_min, y_min = corners.min(0)
        x_max, y_max = corners.max(0)
        width, height = x_max - x_min, y_max - y_min
        if width >= 3 * height and height >= 8:
            flat.append((width, image[y_min:y_max, x_min:x_max]))
        elif height >= 3 * width and width >= 8:
            tall.append((height, image[y_min:y_max, x_min:x_max]))
    chosen, sideways = (tall, True) if len(tall) > len(flat) else (flat, False)
    return [crop for _, crop in sorted(chosen, key=lambda item: -item[0])[:SCRIPT_LINES]], sideways


def _dark_on_light(crop: np.ndarray) -> np.ndarray:
    """Invert a line whose light pixels are the minority, so light text becomes dark text."""
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return 255 - crop if (binary > 0).mean() < 0.5 else crop


def _percentile_of_extremes(buckets: np.ndarray, fraction: float) -> float:
    """The `STATS::ile` value of a 256 bucket histogram, as Tesseract computes it."""
    total = int(buckets.sum())
    if total == 0:
        return 0.0
    target = min(max(fraction * total, 1.0), float(total))
    seen = 0
    index = 0
    while index <= 255 and seen < target:
        seen += int(buckets[index])
        index += 1
    return index - (seen - target) / buckets[index - 1] if index > 0 else 0.0


def _black_and_white(grey: np.ndarray) -> Tuple[float, float]:
    """The black and white points from the local extremes of the middle row."""
    minima = np.zeros(256, dtype=np.int64)
    maxima = np.zeros(256, dtype=np.int64)
    row = grey[grey.shape[0] // 2, :].astype(np.int64)
    for before, value, after in zip(row, row[1:], row[2:]):
        if (value < before and value <= after) or (value <= before and value < after):
            minima[value] += 1
        if (value > before and value >= after) or (value >= before and value > after):
            maxima[value] += 1
    if minima.sum() == 0:
        minima[0] = 1
    if maxima.sum() == 0:
        maxima[255] = 1
    return _percentile_of_extremes(minima, 0.25), _percentile_of_extremes(maxima, 0.75)


def _script_input(crop: np.ndarray) -> np.ndarray:
    rgb = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
    width = max(1, round(rgb.width * SCRIPT_INPUT_HEIGHT / rgb.height))
    values = np.asarray(rgb.resize((width, SCRIPT_INPUT_HEIGHT), Image.BICUBIC), dtype=np.float64)
    grey = np.floor(0.3 * values[..., 0] + 0.5 * values[..., 1] + 0.2 * values[..., 2] + 0.5).astype(np.uint8)
    if float(np.median(grey)) < 64.0:
        grey = np.subtract(255, grey, dtype=np.uint8)
    black, white = _black_and_white(grey)
    contrast = (white - black) / 2.0 or 1.0
    return ((grey.astype(np.float32) - black) / contrast - 1.0)[None, None, :, :].astype(np.float32)


def line_script(crop: np.ndarray) -> str:
    """The script label of one line, such as `Latin` or `Hebrew-dn`, or an empty string."""
    session, labels = _script_model()
    scores = session.run(None, {"image": _script_input(crop)})[0]
    counts: Counter = Counter()
    previous = SCRIPT_BLANK
    for raw in scores.argmax(axis=1):
        index = int(raw)
        if index != SCRIPT_BLANK and index != previous:
            counts[index] += 1
        previous = index
    if not counts:
        return ""
    best = counts.most_common(1)[0][0]
    return "" if best == SCRIPT_NULL else labels[best]


def _agreement(labels: Sequence[str]) -> int:
    return max(Counter(labels).values(), default=0)


def _base_model(label: str) -> str:
    return label.removesuffix("-dn").removesuffix("_vert")


def _stack(crops: Sequence[np.ndarray]) -> np.ndarray:
    """One grey page of lines with stretched contrast. Tesseract reads it in one call."""
    lines = []
    for crop in crops:
        grey = cv2.normalize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), None, 0, 255, cv2.NORM_MINMAX)
        width = max(8, int(crop.shape[1] * STACK_LINE_HEIGHT / crop.shape[0]))
        lines.append(cv2.resize(grey, (width, STACK_LINE_HEIGHT)))
    width = max(line.shape[1] for line in lines) + 2 * STACK_GUTTER
    height = len(lines) * (STACK_LINE_HEIGHT + STACK_GUTTER) + STACK_GUTTER
    page = np.full((height, width), 255, np.uint8)
    for index, line in enumerate(lines):
        top = STACK_GUTTER + index * (STACK_LINE_HEIGHT + STACK_GUTTER)
        page[top:top + STACK_LINE_HEIGHT, STACK_GUTTER:STACK_GUTTER + line.shape[1]] = line
    return page


def decode_image(image_bytes: bytes) -> np.ndarray:
    """The first frame as a BGR array. The detector was measured on this order."""
    import io

    with Image.open(io.BytesIO(image_bytes)) as image:
        image.seek(0)
        if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
            rgba = image.convert("RGBA")
            ground = Image.new("RGB", rgba.size, "white")
            ground.paste(rgba, mask=rgba.getchannel("A"))
            rgb = ground
        else:
            rgb = image.convert("RGB")
    return cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)


def detect(image_bytes: bytes, read: Callable[[np.ndarray, str], str],
           available: Optional[Sequence[str]] = None) -> Detection:
    """Run the chain on one image. `read` gives the text of a page for a Tesseract model.

    `available` lists the installed Tesseract models. Debian names a script model `Latin`,
    with no `script/` folder.
    """
    image = decode_image(image_bytes)
    boxes = find_boxes(image)
    confident = sum(score >= CONFIDENT_SCORE for _, score in boxes)
    result = Detection(has_text=confident >= MIN_CONFIDENT_BOXES, box_count=len(boxes), confident_boxes=confident)
    if not result.has_text:
        return result
    crops, sideways = _crops(image, boxes)
    if not crops:
        return result
    crops = [_dark_on_light(crop) for crop in crops]
    if sideways:
        turned = [[cv2.rotate(crop, side) for crop in crops]
                  for side in (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE)]
        votes = [[line_script(crop) for crop in side] for side in turned]
        chosen = 0 if _agreement(votes[0]) >= _agreement(votes[1]) else 1
        crops, labels = turned[chosen], votes[chosen]
    else:
        labels = [line_script(crop) for crop in crops]
    if sum(label.endswith("-dn") for label in labels) * 2 > len(labels):
        crops = [cv2.rotate(crop, cv2.ROTATE_180) for crop in crops]
    models = ["Latin" if _base_model(label) == "Fraktur" else _base_model(label) for label in labels]
    votes_by_model = Counter(model for model in models if model and model not in NOT_SCRIPTS)
    if not votes_by_model:
        return result
    result.model = votes_by_model.most_common(1)[0][0]
    result.script = SCRIPT_NAMES.get(result.model, result.model)
    if available is not None and result.model not in available:
        return result
    lines = [crop for crop, model in zip(crops, models) if model == result.model][:READ_LINES]
    result.text = read(_stack(lines), result.model)
    return result
