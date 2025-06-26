import gurobipy as gp
from gurobipy import GRB

def generate_warm_start(data, vars):
    T = range(int(data["parameters"]["time_horizon"] / data["parameters"]["time_step"]))
    gens = data["generators"]
    buses = data["buses"]
    reserves = data["reserves"]
    warm_start = {}
    total_load = [sum(b["load_mw"][t] for b_id, b in buses.items()) for t in T]
    total_capacity = sum(max(g["p_mw"]) for g_id, g in gens.items() if g["type"] == "Thermal")
    dispatch_per_gen = {g_id: 0 for g_id in gens}
    for t in T:
        remaining_load = total_load[t]
        for g_id, g in sorted(gens.items(), key=lambda x: min(x[1]["p_cost"])):
            if g["type"] == "Thermal":
                p_max = max(g["p_mw"])
                p_min = min(g["p_mw"])
                if g["must_run"] or g["initial_status"] > 0:
                    vars["commit"][g_id, t].start = 1
                    dispatch = min(max(p_min, remaining_load), p_max)
                    vars["dispatch"][g_id, t].start = dispatch
                    dispatch_per_gen[g_id] += dispatch
                    remaining_load -= dispatch
                    if "r1" in g.get("reserve_eligibility", []):
                        reserve = min(p_max - dispatch, reserves.get("r1", {}).get("amount_mw", [0])[t])
                        vars["reserve"][g_id, t].start = reserve
                    vars["startup"][g_id, t].start = 0
                    vars["shutdown"][g_id, t].start = 0
                else:
                    vars["commit"][g_id, t].start = 0
                    vars["dispatch"][g_id, t].start = 0
                    if "r1" in g.get("reserve_eligibility", []):
                        vars["reserve"][g_id, t].start = 0
                    vars["startup"][g_id, t].start = 0
                    vars["shutdown"][g_id, t].start = 0
        for b_id in buses:
            vars["theta"][b_id, t].start = 0
            vars["balance_slack"][b_id, t].start = max(0, remaining_load)
        vars["reserve_slack"][t].start = 0
    return warm_start

def build_model(data, available_capacity_t0, max_demand, adjusted_reserve, config):
    model = gp.Model("SCUC")
    time_step = data["parameters"]["time_step"]
    T = range(int(data["parameters"]["time_horizon"] / time_step))
    gens = data["generators"]
    buses = data["buses"]
    lines = data["lines"]
    conts = data["contingencies"]
    reserves = data["reserves"]
    storage_units = data["storage_units"]
    include_contingencies = config.get("include_contingencies", True)
    fixed_generators = config.get("fixed_generators", [])
    ignore_lines = config.get("ignore_lines", [])
    use_warm_start = config.get("use_warm_start", False)
    cost_scale = config.get("cost_scale", DEFAULTS["cost_scale"])

    commit = model.addVars(
        [(g_id, t) for g_id, g in gens.items() if g["type"] == "Thermal" for t in T],
        vtype=GRB.BINARY, name="commit"
    )
    startup = model.addVars(
        [(g_id, t) for g_id, g in gens.items() if g["type"] == "Thermal" for t in T],
        vtype=GRB.BINARY, name="startup"
    )
    shutdown = model.addVars(
        [(g_id, t) for g_id, g in gens.items() if g["type"] == "Thermal" for t in T],
        vtype=GRB.BINARY, name="shutdown"
    )
    dispatch = model.addVars(
        [(g_id, t) for g_id, g in gens.items() for t in T], lb=0, name="dispatch"
    )
    reserve = model.addVars(
        [(g_id, t) for g_id, g in gens.items() if g["type"] == "Thermal" and g.get("reserve_eligibility", []) and "r1" in g["reserve_eligibility"] for t in T],
        lb=0, name="reserve"
    )
    theta = model.addVars(buses, T, lb=-GRB.INFINITY, ub=GRB.INFINITY, name="theta")
    reserve_slack = model.addVars(T, lb=0, name="reserve_slack")
    balance_slack = model.addVars(buses, T, lb=0, name="balance_slack")
    charge = model.addVars(storage_units, T, lb=0, name="charge")
    discharge = model.addVars(storage_units, T, lb=0, name="discharge")
    level = model.addVars(storage_units, T, lb=0, name="level")
    charge_binary = model.addVars(
        [(s_id, t) for s_id, s in storage_units.items() if not all(s["simultaneous"]) for t in T],
        vtype=GRB.BINARY, name="charge_binary"
    )

    if use_warm_start:
        generate_warm_start(data, {
            "commit": commit, "startup": startup, "shutdown": shutdown,
            "dispatch": dispatch, "reserve": reserve, "theta": theta,
            "reserve_slack": reserve_slack, "balance_slack": balance_slack,
            "charge": charge, "discharge": discharge, "level": level,
            "charge_binary": charge_binary
        })

    ref_bus = list(buses.keys())[0]
    for t in T:
        model.addConstr(theta[ref_bus, t] == 0, name=f"ref_bus_{t}")

    for g_id, g in gens.items():
        if g["type"] == "Thermal":
            p_mw = g["p_mw"]
            p_cost = [c * cost_scale for c in g["p_cost"]]  # Scale costs
            p_min, p_max = min(p_mw), max(p_mw)
            for t in T:
                model.addConstr(dispatch[g_id, t] >= p_min * commit[g_id, t], name=f"min_power_{g_id}_{t}")
                model.addConstr(dispatch[g_id, t] <= p_max * commit[g_id, t], name=f"max_power_{g_id}_{t}")
                if "r1" in g.get("reserve_eligibility", []):
                    model.addConstr(reserve[g_id, t] <= (p_max - dispatch[g_id, t]) * commit[g_id, t], name=f"reserve_limit_{g_id}_{t}")
                if t > 0:
                    model.addConstr(
                        dispatch[g_id, t] - dispatch[g_id, t - 1] <= g["ramp_up"] * time_step * commit[g_id, t - 1] + p_min * startup[g_id, t],
                        name=f"ramp_up_{g_id}_{t}"
                    )
                    model.addConstr(
                        dispatch[g_id, t - 1] - dispatch[g_id, t] <= g["ramp_down"] * time_step * commit[g_id, t] + p_min * shutdown[g_id, t],
                        name=f"ramp_down_{g_id}_{t}"
                    )
                else:
                    initial_on = 1 if g["must_run"] or g["initial_status"] > 0 else 0
                    model.addConstr(
                        dispatch[g_id, t] - g["initial_power"] <= g["ramp_up"] * time_step * initial_on + p_min * startup[g_id, t],
                        name=f"initial_ramp_up_{g_id}_{t}"
                    )
                    model.addConstr(
                        g["initial_power"] - dispatch[g_id, t] <= g["ramp_down"] * time_step * initial_on + p_min * shutdown[g_id, t],
                        name=f"initial_ramp_down_{g_id}_{t}"
                    )
            if g_id not in fixed_generators and not g["must_run"] and available_capacity_t0 >= max_demand + max(adjusted_reserve):
                initial_status = g["initial_status"]
                for t in range(min(T[-1] + 1, (int(g["min_downtime"] / time_step) if initial_status < 0 else int(g["min_uptime"] / time_step)))):
                    model.addConstr(commit[g_id, t] == (0 if initial_status < 0 else 1), name=f"initial_status_{g_id}_{t}")
            for t in range(int(g["min_uptime"] / time_step), T[-1] + 1):
                model.addConstr(
                    gp.quicksum(startup[g_id, tau] for tau in range(t - int(g["min_uptime"] / time_step) + 1, t + 1)) <= commit[g_id, t],
                    name=f"min_uptime_{g_id}_{t}"
                )
            for t in range(int(g["min_downtime"] / time_step), T[-1] + 1):
                model.addConstr(
                    gp.quicksum(shutdown[g_id, tau] for tau in range(t - int(g["min_downtime"] / time_step) + 1, t + 1)) <= 1 - commit[g_id, t],
                    name=f"min_downtime_{g_id}_{t}"
                )
            if g_id in fixed_generators or g["must_run"]:
                for t in T:
                    model.addConstr(commit[g_id, t] == 1, name=f"must_run_{g_id}_{t}")
            if g.get("commitment_status"):
                for t in T:
                    if g["commitment_status"][t] is not None:
                        model.addConstr(commit[g_id, t] == (1 if g["commitment_status"][t] else 0), name=f"fixed_commit_{g_id}_{t}")
        elif g["type"] == "Profiled":
            for t in T:
                model.addConstr(dispatch[g_id, t] >= g["min_power"][t], name=f"min_power_profiled_{g_id}_{t}")
                model.addConstr(dispatch[g_id, t] <= g["max_power"][t], name=f"max_power_profiled_{g_id}_{t}")

    for s_id, s in storage_units.items():
        for t in T:
            model.addConstr(charge[s_id, t] >= s["min_charge_rate"][t], name=f"min_charge_{s_id}_{t}")
            model.addConstr(charge[s_id, t] <= s["max_charge_rate"][t], name=f"max_charge_{s_id}_{t}")
            model.addConstr(discharge[s_id, t] >= s["min_discharge_rate"][t], name=f"min_discharge_{s_id}_{t}")
            model.addConstr(discharge[s_id, t] <= s["max_discharge_rate"][t], name=f"max_discharge_{s_id}_{t}")
            model.addConstr(level[s_id, t] >= s["min_level"][t], name=f"min_level_{s_id}_{t}")
            model.addConstr(level[s_id, t] <= s["max_level"][t], name=f"max_level_{s_id}_{t}")
            if not s["simultaneous"][t]:
                model.addConstr(charge[s_id, t] <= s["max_charge_rate"][t] * charge_binary[s_id, t], name=f"charge_binary_{s_id}_{t}")
                model.addConstr(discharge[s_id, t] <= s["max_discharge_rate"][t] * (1 - charge_binary[s_id, t]), name=f"discharge_binary_{s_id}_{t}")
        for t in T:
            if t == 0:
                model.addConstr(
                    level[s_id, t] == s["initial_level"] + (s["charge_eff"][t] * charge[s_id, t] - discharge[s_id, t] / s["discharge_eff"][t]) * time_step * (1 - s["loss_factor"]),
                    name=f"initial_level_{s_id}_{t}"
                )
            else:
                model.addConstr(
                    level[s_id, t] == level[s_id, t - 1] * (1 - s["loss_factor"]) + (s["charge_eff"][t] * charge[s_id, t] - discharge[s_id, t] / s["discharge_eff"][t]) * time_step,
                    name=f"level_{s_id}_{t}"
                )
        if s["last_min_level"] is not None and s["last_max_level"] is not None:
            model.addConstr(level[s_id, T[-1]] >= s["last_min_level"], name=f"last_min_level_{s_id}")
            model.addConstr(level[s_id, T[-1]] <= s["last_max_level"], name=f"last_max_level_{s_id}")

    for t in T:
        for b_id in buses:
            gen_sum = gp.quicksum(dispatch[g_id, t] for g_id, g in gens.items() if g["bus"] == b_id)
            storage_sum = gp.quicksum(discharge[s_id, t] - charge[s_id, t] for s_id, s in storage_units.items() if s["bus"] == b_id)
            load = buses[b_id]["load_mw"][t]
            inflow = (
                gp.quicksum(
                    (line["susceptance"] * (theta[line["source_bus"], t] - theta[line["target_bus"], t])
                     if line["target_bus"] == b_id
                     else line["susceptance"] * (theta[line["target_bus"], t] - theta[line["source_bus"], t]))
                    for l_id, line in lines.items() if l_id not in ignore_lines and (line["source_bus"] == b_id or line["target_bus"] == b_id)
                ) if lines else 0.0
            )
            model.addConstr(gen_sum + storage_sum + inflow + balance_slack[b_id, t] == load, name=f"power_balance_{b_id}_{t}")

    if lines and include_contingencies:
        for cont_name in ["base_case"] + list(conts.keys()):
            for l_id, line in lines.items():
                if l_id in ignore_lines or (cont_name != "base_case" and l_id in conts[cont_name].get("Affected lines", [])):
                    continue
                limit = line["normal_limit"] if cont_name == "base_case" else line["emergency_limit"]
                for t in T:
                    flow = line["susceptance"] * (theta[line["source_bus"], t] - theta[line["target_bus"], t])
                    model.addConstr(flow <= limit, name=f"flow_upper_{l_id}_{t}_{cont_name}")
                    model.addConstr(flow >= -limit, name=f"flow_lower_{l_id}_{t}_{cont_name}")
    elif lines:
        for l_id, line in lines.items():
            if l_id in ignore_lines:
                continue
            for t in T:
                flow = line["susceptance"] * (theta[line["source_bus"], t] - theta[line["target_bus"], t])
                model.addConstr(flow <= line["normal_limit"], name=f"flow_upper_{l_id}_{t}")
                model.addConstr(flow >= -line["normal_limit"], name=f"flow_lower_{l_id}_{t}")

    for r_id, res in reserves.items():
        eligible_gens = [g_id for g_id, g in gens.items() if g["type"] == "Thermal" and g.get("reserve_eligibility", []) and "r1" in g["reserve_eligibility"]]
        for t in T:
            if eligible_gens:
                model.addConstr(
                    gp.quicksum(reserve[g, t] for g in eligible_gens) >= res["amount_mw"][t] - reserve_slack[t],
                    name=f"reserve_{r_id}_{t}"
                )

    total_cost = gp.LinExpr()
    for g_id, g in gens.items():
        if g["type"] == "Thermal":
            p_mw = g["p_mw"]
            p_cost = [c * cost_scale for c in g["p_cost"]]
            for t in T:
                model.setPWLObj(dispatch[g_id, t], p_mw, p_cost)
                total_cost += g["startup_costs"][0] * cost_scale * startup[g_id, t]
        elif g["type"] == "Profiled":
            for t in T:
                total_cost += g["p_cost"][t] * cost_scale * dispatch[g_id, t]
    for s_id, s in storage_units.items():
        for t in T:
            total_cost += s["charge_cost"][t] * cost_scale * charge[s_id, t] + s["discharge_cost"][t] * cost_scale * discharge[s_id, t]
    for t in T:
        total_cost += reserve_slack[t] * reserves.get("r1", {}).get("penalty", DEFAULTS["reserve_penalty"]) * cost_scale
    for b_id in buses:
        for t in T:
            total_cost += balance_slack[b_id, t] * DEFAULTS["balance_penalty"] * cost_scale
    model.setObjective(total_cost, GRB.MINIMIZE)
    model.Params.TimeLimit = config["time_limit"]
    model.Params.MIPGap = config["mip_gap"]
    model.Params.Threads = 16
    model.Params.NumericFocus = 1
    if not config["verbose"]:
        model.Params.OutputFlag = 0
    return model, {
        "commit": commit, "dispatch": dispatch, "reserve": reserve, "theta": theta,
        "reserve_slack": reserve_slack, "balance_slack": balance_slack,
        "charge": charge, "discharge": discharge, "level": level
    }