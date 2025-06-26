import numpy as np
import pandas as pd
import pandapower as pp
from math import radians, degrees
from typing import Optional

from LACPF.core.create_data import create_J


def solve(
    df_input: pd.DataFrame,
    net: pp.pandapowerNet,
    H_LL: np.ndarray,
    H_LG: np.ndarray,
    M_LL: np.ndarray,
    H_GL: np.ndarray,
    H_GG: np.ndarray,
    M_GL: np.ndarray,
    N_LL: np.ndarray,
    N_LG: np.ndarray,
    K_LL: np.ndarray,
    G: Optional[np.ndarray] = None,
    B: Optional[np.ndarray] = None,
):
    """Linearised AC power‑flow solver that also fills slack / gen PQ tables.

    Parameters
    ----------
    df_input : DataFrame with columns ``P_pu`` and ``Q_pu`` (load perturbations)
    net      : pandapower network already containing base‑case voltages/angles
    H_*, M_*, N_* : Jacobian sub‑blocks pre‑computed by *create_J*
    G, B     : (optional) real & imag parts of Y‑bus in p.u.; if *None* we
                call ``create_J`` internally to obtain them.

    Returns
    -------
    delta_L_values, delta_G_values, U_L_values  (same as before)

    Side‑effects
    ------------
    Populates ``net.res_ext_grid`` and ``net.res_gen.q_mvar`` with slack‑bus
    and PV‑generator injections for the linearised solution.
    """

    # ------------------------------------------------------------------ bus sets
    slack_bus = int(net.ext_grid.bus.values[0])
    pv_buses = list(net.gen.bus.values)
    pv_buses = [b for b in pv_buses if b != slack_bus]
    pq_buses = [b for b in net.bus.index if b not in [slack_bus] + pv_buses]

    # ------------------------------------------------------------------ build linear system A·x = b
    delta_P_L = df_input.loc[pq_buses, "P_pu"].values
    delta_P_G = df_input.loc[pv_buses, "P_pu"].values
    delta_Q_L = df_input.loc[pq_buses, "Q_pu"].values

    A = np.block([[H_LL, H_LG, M_LL], [H_GL, H_GG, M_GL], [N_LL, N_LG, K_LL]])
    b = np.concatenate([delta_P_L, delta_P_G, delta_Q_L])

    x = np.linalg.solve(A, b)  # Δδ_L | Δδ_G | ΔV_L

    # ------------------------------------------------------------------ unpack solution
    N_L = len(delta_P_L)
    N_G = len(delta_P_G)

    delta_L_values = x[:N_L]
    delta_G_values = x[N_L : N_L + N_G]
    U_L_values = x[N_L + N_G :]

    # ------------------------------------------------------------------ obtain admittance if not supplied
    if G is None or B is None:
        _, _, _, _, _, _, _, _, _, _, _, _, G, B = create_J(net)

    nb = len(net.bus)
    V = net.res_bus.vm_pu.values.copy()
    theta = np.deg2rad(net.res_bus.va_degree.values.copy())

    # apply increments to PQ & PV buses
    for idx, bus in enumerate(pq_buses):
        theta[bus] += delta_L_values[idx]
        V[bus] += U_L_values[idx]
    for idx, bus in enumerate(pv_buses):
        theta[bus] += delta_G_values[idx]
        # PV magnitudes unchanged (generator voltage set‑point)

    # ------------------------------------------------------------------ compute P,Q injections with updated V,θ
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

    # ------------------------------------------------------------------ update result tables
    # 1. res_bus voltages / angles
    net.res_bus["vm_pu"] = V
    net.res_bus["va_degree"] = np.rad2deg(theta)

    # 2. Slack bus P,Q (MW / MVar)
    if net.res_ext_grid.empty:
        net.res_ext_grid = pd.DataFrame(
            index=net.ext_grid.index, columns=["p_mw", "q_mvar"]
        )
    net.res_ext_grid.loc[:, "p_mw"] = P_calc[slack_bus] * sn
    net.res_ext_grid.loc[:, "q_mvar"] = Q_calc[slack_bus] * sn

    # 3. Generator reactive power on PV buses
    if not net.gen.empty:
        if net.res_gen.empty:
            net.res_gen = pd.DataFrame(index=net.gen.index, columns=["p_mw", "q_mvar"])
        for g_idx, gen_row in net.gen.iterrows():
            bus = int(gen_row.bus)
            if bus in pv_buses:
                q_load = (
                    net.load.loc[net.load.bus == bus, "q_mvar"].sum()
                    if not net.load.empty
                    else 0.0
                )
                net.res_gen.at[g_idx, "p_mw"] = gen_row.p_mw  # unchanged active
                net.res_gen.at[g_idx, "q_mvar"] = (Q_calc[bus] + q_load / sn) * sn

    # 4. Loads – copy specified powers (linear model doesn’t change them)
    if not net.load.empty:
        if net.res_load.empty:
            net.res_load = pd.DataFrame(
                index=net.load.index, columns=["p_mw", "q_mvar"]
            )
        net.res_load["p_mw"] = net.load["p_mw"].values
        net.res_load["q_mvar"] = net.load["q_mvar"].values

    print("\n\tSYSTEM SOLVED SUCCESSFULLY (Linear AC)!!!")
    return delta_L_values, delta_G_values, U_L_values


# -----------------------------------------------------------------------------
# Standalone test
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    case = "case4gs"

    from LACPF.core.read_data import read_data

    net = read_data(case)
    # Create Jacobian + Y‑bus once
    (
        N_L,
        N_G,
        _,
        H_LL,
        H_LG,
        M_LL,
        H_GL,
        H_GG,
        M_GL,
        N_LL,
        N_LG,
        K_LL,
        G,
        B,
    ) = create_J(net)

    # Dummy 20% perturbation of PQ loads
    P_net = -net.res_bus.p_mw.values / net.sn_mva
    Q_net = -net.res_bus.q_mvar.values / net.sn_mva
    df_input = pd.DataFrame(
        {"P_pu": 0.2 * P_net, "Q_pu": 0.2 * Q_net}, index=net.bus.index
    )

    # Solve
    solve(df_input, net, H_LL, H_LG, M_LL, H_GL, H_GG, M_GL, N_LL, N_LG, K_LL, G, B)

    # Show slack & first PV bus results
    print("\nSlack ext_grid after LACPF:\n", net.res_ext_grid)
    if not net.res_gen.empty:
        print("\nGenerator Q (LACPF):\n", net.res_gen[["p_mw", "q_mvar"]])

    print("\n\tTEST SOLVER.PY PASSED SUCCESSFULLY!!!\n")
