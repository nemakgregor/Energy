import numpy as np
import pandas as pd
from tabulate import tabulate
from typing import Dict, Any, Tuple, List
import pandapower as pp

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _bus_groups(net: pp.pandapowerNet) -> Tuple[List[int], List[int], List[int]]:
    slack = list(net.ext_grid.bus.values)
    pv = [b for b in net.gen.bus.values if b not in slack]
    pq = [b for b in net.bus.index if b not in slack + pv]
    return slack, pv, pq


def _ensure_tables(net: pp.pandapowerNet):
    if net.res_bus.empty:
        net.res_bus = pd.DataFrame(index=net.bus.index)
    if net.res_ext_grid.empty:
        net.res_ext_grid = pd.DataFrame(
            index=net.ext_grid.index, columns=["p_mw", "q_mvar"]
        )
    if not net.gen.empty and net.res_gen.empty:
        net.res_gen = pd.DataFrame(index=net.gen.index, columns=["p_mw", "q_mvar"])
    if not net.load.empty and net.res_load.empty:
        net.res_load = pd.DataFrame(index=net.load.index, columns=["p_mw", "q_mvar"])


def _recompute_lacpf_slack_gen(result: Dict[str, Any]):
    """If slack/gen values in net_lacpf are NaN, recompute using G/B."""
    net = result["net_lacpf"]
    _ensure_tables(net)

    if net.res_ext_grid["p_mw"].notna().all() and net.res_gen.q_mvar.notna().all():
        return  # already filled

    G: np.ndarray = result["G"]
    B: np.ndarray = result["B"]
    V = net.res_bus.vm_pu.values
    theta = np.deg2rad(net.res_bus.va_degree.values)
    nb = len(net.bus)

    P_calc = np.zeros(nb)
    Q_calc = np.zeros(nb)
    for i in range(nb):
        for j in range(nb):
            P_calc[i] += (
                V[i]
                * V[j]
                * (
                    G[i, j] * np.cos(theta[i] - theta[j])
                    + B[i, j] * np.sin(theta[i] - theta[j])
                )
            )
            Q_calc[i] += (
                V[i]
                * V[j]
                * (
                    G[i, j] * np.sin(theta[i] - theta[j])
                    - B[i, j] * np.cos(theta[i] - theta[j])
                )
            )

    sn = float(net.sn_mva)
    slack, pv, _ = _bus_groups(net)

    for idx, sb in enumerate(slack):
        net.res_ext_grid.at[idx, "p_mw"] = P_calc[sb] * sn
        net.res_ext_grid.at[idx, "q_mvar"] = Q_calc[sb] * sn

    for g_idx, gen in net.gen.iterrows():
        bus = int(gen.bus)
        if bus in pv:
            q_load = (
                net.load.loc[net.load.bus == bus, "q_mvar"].sum()
                if not net.load.empty
                else 0.0
            )
            net.res_gen.at[g_idx, "p_mw"] = gen.p_mw
            net.res_gen.at[g_idx, "q_mvar"] = (Q_calc[bus] + q_load / sn) * sn


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------


def _slack_row(net: pp.pandapowerNet, label: str):
    p = net.res_ext_grid.p_mw.sum() if not net.res_ext_grid.empty else 0.0
    q = net.res_ext_grid.q_mvar.sum() if not net.res_ext_grid.empty else 0.0
    return {
        "Network": label,
        "P_slack (MW)": round(p, 2),
        "Q_slack (MVar)": round(q, 2),
    }


def _pq_balance(net: pp.pandapowerNet):
    p_gen = net.res_gen.p_mw.sum() if not net.res_gen.empty else 0.0
    q_gen = net.res_gen.q_mvar.sum() if not net.res_gen.empty else 0.0
    p_load = net.res_load.p_mw.sum() if not net.res_load.empty else 0.0
    q_load = net.res_load.q_mvar.sum() if not net.res_load.empty else 0.0
    p_slack = net.res_ext_grid.p_mw.sum() if not net.res_ext_grid.empty else 0.0
    q_slack = net.res_ext_grid.q_mvar.sum() if not net.res_ext_grid.empty else 0.0
    return p_gen - p_load + p_slack, q_gen - q_load + q_slack


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------


def evaluate_regimes(result: Dict[str, Any], tol: float = 10.0):
    """Print detailed comparison tables for LACPF / NR / pp‑AC / DC."""

    # ---- unpack nets -------------------------------------------------
    net_lin: pp.pandapowerNet = result["net_lacpf"]
    net_nr: pp.pandapowerNet = result["net_nr"]
    net_ac: pp.pandapowerNet = result["net_ac"]
    net_dc: pp.pandapowerNet = result["net_dc"]

    for n in (net_lin, net_nr, net_ac, net_dc):
        _ensure_tables(n)

    # Fix missing slack/gen in linear AC
    _recompute_lacpf_slack_gen(result)

    # 1. Slack power summary ------------------------------------------
    slack_tbl = pd.DataFrame(
        [
            _slack_row(net_lin, "LACPF"),
            _slack_row(net_nr, "NR"),
            _slack_row(net_ac, "pp‑AC"),
            _slack_row(net_dc, "DC"),
        ]
    )
    print("=== Slack Power Comparison ===")
    print(tabulate(slack_tbl, headers="keys", tablefmt="psql", showindex=False))

    # 2. Bus voltage / angle errors vs pp‑AC ---------------------------
    Vm_ref = net_ac.res_bus.vm_pu.values
    Va_ref = net_ac.res_bus.va_degree.values

    df_bus = pd.DataFrame(index=net_ac.bus.index)
    for label, net in [("LACPF", net_lin), ("NR", net_nr), ("DC", net_dc)]:
        df_bus[f"V_{label}"] = np.round(net.res_bus.vm_pu.values, 4)
        df_bus[f"dV_{label}"] = np.round(np.abs(net.res_bus.vm_pu.values - Vm_ref), 4)
        df_bus[f"Ang_{label}"] = np.round(net.res_bus.va_degree.values, 4)
        df_bus[f"dA_{label}"] = np.round(
            np.abs(net.res_bus.va_degree.values - Va_ref), 4
        )
    df_bus["V_AC"] = np.round(Vm_ref, 4)
    df_bus["Ang_AC"] = np.round(Va_ref, 4)

    # OK counts
    v_ok = (df_bus.filter(like="dV_") <= 0.01).sum()
    a_ok = (df_bus.filter(like="dA_") <= 0.5).sum()
    total = {col: "" for col in df_bus.columns}
    for col in v_ok.index:
        total[col] = f"{v_ok[col]}/{len(df_bus)}"
    for col in a_ok.index:
        total[col] = f"{a_ok[col]}/{len(df_bus)}"
    df_bus = pd.concat([df_bus, pd.DataFrame(total, index=["Total"])]).reset_index(
        names=["bus"]
    )

    print("=== Bus Voltage & Angle Errors vs pp‑AC ===")
    print(tabulate(df_bus, headers="keys", tablefmt="psql", showindex=False))

    # 3. PV‑generator Q comparison ------------------------------------
    if not net_lin.res_gen.empty and not net_ac.res_gen.empty:
        df_Q = pd.DataFrame(
            {
                "Q_LACPF": net_lin.res_gen.q_mvar.values.round(2),
                "Q_NR": (
                    net_nr.res_gen.q_mvar.values.round(2)
                    if not net_nr.res_gen.empty
                    else 0.0
                ),
                "Q_AC": net_ac.res_gen.q_mvar.values.round(2),
            }
        )
        df_Q["dQ_LACPF"] = np.abs(df_Q.Q_LACPF - df_Q.Q_AC).round(2)
        df_Q["dQ_NR"] = np.abs(df_Q.Q_NR - df_Q.Q_AC).round(2)
        print("=== PV Generator Reactive Power (MW) ===")
        print(
            tabulate(
                df_Q.reset_index(names=["gen_id"]),
                headers="keys",
                tablefmt="psql",
                showindex=False,
            )
        )

    # 4. System power balance -----------------------------------------
    print("=== System Power Balance (ΔP / ΔQ) ===")
    for label, net in [
        ("LACPF", net_lin),
        ("NR", net_nr),
        ("pp‑AC", net_ac),
        ("DC", net_dc),
    ]:
        dP, dQ = _pq_balance(net)
        tagP = "OK" if abs(dP) <= tol else f"⚠ {dP:.1f}"
        tagQ = "OK" if abs(dQ) <= tol else f"⚠ {dQ:.1f}"
        print(f"{label:6s}  ΔP = {dP:9.2f} MW [{tagP}]   ΔQ = {dQ:9.2f} MVar [{tagQ}]")

    print("✅ Regime evaluation complete.")


# ---------------------------------------------------------------------------
# Stand‑alone test helper
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from LACPF.core.read_data import read_data
    from LACPF.core.perturbation import build_full_perturbation_template
    from LACPF.models.calculate_regime import calculate_regime

    case = "case4gs"
    net_base = read_data(case)

    perturb = build_full_perturbation_template(net_base, proc=20)  # 20 % load change

    result = calculate_regime(net_base, perturb)
    evaluate_regimes(result)

    print("TEST regime_evaluation.py PASSED SUCCESSFULLY")
