"""Minimal emulation of AWS IoT classic device shadows.

A shadow holds `desired` and `reported` state. When `desired` changes and differs
from `reported`, a delta is published to the device. A value of None deletes a key,
as in AWS.
"""
from __future__ import annotations

import copy
import time


def _equal(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(float(a) - float(b)) < 1e-6
    return a == b


def compute_delta(desired: dict, reported: dict) -> dict:
    """Keys in desired whose values differ from reported (recursively)."""
    delta = {}
    for key, want in desired.items():
        have = reported.get(key) if isinstance(reported, dict) else None
        if isinstance(want, dict):
            sub = compute_delta(want, have if isinstance(have, dict) else {})
            if sub:
                delta[key] = sub
        elif not _equal(want, have):
            delta[key] = want
    return delta


def merge(base: dict, patch: dict) -> dict:
    """Deep merge; None removes a key."""
    out = copy.deepcopy(base)
    for key, val in patch.items():
        if val is None:
            out.pop(key, None)
        elif isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], val)
        else:
            out[key] = copy.deepcopy(val)
    return out


class ShadowStore:
    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}

    def get(self, thing: str) -> dict:
        return self.docs.setdefault(thing, {"desired": {}, "reported": {}, "version": 0})

    def update(self, thing: str, state: dict) -> tuple[dict, dict]:
        """Apply an update ({"desired": ..., "reported": ...}). Returns (document, delta)."""
        doc = self.get(thing)
        for section in ("desired", "reported"):
            if section in state:
                # an explicit null clears the whole section, as in AWS
                doc[section] = {} if state[section] is None else merge(doc[section], state[section])
        doc["version"] += 1
        doc["timestamp"] = int(time.time())
        return doc, compute_delta(doc["desired"], doc["reported"])
