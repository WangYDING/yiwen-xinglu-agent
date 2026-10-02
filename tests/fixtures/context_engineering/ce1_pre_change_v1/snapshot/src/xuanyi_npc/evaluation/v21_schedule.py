"""Single source of truth for the V2.1 slim execution schedule."""
from __future__ import annotations

from collections import Counter, defaultdict
import random
from typing import Iterable


TRACK_TASKS = {
    "G": ("T01", "T07", "T09", "T16", "T17", "T23"),
    "C": ("C01", "C02", "C09", "C10"),
    "M": ("MV01", "MV06"),
}
TRACK_CONDITIONS = {"G": ("A1",), "C": ("A0", "A1"), "M": ("M0", "M1")}
REPEATS = (1, 2, 3)
SCHEDULE_SEED = 20260920


def build_execution_order(tracks: tuple[str, ...] = ("G", "C", "M")) -> list[dict]:
    """Return the original frozen 54-item order, deterministically."""
    order: list[dict] = []
    if "G" in tracks:
        g = [(task, repeat) for task in TRACK_TASKS["G"] for repeat in REPEATS]
        random.Random(SCHEDULE_SEED).shuffle(g)
        order.extend({"track":"G", "task_id":task, "condition":"A1", "repeat":repeat} for task, repeat in g)
    for track in (item for item in ("C", "M") if item in tracks):
        pairs = [(task, repeat) for task in TRACK_TASKS[track] for repeat in REPEATS]
        random.Random(SCHEDULE_SEED).shuffle(pairs)
        for task, repeat in pairs:
            conditions = list(TRACK_CONDITIONS[track])
            random.Random(f"{task}:{repeat}:{SCHEDULE_SEED}").shuffle(conditions)
            order.extend({"track":track, "task_id":task, "condition":condition, "repeat":repeat,
                          "pair_id":f"{task}_r{repeat:02d}"} for condition in conditions)
    return order


def normalize_order(order: Iterable[dict]) -> list[dict]:
    keys = ("track", "task_id", "condition", "repeat", "pair_id")
    return [{key:item[key] for key in keys if key in item} for item in order]


def validate_execution_order(order: Iterable[dict], *, require_canonical: bool = True,
                             tracks: tuple[str, ...] | None = None) -> list[str]:
    items = normalize_order(order); errors: list[str] = []
    if tracks is None:
        present={item.get("track") for item in items}
        tracks=("C","M") if present == {"C","M"} else ("G","C","M")
    expected = build_execution_order(tracks)
    if len(items) != len(expected): errors.append(f"expected {len(expected)} entries, found {len(items)}")
    identities=[(item.get("track"),item.get("task_id"),item.get("condition"),item.get("repeat")) for item in items]
    duplicates=[key for key,count in Counter(identities).items() if count > 1]
    if duplicates: errors.append(f"duplicate schedule entries: {duplicates}")
    expected_ids={(item["track"],item["task_id"],item["condition"],item["repeat"]) for item in expected}
    actual_ids=set(identities)
    missing=sorted(expected_ids-actual_ids); extra=sorted(actual_ids-expected_ids)
    if missing: errors.append(f"missing schedule entries: {missing}")
    if extra: errors.append(f"unexpected schedule entries: {extra}")
    grouped=defaultdict(list)
    for index,item in enumerate(items):
        if item.get("track") in {"C","M"}:
            grouped[(item.get("track"),item.get("task_id"),item.get("repeat"))].append((index,item.get("condition"),item.get("pair_id")))
    for (track,task,repeat), values in grouped.items():
        wanted=set(TRACK_CONDITIONS[track]); got={value[1] for value in values}
        if len(values) != len(wanted) or got != wanted:
            errors.append(f"condition grouping mismatch: {track}/{task}/r{repeat}: {values}")
        if values and (max(value[0] for value in values)-min(value[0] for value in values)+1 != len(values)):
            errors.append(f"non-contiguous pair: {track}/{task}/r{repeat}")
        if any(value[2] != f"{task}_r{repeat:02d}" for value in values):
            errors.append(f"pair_id mismatch: {track}/{task}/r{repeat}")
    if require_canonical and items != expected:
        first=next((i for i,(left,right) in enumerate(zip(items,expected)) if left != right), min(len(items),len(expected)))
        errors.append(f"schedule order differs from canonical at index {first}")
    return errors


def track_sequence(plan: dict, track: str) -> list[dict]:
    """Expand exactly what an execution entrypoint must pass to a pool runner."""
    tracks=tuple(plan.get("tracks", {}).keys()) or None
    errors=validate_execution_order(plan.get("execution_order", ()),tracks=tracks)
    if errors: raise ValueError("; ".join(errors))
    return [item for item in normalize_order(plan["execution_order"]) if item["track"] == track]
