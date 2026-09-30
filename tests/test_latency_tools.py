"""Latency window arithmetic used by make latency and make e2e."""
from tools.latency import describe, window


def snap(t, n, lat, handler, stamped=0, to_bridge=0, bridge=0, queue=0):
    return {"t": t, "lambda_msgs": n, "latency_sum_ms": lat, "cold_starts": 0, "stamped_count": stamped,
            "hist_sum_ms": handler / 2, "engine_sum_ms": 1.0 * n, "publish_sum_ms": 0.0, "handler_sum_ms": handler,
            "to_bridge_sum_ms": to_bridge, "bridge_sum_ms": bridge, "queue_sum_ms": queue}


def test_window_means_and_split():
    a = snap(0, 100, 10_000, 2_000, 100, 500, 1_000, 6_500)
    b = snap(10, 150, 20_000, 3_000, 150, 750, 1_500, 14_750)
    w = window(a, b)
    assert w["n"] == 50 and w["rate"] == 5
    assert w["latency_ms"] == 200 and w["handler_ms"] == 20
    assert (w["to_bridge_ms"], w["bridge_ms"], w["queue_ms"]) == (5, 10, 165)
    assert "queue 165" in describe(w)


def test_window_without_stamps_or_messages():
    a = snap(0, 10, 100, 50)
    assert window(a, a) == {"n": 0}
    w = window(a, snap(5, 20, 300, 100))
    assert w["queue_ms"] is None and "queue" not in describe(w)


def test_lambda_alive_counts_zero_seconds_ago():
    from tools.e2e_check import lambda_alive
    assert lambda_alive({"lambda_msgs": 5, "seen_s_ago": 0.0})
    assert not lambda_alive({"lambda_msgs": 5, "seen_s_ago": None})
    assert not lambda_alive({"lambda_msgs": 5, "seen_s_ago": 300.0})
    assert not lambda_alive({"lambda_msgs": 0, "seen_s_ago": 1.0})
