import json
import numpy as np

from config import KEY_MAPPINGS, DEFAULTS


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


def load_case(filepath):
    with open(filepath, "rt") as f:
        data = json.load(f)
    time_horizon = get_key_value(
        data.get("Parameters", {}), "time_horizon", DEFAULTS["time_horizon"]
    )
    time_step_min = data.get("Parameters", {}).get("Time step (min)", None)
    if time_step_min is not None:
        time_step = time_step_min / 60.0
        T = int(time_horizon / time_step)
    else:
        T = find_T(data, time_horizon)
        time_step = time_horizon / T if T > 0 else 1.0
    case_data = {
        "parameters": {"time_horizon": time_horizon, "time_step": time_step},
        "generators": {},
        "buses": {},
        "lines": {},
        "contingencies": data.get("Contingencies", {}),
        "storage_units": {},
        "reserves": {},
    }
    for gen_id, gen_data in data.get("Generators", {}).items():
        g_type = get_key_value(gen_data, "type", "Thermal")
        if g_type == "Thermal":
            p_mw = get_key_value(gen_data, "p_mw")
            case_data["generators"][gen_id] = {
                "type": g_type,
                "bus": get_key_value(gen_data, "bus"),
                "p_mw": p_mw,
                "p_cost": get_key_value(gen_data, "p_cost"),
                "startup_delays": get_key_value(gen_data, "startup_delays", [1]),
                "startup_costs": get_key_value(gen_data, "startup_costs", [0]),
                "ramp_up": get_key_value(gen_data, "ramp_up", DEFAULTS["ramp_up"]),
                "ramp_down": get_key_value(
                    gen_data, "ramp_down", DEFAULTS["ramp_down"]
                ),
                "startup_limit": get_key_value(
                    gen_data, "startup_limit", DEFAULTS["startup_limit"]
                ),
                "shutdown_limit": get_key_value(
                    gen_data, "shutdown_limit", DEFAULTS["shutdown_limit"]
                ),
                "must_run": get_key_value(gen_data, "must_run", False),
                "min_uptime": get_key_value(
                    gen_data, "min_uptime", DEFAULTS["min_uptime"]
                ),
                "min_downtime": get_key_value(
                    gen_data, "min_downtime", DEFAULTS["min_downtime"]
                ),
                "initial_status": get_key_value(gen_data, "initial_status", 0),
                "initial_power": get_key_value(gen_data, "initial_power", 0),
                "reserve_eligibility": get_key_value(
                    gen_data, "reserve_eligibility", []
                ),
                "commitment_status": get_key_value(gen_data, "commitment_status", None),
            }
        elif g_type == "Profiled":
            min_power = get_key_value(gen_data, "min_power", 0.0)
            max_power = get_key_value(gen_data, "max_power", 0.0)
            p_cost = get_key_value(gen_data, "p_cost", 0.0)
            min_power = ensure_list(
                min_power, T, f"Generator {gen_id} min_power", default=0.0
            )
            max_power = ensure_list(
                max_power, T, f"Generator {gen_id} max_power", default=0.0
            )
            p_cost = ensure_list(p_cost, T, f"Generator {gen_id} p_cost", default=0.0)
            case_data["generators"][gen_id] = {
                "type": g_type,
                "bus": get_key_value(gen_data, "bus"),
                "min_power": min_power,
                "max_power": max_power,
                "p_cost": p_cost,
            }
    for bus_id, bus_data in data.get("Buses", {}).items():
        load_mw = get_key_value(bus_data, "load_mw", 0.0)
        load_mw = ensure_list(load_mw, T, f"Bus {bus_id} load_mw", default=0.0)
        case_data["buses"][bus_id] = {"load_mw": load_mw}
    for line_id, line_data in data.get("Transmission lines", {}).items():
        case_data["lines"][line_id] = {
            "source_bus": get_key_value(line_data, "source_bus"),
            "target_bus": get_key_value(line_data, "target_bus"),
            "reactance": get_key_value(line_data, "reactance", float("inf")),
            "susceptance": get_key_value(line_data, "susceptance", 0.0) / 100,
            "normal_limit": get_key_value(
                line_data, "normal_limit", DEFAULTS["normal_limit"]
            ),
            "emergency_limit": get_key_value(
                line_data, "emergency_limit", DEFAULTS["emergency_limit"]
            ),
            "penalty": get_key_value(
                line_data, "flow_penalty", DEFAULTS["flow_penalty"]
            ),
        }
    for s_id, s_data in data.get("Storage units", {}).items():
        s = {
            "bus": get_key_value(s_data, "bus"),
            "min_level": ensure_list(
                get_key_value(s_data, "storage_min_level", 0.0),
                T,
                f"Storage {s_id} min_level",
                default=0.0,
            ),
            "max_level": ensure_list(
                get_key_value(
                    s_data, "storage_max_level", DEFAULTS["storage_max_level"]
                ),
                T,
                f"Storage {s_id} max_level",
                default=DEFAULTS["storage_max_level"],
            ),
            "charge_cost": ensure_list(
                get_key_value(
                    s_data, "storage_charge_cost", DEFAULTS["storage_charge_cost"]
                ),
                T,
                f"Storage {s_id} charge_cost",
                default=DEFAULTS["storage_charge_cost"],
            ),
            "discharge_cost": ensure_list(
                get_key_value(
                    s_data, "storage_discharge_cost", DEFAULTS["storage_discharge_cost"]
                ),
                T,
                f"Storage {s_id} discharge_cost",
                default=DEFAULTS["storage_discharge_cost"],
            ),
            "charge_eff": ensure_list(
                get_key_value(
                    s_data, "storage_charge_eff", DEFAULTS["storage_charge_eff"]
                ),
                T,
                f"Storage {s_id} charge_eff",
                default=DEFAULTS["storage_charge_eff"],
            ),
            "discharge_eff": ensure_list(
                get_key_value(
                    s_data, "storage_discharge_eff", DEFAULTS["storage_discharge_eff"]
                ),
                T,
                f"Storage {s_id} discharge_eff",
                default=DEFAULTS["storage_discharge_eff"],
            ),
            "loss_factor": get_key_value(
                s_data, "storage_loss_factor", DEFAULTS["storage_loss_factor"]
            ),
            "min_charge_rate": ensure_list(
                get_key_value(s_data, "storage_min_charge_rate", 0.0),
                T,
                f"Storage {s_id} min_charge_rate",
                default=0.0,
            ),
            "max_charge_rate": ensure_list(
                get_key_value(
                    s_data, "storage_max_charge_rate", DEFAULTS["storage_charge_rate"]
                ),
                T,
                f"Storage {s_id} max_charge_rate",
                default=DEFAULTS["storage_charge_rate"],
            ),
            "min_discharge_rate": ensure_list(
                get_key_value(s_data, "storage_min_discharge_rate", 0.0),
                T,
                f"Storage {s_id} min_discharge_rate",
                default=0.0,
            ),
            "max_discharge_rate": ensure_list(
                get_key_value(
                    s_data,
                    "storage_max_discharge_rate",
                    DEFAULTS["storage_discharge_rate"],
                ),
                T,
                f"Storage {s_id} max_discharge_rate",
                default=DEFAULTS["storage_discharge_rate"],
            ),
            "initial_level": get_key_value(
                s_data, "storage_initial_level", DEFAULTS["storage_initial_level"]
            ),
            "last_min_level": get_key_value(s_data, "storage_last_min_level", 0.0),
            "last_max_level": get_key_value(
                s_data, "storage_last_max_level", DEFAULTS["storage_max_level"]
            ),
            "simultaneous": ensure_list(
                get_key_value(s_data, "storage_simultaneous", True),
                T,
                f"Storage {s_id} simultaneous",
                default=True,
            ),
        }
        case_data["storage_units"][s_id] = s
    for r_id, r_data in data.get("Reserves", {}).items():
        amount_mw = get_key_value(r_data, "reserve_amount", 0.0)
        amount_mw = ensure_list(amount_mw, T, f"Reserve {r_id} amount_mw", default=0.0)
        case_data["reserves"][r_id] = {
            "amount_mw": amount_mw,
            "penalty": get_key_value(
                r_data, "reserve_penalty", DEFAULTS["reserve_penalty"]
            ),
        }
    errors, warnings, available_capacity_t0, max_demand, adjusted_reserve = (
        validate_data(case_data)
    )
    if errors:
        raise ValueError("\n".join(errors))
    for warning in warnings:
        print(warning)
    return case_data, available_capacity_t0, max_demand, adjusted_reserve
