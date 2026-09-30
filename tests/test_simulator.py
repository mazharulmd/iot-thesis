"""Step 2 acceptance tests: every fault shows its symptom, and its remediation fixes it."""
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

from simulator.config import HallConfig, ScenarioConfig
from simulator.model import DataHall
from simulator.runner import load_scenario, run_scenario

SCN = Path(__file__).resolve().parents[1] / "simulator" / "scenarios"
FAULT_START = 1800


@lru_cache(maxsize=None)
def run(name: str, actions: bool = True):
    scn, _ = load_scenario(SCN / f"{name}.yaml")
    return run_scenario(scn, apply_actions=actions).frame


def during(f):
    return f[f.t_s >= FAULT_START]


def before(f):
    return f[f.t_s < FAULT_START]


def last(f, minutes=10):
    return f[f.t_s >= f.t_s.max() - minutes * 60]


def inlets(f):
    return f[[c for c in f.columns if c.endswith(".t_in")]]


# ---------------------------------------------------------------- normal operation
def test_normal_inlets_stay_in_ashrae_range():
    t_in = inlets(run("normal"))
    assert t_in.min().min() >= 18.0
    assert t_in.max().max() <= 27.0


def test_normal_energy_balance():
    f = run("normal")
    half = f[f.t_s > f.t_s.max() / 2]
    err = abs(half["truth.q_air_kw"].mean() - half["truth.it_kw"].mean()) / half["truth.it_kw"].mean()
    assert err < 0.02, f"air removes {err:.1%} more/less heat than IT produces"


def test_normal_load_varies_like_gpu_jobs():
    p = run("normal")["zone1.pdu1.p_kw"]
    assert p.max() - p.min() > 20, "zone power should vary as jobs start and stop"


# ---------------------------------------------------------------- fault symptoms and recovery
def test_crah_fan_failure():
    bad, good = run("crah_fan_failure", False), run("crah_fan_failure")
    assert during(bad)["zone2.rack07.t_in"].max() > 35
    assert last(bad)["zone2.crah2.fan_pct"].max() < 1
    assert last(good)["truth.max_t_in"].max() < 27


def test_rack_hotspot_is_local():
    bad, good = run("rack_hotspot", False), run("rack_hotspot")
    assert during(bad)["zone2.rack07.t_in"].max() > 27
    assert during(bad)["zone2.rack06.t_in"].max() < 23
    assert last(good)["zone2.rack07.t_in"].mean() < 27


def test_chw_supply_drift():
    bad, good = run("chw_supply_drift", False), run("chw_supply_drift")
    gap = during(bad)["plant.chiller.t_sup"] - during(bad)["plant.chiller.sp"]
    assert gap.max() > 5
    assert during(bad)["truth.max_t_in"].max() > 27
    assert last(good)["truth.max_t_in"].max() < 27


def test_pump_degradation_is_early_warning():
    bad, good = run("pump_degradation", False), run("pump_degradation")
    base = before(bad)
    assert during(bad)["plant.pump1.vib_mms"].max() - base["plant.pump1.vib_mms"].mean() > 3
    assert last(bad)["plant.pump1.flow_lps"].mean() < 0.75 * base["plant.pump1.flow_lps"].mean()
    # stays below the 7.1 mm/s ISO alarm: a static threshold would miss it
    assert during(bad)["plant.pump1.vib_mms"].max() < 7.1
    assert last(good)["plant.pump2.flow_lps"].mean() > 35
    assert abs(last(good)["zone1.crah1.t_sup"].mean() - base["zone1.crah1.t_sup"].mean()) < 0.5


def test_ups_battery_overheat():
    bad, good = run("ups_battery_overheat", False), run("ups_battery_overheat")
    assert during(bad)["plant.ups1.t_batt"].max() > 35
    assert last(good)["plant.ups1.t_batt"].mean() < 30
    assert last(good)["plant.ups1.load_kw"].mean() < 1


def test_pdu_overload():
    bad, good = run("pdu_overload", False), run("pdu_overload")
    assert during(bad)["zone3.pdu3.load_pct"].max() > 95
    assert last(good)["zone3.pdu3.load_pct"].mean() < 85


def test_sensor_stuck_goes_flat():
    f = run("sensor_stuck", False)
    assert during(f)["zone2.rack07.t_in"].std() == 0
    assert before(f)["zone2.rack07.t_in"].std() > 0.05


def test_sensor_drift_is_implausible():
    f = run("sensor_drift", False)
    end = last(f)
    assert (end["zone3.rack12.t_in"] - end["zone3.rack11.t_in"]).mean() > 10
    # the air itself did not change: outlet stays where it was
    assert abs(end["zone3.rack12.t_out"].mean() - before(f)["zone3.rack12.t_out"].mean()) < 3


# ---------------------------------------------------------------- mechanics
def test_labels_are_not_in_published_messages():
    scn, _ = load_scenario(SCN / "sensor_stuck.yaml")
    scn.duration_s = 1900
    res = run_scenario(scn)
    text = str(res.messages)
    assert "sensor_stuck" not in text and "label" not in text
    assert res.labels["faults"][0]["type"] == "sensor_stuck"


def test_message_format():
    res = run_scenario(ScenarioConfig(duration_s=60))
    gws = {m["gw"] for m in res.messages}
    assert gws == {"zone1", "zone2", "zone3", "zone4", "plant"}
    m = res.messages[0]
    assert m["ts"].endswith("Z") and m["seq"] == 1
    assert set(m["assets"]) >= {"rack01", "crah1", "pdu1"}


def test_same_seed_same_result():
    a = run_scenario(ScenarioConfig(duration_s=600, seed=42)).frame
    b = run_scenario(ScenarioConfig(duration_s=600, seed=42)).frame
    assert a.equals(b)


def test_unknown_command_is_rejected():
    hall = DataHall(HallConfig(), np.random.default_rng(0))
    with pytest.raises(ValueError):
        hall.apply_command("crah1", {"colour": "blue"})


def test_speed_one_simulated_day_under_a_minute():
    t0 = time.time()
    run_scenario(ScenarioConfig(duration_s=3600, warmup_s=0))
    assert (time.time() - t0) * 24 < 60
