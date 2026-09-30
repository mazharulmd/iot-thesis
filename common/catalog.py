"""Fault types: risk tier and the remediation playbook that handles each one."""

FAULT_CATALOG = {
    "crah_fan_failure":     ("low",    "cooling_unit_failover"),
    "sensor_stuck":         ("low",    "sensor_quarantine"),
    "sensor_drift":         ("low",    "sensor_quarantine"),
    "pump_degradation":     ("medium", "pump_switchover"),
    "chw_supply_drift":     ("medium", "chilled_water_recovery"),
    "rack_hotspot":         ("medium", "hotspot_mitigation"),
    "ups_battery_overheat": ("high",   "ups_load_transfer"),
    "pdu_overload":         ("high",   "rack_power_cap"),
    # Anything the diagnosis rules cannot explain goes to a human, never to automation.
    "unexplained":          ("low",    "notify_only"),
}
