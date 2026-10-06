"""Compute calibrated red flag passages from signal occurrences."""

from bisect import bisect_right
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

CALIBRATION_PATH = Path(__file__).with_name("signal_calibration.json")


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def load_calibration():
    value = json.loads(CALIBRATION_PATH.read_text())
    if len(value["categories"]) != 26:
        raise ValueError("Signal calibration must contain 26 categories.")
    if value["window_words"] < 1 or not 0 < value["stride_words"] <= value["window_words"]:
        raise ValueError("Signal window dimensions are invalid.")
    for category in value["categories"].values():
        if set(category["points"]) != {"L", "M", "H"} or category["min_concepts"] < 1:
            raise ValueError("Signal category calibration is invalid.")
    value["hash"] = text_digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return value


def word_ranges(text):
    ranges, previous, byte_offset = [], 0, 0
    for match in re.finditer(r"\S+", text):
        byte_offset += len(text[previous:match.start()].encode("utf-8"))
        end = byte_offset + len(match.group().encode("utf-8"))
        ranges.append((byte_offset, end))
        byte_offset, previous = end, match.end()
    return ranges


def score_concepts(hits, category, rule, noisy):
    best = {}
    for hit in hits:
        flags = set(hit.get("flags", []))
        if flags & {"quoted", "boilerplate"}:
            continue
        tier = "L" if (category, hit["term"]) in noisy else hit["tier"]
        points = rule["points"][tier] * (0.5 if "negated" in flags else 1)
        concept = hit["concept"]
        if concept not in best or points > best[concept][0]:
            best[concept] = (points, tier)
    low = min(rule["l_cap"], sum(points for points, tier in best.values() if tier == "L"))
    points = low + sum(points for points, tier in best.values() if tier != "L")
    return points, len(best) >= rule["min_concepts"] and points >= rule["threshold"]


def compute_clusters(text: str, hits: list[dict], calibration=None) -> list[dict]:
    calibration = calibration or load_calibration()
    words = word_ranges(text)
    if not words:
        return []
    starts = [start for start, _ in words]
    width, stride = calibration["window_words"], calibration["stride_words"]
    window_starts = [0]
    while window_starts[-1] + width < len(words):
        window_starts.append(window_starts[-1] + stride)
    noisy = {tuple(row) for row in calibration["noisy_terms"]}
    by_category = {}
    encoded = text.encode("utf-8")
    for hit in hits:
        start, end = int(hit["start"]), int(hit["end"])
        if not 0 <= start < end <= len(encoded):
            raise ValueError("A signal has invalid byte offsets.")
        if encoded[start:end].decode("utf-8") != hit["text"]:
            raise ValueError("A signal does not match its source bytes.")
        by_category.setdefault(hit["category"], []).append(hit)
    clusters = []
    for category, category_hits in sorted(by_category.items()):
        rule = calibration["categories"][category]
        windows = {}
        for hit in category_hits:
            word = bisect_right(starts, hit["start"]) - 1
            first = max(0, (word - width) // stride + 1)
            last = min(word // stride, len(window_starts) - 1)
            for window in range(first, last + 1):
                windows.setdefault(window, []).append(hit)
        current = None
        for window, window_hits in sorted(windows.items()):
            points, qualifies = score_concepts(window_hits, category, rule, noisy)
            if not qualifies:
                continue
            word_start = window_starts[window]
            start = words[word_start][0]
            end = max(words[min(word_start + width, len(words)) - 1][1],
                      max(hit["end"] for hit in window_hits))
            if current is not None and window == current["last_window"] + 1:
                current["end"] = max(current["end"], end)
                current["points"] = max(current["points"], points)
                current["last_window"] = window
            else:
                current = dict(category=category, start=start, end=end, points=points, last_window=window)
                clusters.append(current)
        for cluster in (row for row in clusters if row["category"] == category):
            start, end = cluster["start"], cluster["end"]
            cluster.pop("last_window")
            cluster["excerpt"] = encoded[start:end].decode("utf-8")
            retained = [hit for hit in category_hits if start <= hit["start"] and hit["end"] <= end]
            cluster["hit_starts"] = [hit["start"] - start for hit in retained]
            cluster["hit_ends"] = [hit["end"] - start for hit in retained]
    return clusters
