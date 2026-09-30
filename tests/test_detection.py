"""Step 4 tests: detector runtimes, engine behaviour and the trained bundle."""
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest
from sklearn.ensemble import IsolationForest

from detection.data import by_gateway
from detection.engine import DetectionEngine
from detection.evaluate import expected_target, run_events
from detection.features import SIGNALS, WINDOW, base_signals, window_features, windows
from detection.models import Bundle, flatline_flags, if_score, lstm_ae_forward
from detection.train import export_forest
from simulator.config import ScenarioConfig
from simulator.runner import load_scenario, run_scenario

SCN = Path(__file__).resolve().parents[1] / "simulator" / "scenarios"


@lru_cache(maxsize=None)
def bundle() -> Bundle:
    return Bundle.load()


@lru_cache(maxsize=None)
def fault_run(name: str, seed: int = 11):
    scn, _ = load_scenario(SCN / f"{name}.yaml")
    scn.seed = seed
    res = run_scenario(scn, apply_actions=False)
    return res.messages, res.labels


# ---------------------------------------------------------------- runtimes match the training libraries
def test_numpy_isolation_forest_matches_sklearn():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(2000, 6))
    model = IsolationForest(n_estimators=50, max_samples=256, random_state=0).fit(x)
    arrays, denom = export_forest(model)
    probe = np.vstack([rng.normal(size=(300, 6)), rng.normal(5, 1, size=(20, 6))])
    np.testing.assert_allclose(if_score(probe, dict(arrays, denominator=denom)), -model.score_samples(probe),
                               rtol=1e-10, atol=1e-12)


def test_numpy_lstm_matches_jax():
    jnp = pytest.importorskip("jax.numpy")
    from detection.lstm_jax import init_params
    params = init_params(n=5, hidden=16, latent=4, seed=3)
    x = np.random.default_rng(1).normal(size=(7, WINDOW, 5))
    np.testing.assert_allclose(lstm_ae_forward(params, x, np),
                               np.asarray(lstm_ae_forward({k: jnp.asarray(v) for k, v in params.items()},
                                                          jnp.asarray(x), jnp)), rtol=1e-4, atol=1e-5)


# ---------------------------------------------------------------- features
def test_features_shapes_and_meaning():
    msgs = run_scenario(ScenarioConfig(duration_s=120, warmup_s=300)).messages
    zone = [m for m in msgs if m["gw"] == "zone2"]
    sig = base_signals(zone[0])
    assert set(sig) == {"rack06", "rack07", "rack08", "rack09", "rack10", "crah2", "pdu2"}
    kind, vec, raw = sig["rack07"]
    assert kind == "rack" and vec.shape == (len(SIGNALS["rack"]),)
    assert vec[1] == pytest.approx(raw["t_out"] - raw["t_in"])
    plant = base_signals(next(m for m in msgs if m["gw"] == "plant"))
    assert "pump2" not in plant and "crah5" not in plant        # idle standby units are not scored
    arr = np.stack([base_signals(m)["rack07"][1] for m in zone])
    w = windows(arr)
    assert w.shape == (len(zone) - WINDOW + 1, WINDOW, 5)
    assert window_features(w).shape == (w.shape[0], 20)


def test_flatline_rule():
    win = np.random.default_rng(0).normal(20, 0.1, size=(3, WINDOW, 5))
    win[1, :, 0] = 20.5                                          # t_in frozen in the second window
    assert list(flatline_flags("rack", win)) == [False, True, False]


# ---------------------------------------------------------------- engine
def test_online_and_offline_paths_agree():
    msgs, _ = fault_run("sensor_drift")
    eng = DetectionEngine(bundle(), "d2h")
    for gw, gm in by_gateway(msgs).items():
        offline = eng.process_series(gm)
        online = []
        for i in range(len(gm)):
            online += eng.process(gm[max(0, i - eng.messages_needed + 1): i + 1])
        key = lambda e: (e["seq"], e["asset"], e["fault_type"])  # noqa: E731
        assert sorted(map(key, offline)) == sorted(map(key, online)), gw


@pytest.mark.parametrize("fault", ["crah_fan_failure", "sensor_stuck", "pump_degradation", "rack_hotspot"])
def test_d2h_detects_and_diagnoses(fault):
    msgs, labels = fault_run(fault)
    lab = labels["faults"][0]
    want = (lab["type"], expected_target(lab))
    events = run_events(DetectionEngine(bundle(), "d2h"), msgs)
    hits = [e for e in events if (e["fault_type"], e["target"]) == want and e["t_s"] >= lab["start_s"]]
    assert hits, f"{fault} not detected; events: {[(e['t_s'], e['fault_type'], e['target']) for e in events]}"
    assert hits[0]["t_s"] - lab["start_s"] <= 600


def test_static_limits_miss_pump_wear():
    msgs, _ = fault_run("pump_degradation")
    events = run_events(DetectionEngine(bundle(), "d0"), msgs)
    assert not [e for e in events if e["fault_type"] == "pump_degradation"]


def test_no_automated_false_alarms_in_normal_operation():
    msgs = run_scenario(ScenarioConfig(duration_s=3 * 3600, seed=301)).messages
    events = run_events(DetectionEngine(bundle(), "d2h"), msgs)
    assert not [e for e in events if e["playbook"] != "notify_only"], events


def test_small_deviation_is_not_diagnosed_as_fault():
    eng = DetectionEngine(bundle(), "d2h")
    mu, sd = bundle().scaler("chiller", "base")
    win = np.tile(mu, (WINDOW, 1))
    win[-1, 0] = mu[0] + 0.5                  # 0.5 K above normal: high z-score but physically small
    assert eng.diagnose("chiller", "chiller", win)[0] == "unexplained"
    win[-1, 0] = mu[0] + 2.0
    assert eng.diagnose("chiller", "chiller", win)[0] == "chw_supply_drift"


def test_unknown_detector_rejected():
    with pytest.raises(ValueError):
        DetectionEngine(bundle(), "d9")


# ---------------------------------------------------------------- trained bundle
def test_bundle_is_complete():
    b = bundle()
    for kind in SIGNALS:
        assert b.has(kind), kind
        thr = b.types[kind]["thresholds"]
        assert thr["d1"] > 0 and thr["d2"] > 0
        assert b.forest(kind)["left"].shape[0] == 100
        assert set(b.ae_params(kind)) >= {"enc_wx", "dec_wx", "out_w"}
