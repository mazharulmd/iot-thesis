"""Which gateway owns which asset, and the MQTT topic names.

Topic names follow AWS IoT Core conventions so the same code works against
Mosquitto (local) and AWS IoT Core (cloud).
"""
from __future__ import annotations

SITE = "dc/hall1"
GATEWAYS = ["zone1", "zone2", "zone3", "zone4", "plant"]
PLANT_ASSETS = {"chiller", "pump1", "pump2", "ups1", "ups2", "crah5"}
RACKS_PER_ZONE = 5


def gateway_of(asset: str) -> str:
    """Gateway that owns an asset, e.g. rack07 -> zone2, crah3 -> zone3, pump1 -> plant."""
    if asset in PLANT_ASSETS:
        return "plant"
    if asset.startswith("rack"):
        return f"zone{(int(asset[4:]) - 1) // RACKS_PER_ZONE + 1}"
    for prefix in ("crah", "pdu"):
        if asset.startswith(prefix):
            return f"zone{int(asset[len(prefix):])}"
    raise ValueError(f"unknown asset {asset!r}")


N_ZONES = len(GATEWAYS) - 1
PLANT_COOLING = ("chiller", "pump1", "pump2")


def zone_assets(zone: int) -> list[str]:
    first = (zone - 1) * RACKS_PER_ZONE + 1
    return [f"rack{i:02d}" for i in range(first, first + RACKS_PER_ZONE)] + [f"pdu{zone}"]


def downstream(asset: str) -> list[str]:
    """Assets whose readings a fault on `asset` can move, from the physical dependencies.

    Used to group alerts: an unexplained anomaly on a downstream asset joins the upstream incident.
      chilled water plant -> every CRAH and rack (warmer supply air everywhere)
      zone CRAH           -> its zone's racks and PDU, and the neighbouring CRAHs (air spill/leakage)
      PDU                 -> its zone's racks and CRAH (more IT heat to remove)
      UPS                 -> the other UPS (load share)
    """
    if asset in PLANT_COOLING:
        return ([a for z in range(1, N_ZONES + 1) for a in zone_assets(z)]
                + [f"crah{z}" for z in range(1, N_ZONES + 2)] + [p for p in PLANT_COOLING if p != asset])
    if asset.startswith("crah") and 1 <= int(asset[4:]) <= N_ZONES:
        z = int(asset[4:])
        return zone_assets(z) + [f"crah{n}" for n in (z - 1, z + 1) if 1 <= n <= N_ZONES]
    if asset.startswith("pdu"):
        return zone_assets(int(asset[3:]))[:-1] + [f"crah{asset[3:]}"]
    if asset.startswith("ups"):
        return ["ups2" if asset == "ups1" else "ups1"]
    return []


def telemetry_topic(gw: str) -> str:
    return f"{SITE}/{gw}/telemetry"


TELEMETRY_FILTER = f"{SITE}/+/telemetry"


def shadow_topic(gw: str, suffix: str = "") -> str:
    """AWS IoT classic shadow topics: update, update/delta, update/accepted."""
    base = f"$aws/things/{gw}/shadow/update"
    return f"{base}/{suffix}" if suffix else base


SHADOW_UPDATE_FILTER = "$aws/things/+/shadow/update"


def shadow_get_topic(gw: str, suffix: str = "") -> str:
    """Devices publish to shadow/get on connect; the answer comes on shadow/get/accepted."""
    base = f"$aws/things/{gw}/shadow/get"
    return f"{base}/{suffix}" if suffix else base


SHADOW_GET_FILTER = "$aws/things/+/shadow/get"


def gateway_from_topic(topic: str) -> str:
    """Works for dc/hall1/<gw>/telemetry and $aws/things/<gw>/shadow/..."""
    return topic.split("/")[2]
