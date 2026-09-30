"""Reduced-order thermal and electrical model of a data hall.

Layout
------
- 4 zones, each with 5 GPU racks, 1 CRAH unit and 1 PDU.
- 1 standby CRAH (crah5) that can be started and assigned to any zone.
- Chilled water plant: 1 chiller, 2 pumps (duty + standby).
- 2 UPS units sharing the IT load.

Air side, per zone z (lumped hot-aisle node T_hot):
    C dT_hot/dt = P_IT - m_eff * cp * (T_hot - T_sa) - UA * sum(T_hot - T_hot_neighbour)
Rack inlet mixes cold supply air with recirculated hot air:
    T_in = T_sa + r * (T_hot - T_sa),  r = r0 + max(0, 1 - supply / demand)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .config import CP_AIR, CP_WATER, HallConfig


def _ramp(current: float, target: float, max_step: float) -> float:
    if target > current:
        return min(target, current + max_step)
    return max(target, current - max_step)


@dataclass
class Crah:
    name: str
    zone: int | None                 # None for the standby unit until assigned
    status: str = "on"               # on | off | starting | failed
    fan_mode: str = "auto"           # auto | manual
    fan_manual_pct: float = 80.0
    fan_pct: float = 60.0
    start_timer: float = 0.0
    t_ret: float = 30.0


@dataclass
class Pump:
    name: str
    status: str = "on"               # on | off
    speed: float = 1.0               # 0..1, ramps
    health: float = 1.0              # 1 = new, lower = degraded (set by faults)
    flow: float = 0.0


@dataclass
class Ups:
    name: str
    load_kw: float = 0.0
    t_batt: float = 26.0
    fault_heat_k_per_min: float = 0.0   # set by faults


@dataclass
class DataHall:
    cfg: HallConfig
    rng: np.random.Generator
    t: float = 0.0
    flagged_sensors: set = field(default_factory=set)

    def __post_init__(self) -> None:
        c = self.cfg
        n = c.n_racks
        self.rack_busy = np.zeros(n, dtype=bool)
        self.rack_next_switch = np.zeros(n)
        self.rack_power = np.zeros(n)            # kW, actual
        self.rack_cap = np.full(n, np.inf)       # kW, commanded power cap
        self.rack_force_frac = np.full(n, np.nan)  # set by overload fault
        self.rack_hotspot = np.zeros(n)          # 0..1 local airflow loss (fault)
        self.rack_noise = np.zeros(n)            # slow AR(1) load wiggle
        self.rack_t_in = np.full(n, 21.0)
        self.rack_t_out = np.full(n, 35.0)
        self.t_hot = np.full(c.n_zones, 33.0)
        self.zone_power = np.zeros(c.n_zones)
        self.crahs = [Crah(f"crah{z + 1}", z) for z in range(c.n_zones)]
        self.standby = Crah(f"crah{c.n_zones + 1}", None, status="off", fan_pct=0.0)
        self.pumps = [Pump("pump1"), Pump("pump2", status="off", speed=0.0)]
        self.ups = [Ups("ups1"), Ups("ups2")]
        self.ups_share1 = 0.5
        self.chw_sp = c.chw_setpoint_c
        self.chw_drift = 0.0                     # K, set by faults
        self.chw_assist = False
        self.t_chw_sup = self.chw_sp
        self.t_chw_ret = self.chw_sp + 4.0
        self.t_sa = self.chw_sp + c.coil_approach_k
        self.q_air = np.zeros(c.n_zones)         # W removed by air per zone

    # ------------------------------------------------------------------ setup
    def init_load(self, busy_frac: float) -> None:
        c = self.cfg
        self.rack_busy = self.rng.random(c.n_racks) < busy_frac
        for i in range(c.n_racks):
            self.rack_next_switch[i] = self._draw_duration(self.rack_busy[i])
            self.rack_power[i] = self._rack_demand(i)

    def _draw_duration(self, busy: bool) -> float:
        mean = self.cfg.mean_busy_s if busy else self.cfg.mean_idle_s
        return self.t + float(self.rng.exponential(mean))

    def _rack_demand(self, i: int) -> float:
        c = self.cfg
        if not math.isnan(self.rack_force_frac[i]):
            return c.rack_rated_kw * self.rack_force_frac[i]
        frac = c.rack_busy_frac if self.rack_busy[i] else c.rack_idle_frac
        return c.rack_rated_kw * frac * (1.0 + self.rack_noise[i])

    # ------------------------------------------------------------------ physics
    def step(self, dt: float) -> None:
        c = self.cfg
        self.t += dt

        # 1. IT load: job on/off process, caps, thermal throttling, ramping
        self.rack_noise = 0.995 * self.rack_noise + self.rng.normal(0, 0.002, c.n_racks)
        for i in range(c.n_racks):
            if self.t >= self.rack_next_switch[i]:
                self.rack_busy[i] = not self.rack_busy[i]
                self.rack_next_switch[i] = self._draw_duration(self.rack_busy[i])
            target = min(self._rack_demand(i), self.rack_cap[i])
            # GPUs throttle when their inlet air is too hot
            over = self.rack_t_in[i] - c.throttle_start_c
            if over > 0:
                target *= max(0.5, 1.0 - 0.5 * over / (c.throttle_full_c - c.throttle_start_c))
            self.rack_power[i] = _ramp(self.rack_power[i], target, c.load_ramp_kw_per_s * dt)

        z_of = np.array([c.zone_of_rack(i) for i in range(c.n_racks)])
        self.zone_power = np.array([self.rack_power[z_of == z].sum() for z in range(c.n_zones)])
        m_rack = np.maximum(self.rack_power * c.air_kg_s_per_kw, 1e-3)
        m_it = np.array([m_rack[z_of == z].sum() for z in range(c.n_zones)])

        # 2. CRAH fans (local auto control follows IT airflow demand)
        m_own = np.zeros(c.n_zones)
        for crah in self.crahs:
            m_own[crah.zone] += self._update_crah(crah, m_it[crah.zone], dt)
        if self.standby.zone is not None:
            m_own[self.standby.zone] += self._update_crah(self.standby, m_it[self.standby.zone], dt)
        else:
            self._update_crah(self.standby, 0.0, dt)

        # 3. Chilled water plant
        total_flow = 0.0
        for p in self.pumps:
            p.speed = _ramp(p.speed, 1.0 if p.status == "on" else 0.0, dt / c.pump_ramp_s)
            p.flow = c.chw_nominal_flow_kg_s * p.speed * (0.4 + 0.6 * p.health)
            total_flow += p.flow
        flow_factor = min(max(total_flow / c.chw_nominal_flow_kg_s, 0.05), 1.3)
        drift = self.chw_drift * (c.chiller_assist_factor if self.chw_assist else 1.0)
        self.t_chw_sup = self.chw_sp + drift
        approach = c.coil_approach_k * (1.0 / max(flow_factor, 0.15)) ** 0.6
        self.t_sa = self.t_chw_sup + approach

        # 4. Airflow: surplus CRAH air spills into neighbouring zones
        surplus = np.maximum(0.0, m_own - m_it)
        keep = m_own - c.spill_fraction * surplus
        spill_in = np.zeros(c.n_zones)
        spill_to = {}
        for z in range(c.n_zones):
            nbs = c.neighbours(z)
            for nb in nbs:
                share = c.spill_fraction * surplus[z] / len(nbs)
                spill_in[nb] += share
                spill_to[(z, nb)] = share
        m_eff = keep + spill_in

        # 5. Zone energy balance (explicit Euler)
        self.q_air = m_eff * CP_AIR * (self.t_hot - self.t_sa)
        leak = np.array([
            c.zone_leak_w_k * sum(self.t_hot[z] - self.t_hot[nb] for nb in c.neighbours(z))
            for z in range(c.n_zones)
        ])
        d_t = (self.zone_power * 1000.0 - self.q_air - leak) / c.zone_heat_capacity_j_k
        self.t_hot = self.t_hot + d_t * dt

        # 6. Rack inlet / outlet temperatures
        for i in range(c.n_racks):
            z = z_of[i]
            share = m_eff[z] * (m_rack[i] / m_it[z]) * (1.0 - self.rack_hotspot[i])
            r = min(c.recirc_max, c.recirc_base + max(0.0, 1.0 - share / m_rack[i]))
            self.rack_t_in[i] = self.t_sa + r * (self.t_hot[z] - self.t_sa)
            self.rack_t_out[i] = self.rack_t_in[i] + self.rack_power[i] * 1000.0 / (m_rack[i] * CP_AIR)

        # 7. CRAH return air temperatures (mix of air they collect)
        for crah in self.crahs + [self.standby]:
            z = crah.zone
            if z is None:
                crah.t_ret = self.t_sa
                continue
            num = keep[z] * self.t_hot[z]
            den = keep[z]
            for nb in c.neighbours(z):
                num += spill_to.get((z, nb), 0.0) * self.t_hot[nb]
                den += spill_to.get((z, nb), 0.0)
            crah.t_ret = num / den if den > 1e-6 else self.t_hot[z]

        # 8. Chilled water return
        q_total = max(float(self.q_air.sum()), 0.0)
        self.t_chw_ret = self.t_chw_sup + q_total / (max(total_flow, 1.0) * CP_WATER)

        # 9. UPS load and battery temperature
        total_kw = float(self.rack_power.sum())
        self.ups[0].load_kw = total_kw * self.ups_share1
        self.ups[1].load_kw = total_kw * (1.0 - self.ups_share1)
        half_load = 0.5 * c.n_racks * c.rack_rated_kw * c.rack_busy_frac
        for u in self.ups:
            frac = u.load_kw / c.ups_rated_kw
            t_eq = c.ups_batt_ambient_c + 3.0 * frac
            heat = u.fault_heat_k_per_min / 60.0 * (u.load_kw / half_load)
            u.t_batt += ((t_eq - u.t_batt) / c.ups_batt_tau_s + heat) * dt

    def _update_crah(self, crah: Crah, m_it_zone: float, dt: float) -> float:
        c = self.cfg
        if crah.status == "starting":
            crah.start_timer += dt
            if crah.start_timer >= c.standby_start_delay_s:
                crah.status = "on"
        if crah.status == "on":
            if crah.fan_mode == "manual":
                target = crah.fan_manual_pct
            else:
                target = 100.0 * c.crah_airflow_margin * m_it_zone / c.crah_max_air_kg_s
                target = min(100.0, max(c.crah_fan_min_pct, target))
            crah.fan_pct = _ramp(crah.fan_pct, target, c.crah_fan_ramp_pct_s * dt)
        else:  # off, starting or failed: fan stopped
            crah.fan_pct = _ramp(crah.fan_pct, 0.0, 10.0 * dt)
        return crah.fan_pct / 100.0 * c.crah_max_air_kg_s

    # ------------------------------------------------------------------ commands
    def apply_command(self, asset: str, desired: dict) -> dict:
        """Apply one asset's desired state (as a device shadow would). Returns what was applied."""
        c = self.cfg
        applied = {}
        if "sensor_flag" in desired:
            self.flagged_sensors.add(f"{asset}.{desired['sensor_flag']}")
            applied["sensor_flag"] = desired["sensor_flag"]

        if asset.startswith("crah"):
            crah = self.standby if asset == self.standby.name else self._crah(asset)
            if "zone" in desired and crah is self.standby:
                crah.zone = int(desired["zone"]) - 1
                applied["zone"] = crah.zone + 1
            if "fan_pct" in desired:
                crah.fan_mode = "manual"
                crah.fan_manual_pct = float(min(100.0, max(c.crah_fan_min_pct, desired["fan_pct"])))
                applied["fan_pct"] = crah.fan_manual_pct
            if desired.get("fan_mode") == "auto":
                crah.fan_mode = "auto"
                applied["fan_mode"] = "auto"
            if "status" in desired and crah.status != "failed":
                if desired["status"] == "on" and crah.status == "off":
                    crah.status, crah.start_timer = "starting", 0.0
                    if crah is self.standby and "fan_pct" not in desired:
                        crah.fan_mode = "manual"
                        crah.fan_manual_pct = 80.0
                elif desired["status"] == "off":
                    crah.status = "off"
                applied["status"] = desired["status"]
        elif asset.startswith("pump"):
            pump = next(p for p in self.pumps if p.name == asset)
            if "status" in desired:
                pump.status = desired["status"]
                applied["status"] = pump.status
        elif asset == "chiller":
            if "sp" in desired:
                self.chw_sp = max(c.chw_setpoint_min_c, float(desired["sp"]))
                applied["sp"] = self.chw_sp
            if "assist" in desired:
                self.chw_assist = desired["assist"] in (True, "on")
                applied["assist"] = "on" if self.chw_assist else "off"
        elif asset.startswith("rack"):
            i = int(asset[4:]) - 1
            if "cap_kw" in desired:
                cap = desired["cap_kw"]
                self.rack_cap[i] = np.inf if cap in (None, "none") else float(cap)
                applied["cap_kw"] = cap
        elif asset.startswith("ups"):
            if "load_share" in desired:
                share = min(1.0, max(0.0, float(desired["load_share"])))
                self.ups_share1 = share if asset == "ups1" else 1.0 - share
                applied["load_share"] = share
        if not applied:
            raise ValueError(f"unsupported command for {asset}: {desired}")
        return applied

    def controls(self, asset: str) -> dict:
        """The asset's full controllable state, as a gateway reports it in the device shadow.

        Reporting the whole state (not only what a command changed) keeps desired and reported
        comparable: a key that no longer applies is reported as None, which clears it.
        """
        if asset.startswith("crah"):
            crah = self.standby if asset == self.standby.name else self._crah(asset)
            state = {"status": crah.status, "fan_mode": crah.fan_mode,
                     "fan_pct": round(crah.fan_manual_pct, 1) if crah.fan_mode == "manual" else None}
            if crah is self.standby:
                state["zone"] = crah.zone + 1 if crah.zone is not None else None
        elif asset.startswith("pump"):
            state = {"status": next(p for p in self.pumps if p.name == asset).status}
        elif asset == "chiller":
            state = {"sp": round(self.chw_sp, 2), "assist": "on" if self.chw_assist else "off"}
        elif asset.startswith("rack"):
            cap = self.rack_cap[int(asset[4:]) - 1]
            state = {"cap_kw": None if np.isinf(cap) else float(cap)}
        elif asset.startswith("ups"):
            state = {"load_share": round(self.ups_share1 if asset == "ups1" else 1.0 - self.ups_share1, 3)}
        else:
            state = {}
        flags = sorted(s.split(".", 1)[1] for s in self.flagged_sensors if s.split(".", 1)[0] == asset)
        if flags or asset.startswith("rack"):
            state["sensor_flag"] = flags[0] if len(flags) == 1 else (flags or None)
        return state

    def _crah(self, name: str) -> Crah:
        return next(x for x in self.crahs if x.name == name)

    # ------------------------------------------------------------------ readings
    def true_readings(self) -> dict:
        """Noise-free values grouped as gateway -> asset -> signal."""
        c = self.cfg
        out: dict = {}
        for z in range(c.n_zones):
            gw: dict = {}
            for k in range(c.racks_per_zone):
                i = z * c.racks_per_zone + k
                gw[c.rack_id(i)] = {
                    "t_in": self.rack_t_in[i],
                    "t_out": self.rack_t_out[i],
                    "p_kw": self.rack_power[i],
                }
            crah = self.crahs[z]
            gw[crah.name] = {
                "t_sup": self.t_sa,
                "t_ret": crah.t_ret,
                "fan_pct": crah.fan_pct,
                "status": crah.status,
            }
            p_kw = self.zone_power[z]
            gw[f"pdu{z + 1}"] = {
                "p_kw": p_kw,
                "i_a": p_kw * 1000.0 / (math.sqrt(3) * c.pdu_voltage_v * c.power_factor),
                "load_pct": 100.0 * p_kw / c.pdu_rated_kw,
            }
            out[f"zone{z + 1}"] = gw

        plant: dict = {
            "chiller": {
                "t_sup": self.t_chw_sup,
                "t_ret": self.t_chw_ret,
                "sp": self.chw_sp,
                "assist": "on" if self.chw_assist else "off",
            }
        }
        for p in self.pumps:
            running = p.speed > 0.01
            plant[p.name] = {
                "status": p.status,
                "flow_lps": p.flow,
                "dp_kpa": c.pump_nominal_dp_kpa * (p.flow / c.chw_nominal_flow_kg_s) ** 2,
                "vib_mms": (c.pump_nominal_vib_mm_s + 6.0 * (1.0 - p.health)) if running else 0.1,
                "i_a": (c.pump_nominal_current_a + 10.0 * (1.0 - p.health)) * p.speed,
            }
        for u in self.ups:
            plant[u.name] = {
                "load_kw": u.load_kw,
                "t_batt": u.t_batt,
                "v_batt": c.ups_batt_nominal_v - 0.2 * (u.t_batt - c.ups_batt_ambient_c),
            }
        sb = self.standby
        plant[sb.name] = {
            "status": sb.status,
            "zone": (sb.zone + 1) if sb.zone is not None else 0,
            "fan_pct": sb.fan_pct,
            "t_sup": self.t_sa,
            "t_ret": sb.t_ret,
        }
        out["plant"] = plant
        return out
