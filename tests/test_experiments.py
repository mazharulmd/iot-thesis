"""Step 7 tests: metrics definitions, the M1 human, E4 conditions, batch rows and statistics helpers."""
from types import SimpleNamespace

import numpy as np
import pytest

from experiments.analysis import holm, median_ci, mwu
from experiments.batch import FIELDS, human_delay, run_one, scenario
from experiments.closed_loop import fault_scenario, run_closed_loop
from experiments.metrics import run_metrics


def fake_run(inlets: list[float], fault_at: float = 0.0):
    """A CRAH-failure run where every zone-2 rack inlet follows `inlets` (one value per 10 s tick)."""
    truth = []
    for i, v in enumerate(inlets):
        zone2 = {f"rack{r:02d}": {"t_in": v} for r in range(6, 11)}
        truth.append({"t_s": i * 10.0, "wall_start": "2026-12-01T10:00:00Z",
                      "values": {"zone2": zone2, "plant": {"chiller": {"sp": 14.0}}}})
    return SimpleNamespace(labels=[{"type": "crah_fan_failure", "target": "crah2", "start_s": fault_at}],
                           events=[], incidents=[], human_actions=[], truth=truth, messages=[], commands=[],
                           alerts=[], dropped=0)


def test_recovery_and_exposure_definitions():
    m = run_metrics(fake_run([20, 29, 29, 25, 21, 21]))
    assert m["exceeded"] and m["recovered"] and m["mttr_s"] == 30.0
    assert m["exposure"] == pytest.approx(5 * 2 * 2 * 10 / 60, abs=1e-3)   # 5 racks x 2 K x 2 ticks
    never = run_metrics(fake_run([20, 22, 23, 22]))
    assert never["mttr_s"] == 0.0 and not never["exceeded"]          # prevented
    stuck = run_metrics(fake_run([20, 30, 25, 31]))
    assert stuck["recovered"] is False and stuck["mttr_s"] is None     # censored
    assert stuck["detected"] is False and stuck["wrong_actions"] == 0


def test_human_delay_is_paired_and_lognormal():
    assert human_delay(1001) == human_delay(1001)
    delays = [human_delay(s) for s in range(1, 2001)]
    assert 540 < np.median(delays) < 660
    assert 0.8 < np.percentile(delays, 95) / 1370 < 1.2               # ~22.8 min at the 95th percentile


def test_alert_only_human_carries_out_the_playbook_by_hand():
    res = run_closed_loop(fault_scenario("crah_fan_failure", after=900, seed=1003), detector="d0",
                          automation="notify", human={"delay_s": 300.0, "stage_gap_s": 120.0})
    inc = res.incidents[0]
    assert inc["status"] == "notified" and not [s for s in inc["log"] if s["step"] == "act"]
    first, second = res.human_actions
    detected = next(e["t_s"] for e in res.events if e["fault_type"] == "crah_fan_failure")
    assert first["t_s"] == pytest.approx(detected + 300, abs=10) and second["t_s"] - first["t_s"] == pytest.approx(120, abs=10)
    m = run_metrics(res)
    assert m["recovered"] and m["action_s"] == pytest.approx(first["t_s"] - 600, abs=1)


def test_load_surge_is_normal_operation_without_actions():
    spec = {"suite": "e4_surge", "mode": "M3", "fault": "load_surge", "seed": 1002, "param": ""}
    scn = scenario(spec)
    assert scn.faults[0].type == "load_surge" and scn.faults[0].is_normal_event
    row = run_one(spec)
    assert not row.get("error") and row["false_remediations"] == 0 and row["commands"] == 0


def test_message_loss_still_detects_and_mitigates():
    res = run_closed_loop(fault_scenario("crah_fan_failure", after=900, seed=1004), drop_rate=0.2)
    assert 0.1 < res.dropped / len(res.messages) < 0.3
    m = run_metrics(res)
    assert m["detected"] and m["recovered"] and m["incident_status"] == "mitigated"


def test_batch_row_has_every_field():
    row = run_one({"suite": "e1", "mode": "M2", "fault": "rack_hotspot", "seed": 1001, "param": ""})
    assert not row.get("error"), row.get("error")
    assert set(row) <= set(FIELDS) and row["detected"] and row["wrong_actions"] == 0


def test_statistics_helpers():
    m, lo, hi = median_ci(list(range(101)))
    assert m == 50 and lo < 50 < hi
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    p, r = mwu([10, 11, 12, 13, 14, 15], [1, 2, 3, 4, 5, 6])
    assert p < 0.01 and r == pytest.approx(1.0)
    assert mwu([5, 5], [5, 5]) == (1.0, 0.0)
