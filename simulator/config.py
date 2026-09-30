"""Physical parameters of the simulated data hall.

Values are round, plausible numbers for a small AI data hall. They are
documented here in one place so the thesis can report and justify them.
"""
from dataclasses import dataclass, field

CP_AIR = 1005.0      # J/(kg K)
CP_WATER = 4186.0    # J/(kg K)


@dataclass
class HallConfig:
    # Layout: 4 zones x 5 racks = 20 GPU racks
    n_zones: int = 4
    racks_per_zone: int = 5

    # Racks
    rack_rated_kw: float = 45.0          # nameplate
    rack_busy_frac: float = 0.90         # utilisation when a training job runs
    rack_idle_frac: float = 0.25         # utilisation when idle
    mean_busy_s: float = 2 * 3600.0      # mean job length
    mean_idle_s: float = 0.5 * 3600.0    # mean gap between jobs
    load_ramp_kw_per_s: float = 2.0      # jobs ramp up/down, not instantly
    air_kg_s_per_kw: float = 0.068       # server airflow demand (~120 CFM/kW)
    throttle_start_c: float = 32.0       # inlet temp where GPUs start throttling
    throttle_full_c: float = 40.0        # inlet temp where power is halved

    # Zones (air side)
    zone_heat_capacity_j_k: float = 4.0e6  # air + equipment thermal mass
    recirc_base: float = 0.05              # hot-air recirculation with enough airflow
    recirc_max: float = 0.90
    zone_leak_w_k: float = 1500.0          # conductive/leak exchange between adjacent zones
    spill_fraction: float = 0.5            # share of surplus CRAH air that spills to neighbours

    # CRAH units: one per zone plus one standby
    crah_max_air_kg_s: float = 22.0
    crah_fan_min_pct: float = 30.0
    crah_airflow_margin: float = 1.10      # auto mode supplies 110 % of IT demand
    crah_fan_ramp_pct_s: float = 2.0
    standby_start_delay_s: float = 60.0
    coil_approach_k: float = 6.0           # supply air above chilled water at full flow

    # Chilled water plant
    chw_setpoint_c: float = 14.0
    chw_setpoint_min_c: float = 8.0
    chw_nominal_flow_kg_s: float = 40.0
    pump_nominal_dp_kpa: float = 150.0
    pump_nominal_current_a: float = 30.0
    pump_nominal_vib_mm_s: float = 2.0
    pump_ramp_s: float = 20.0
    chiller_assist_factor: float = 0.3     # drift remaining when assist capacity runs

    # Power
    pdu_rated_kw: float = 260.0
    pdu_voltage_v: float = 400.0
    power_factor: float = 0.95
    ups_rated_kw: float = 1000.0
    ups_batt_nominal_v: float = 540.0
    ups_batt_ambient_c: float = 25.0
    ups_batt_tau_s: float = 1800.0

    # Sensors
    noise_temp_c: float = 0.10
    noise_power_rel: float = 0.005
    noise_flow_rel: float = 0.01
    noise_vib_mm_s: float = 0.10
    noise_current_rel: float = 0.01

    # ASHRAE recommended inlet range (A1)
    ashrae_min_c: float = 18.0
    ashrae_max_c: float = 27.0

    # Timing
    dt_s: float = 1.0                      # physics step
    publish_period_s: float = 10.0         # gateway message period

    @property
    def n_racks(self) -> int:
        return self.n_zones * self.racks_per_zone

    def rack_id(self, i: int) -> str:
        return f"rack{i + 1:02d}"

    def zone_of_rack(self, i: int) -> int:
        return i // self.racks_per_zone

    def neighbours(self, z: int) -> list[int]:
        return [n for n in (z - 1, z + 1) if 0 <= n < self.n_zones]


@dataclass
class ScenarioConfig:
    name: str = "normal"
    duration_s: float = 2 * 3600.0
    seed: int = 1
    start_time: str = "2026-12-01T10:00:00Z"
    warmup_s: float = 1800.0               # run before t=0 so the hall is in steady state
    initial_busy_frac: float = 0.8
    faults: list = field(default_factory=list)
    actions: list = field(default_factory=list)
