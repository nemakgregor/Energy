import json
import numpy as np


def load_case(file_path):
    with open(file_path, "r") as f:
        return json.load(f)


def get_key_value(data, key, default=None):
    for alt_key in KEY_MAPPINGS.get(key, {key}):
        if alt_key in data:
            return data[alt_key]
    return default


def ensure_list(param, T, param_name, default=None):
    if isinstance(param, list):
        if len(param) != T:
            raise ValueError(
                f"Parameter '{param_name}': List length ({len(param)}) does not match time stamps ({T})"
            )
        return param
    elif isinstance(param, (int, float)):
        return [param] * T
    else:
        return [default] * T if default is not None else [0] * T


def find_T(data, time_horizon):
    list_lengths = set()
    for bus_id, bus in data.get("Buses", {}).items():
        load_mw = bus.get("Load (MW)", 0.0)
        if isinstance(load_mw, list):
            list_lengths.add(len(load_mw))
    for r_id, res in data.get("Reserves", {}).items():
        amount_mw = res.get("Amount (MW)", 0.0)
        if isinstance(amount_mw, list):
            list_lengths.add(len(amount_mw))
    for s_id, s in data.get("Storage units", {}).items():
        for key in [
            "Minimum level (MWh)",
            "Maximum level (MWh)",
            "Charge cost ($/MW)",
            "Discharge cost ($/MW)",
            "Charge efficiency",
            "Discharge efficiency",
            "Minimum charge rate (MW)",
            "Maximum charge rate (MW)",
            "Minimum discharge rate (MW)",
            "Maximum discharge rate (MW)",
            "Allow simultaneous charging and discharging",
        ]:
            param = s.get(key, None)
            if isinstance(param, list):
                list_lengths.add(len(param))
    if list_lengths:
        if len(list_lengths) > 1:
            raise ValueError("Inconsistent list lengths in data")
        return list_lengths.pop()
    return 1


def validate_data(data):
    errors = []
    warnings = []
    time_horizon = data["parameters"]["time_horizon"]
    time_step = data["parameters"]["time_step"]
    T = int(time_horizon / time_step)
    generators = data["generators"]
    for g_id, g in generators.items():
        g_type = g.get("type", "Thermal")
        if g_type not in ["Thermal", "Profiled"]:
            errors.append(f"Generator {g_id}: Invalid type ({g_type})")
        if not g["bus"]:
            errors.append(f"Generator {g_id}: Missing bus assignment")
        if g_type == "Thermal":
            if (
                not isinstance(g["p_mw"], list)
                or not isinstance(g["p_cost"], list)
                or len(g["p_mw"]) != len(g["p_cost"])
            ):
                errors.append(f"Generator {g_id}: Invalid production cost curve")
            if max(g["p_mw"]) <= 0:
                errors.append(
                    f"Generator {g_id}: Maximum capacity is non-positive ({max(g['p_mw'])} MW)"
                )
            if len(g["startup_costs"]) != len(g["startup_delays"]):
                errors.append(f"Generator {g_id}: Mismatched startup costs and delays")
            if g["must_run"] and g["initial_status"] < 0:
                warnings.append(
                    f"Generator {g_id}: Must-run with negative initial status. Setting to 1."
                )
                g["initial_status"] = 1
            if g["ramp_up"] <= 0 or g["ramp_down"] <= 0:
                warnings.append(f"Generator {g_id}: Non-positive ramping limits")
            if g["min_uptime"] < 1 or g["min_downtime"] < 1:
                errors.append(f"Generator {g_id}: Invalid min up/down times")
            if g.get("commitment_status") and (
                len(g["commitment_status"]) != T
                or any(cs not in [True, False, None] for cs in g["commitment_status"])
            ):
                errors.append(f"Generator {g_id}: Invalid commitment status")
            for t in range(min(T, g["min_uptime"])):
                if g["must_run"] or g["initial_status"] > 0:
                    if g["initial_power"] < min(g["p_mw"]) or g["initial_power"] > max(
                        g["p_mw"]
                    ):
                        errors.append(
                            f"Generator {g_id}: Initial power {g['initial_power']:.2f} outside bounds [{min(g['p_mw']):.2f}, {max(g['p_mw']):.2f}]"
                        )
        elif g_type == "Profiled":
            if g["min_power"] is None or g["max_power"] is None or g["p_cost"] is None:
                errors.append(
                    f"Generator {g_id}: Missing min_power, max_power, or cost"
                )
            if any(mp > mxp for mp, mxp in zip(g["min_power"], g["max_power"])):
                errors.append(f"Generator {g_id}: min_power exceeds max_power")
    buses = data["buses"]
    for b_id, b in buses.items():
        if any(l < 0 for l in b["load_mw"]):
            errors.append(f"Bus {b_id}: Negative load values")
    lines = data["lines"]
    for l_id, line in lines.items():
        if not line["source_bus"] or not line["target_bus"]:
            errors.append(f"Line {l_id}: Missing bus assignment")
        if line["susceptance"] == 0 or line["reactance"] <= 0:
            warnings.append(f"Line {l_id}: Invalid susceptance or reactance")
        if line["normal_limit"] <= 0 or line["emergency_limit"] <= 0:
            warnings.append(f"Line {l_id}: Non-positive flow limits")
    storage_units = data.get("storage_units", {})
    for s_id, s in storage_units.items():
        if not s["bus"]:
            errors.append(f"Storage {s_id}: Missing bus")
        if any(min_l > max_l for min_l, max_l in zip(s["min_level"], s["max_level"])):
            errors.append(f"Storage {s_id}: Min level exceeds max")
        for t in range(T):
            if s["min_charge_rate"][t] > s["max_charge_rate"][t]:
                errors.append(f"Storage {s_id}: Min charge rate exceeds max at t={t}")
            if s["min_discharge_rate"][t] > s["max_discharge_rate"][t]:
                errors.append(
                    f"Storage {s_id}: Min discharge rate exceeds max at t={t}"
                )
        if s["last_min_level"] is not None and s["last_max_level"] is not None:
            if s["last_min_level"] > s["last_max_level"]:
                errors.append(f"Storage {s_id}: Last period min level exceeds max")
    reserves = data["reserves"]
    for r_id, res in reserves.items():
        if any(r < 0 for r in res["amount_mw"]):
            errors.append(f"Reserve {r_id}: Negative requirement")
    total_capacity = sum(
        max(g["p_mw"]) if g["type"] == "Thermal" else max(g["max_power"])
        for g_id, g in generators.items()
    ) + sum(max(s["max_discharge_rate"]) for s_id, s in storage_units.items())
    available_capacity_t0 = sum(
        max(g["p_mw"])
        for g_id, g in generators.items()
        if g["type"] == "Thermal" and (g["must_run"] or g["initial_status"] > 0)
    )
    available_capacity_t0 += sum(
        max(g["max_power"]) for g_id, g in generators.items() if g["type"] == "Profiled"
    ) + sum(max(s["max_discharge_rate"]) for s_id, s in storage_units.items())
    max_demand = (
        max(sum(b["load_mw"][t] for b in buses.values()) for t in range(T)) if T else 0
    )
    max_reserve = (
        max(max(res["amount_mw"]) for res in reserves.values()) if reserves else 0
    )
    if total_capacity < max_demand + max_reserve:
        errors.append(
            f"Insufficient total capacity: {total_capacity:.2f} MW < {max_demand + max_reserve:.2f} MW"
        )
    if available_capacity_t0 < max_demand + max_reserve:
        warnings.append(
            f"Insufficient initial capacity: {available_capacity_t0:.2f} MW < {max_demand + max_reserve:.2f} MW"
        )
    for t in range(T):
        total_load = sum(b["load_mw"][t] for b_id, b in buses.items())
        if available_capacity_t0 < total_load + max_reserve:
            warnings.append(
                f"Insufficient capacity at t={t}: {available_capacity_t0:.2f} MW < {total_load + max_reserve:.2f} MW"
            )
    return (
        errors,
        warnings,
        available_capacity_t0,
        max_demand,
        [res["amount_mw"] for res in reserves.values()][0] if reserves else 0,
    )
