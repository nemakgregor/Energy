import numpy as np
import pandas as pd

import pandapower as pp

from LACPF.core.read_data import read_data
from LACPF.core.create_data import create_J


def solve(
    df_input,
    net,
    H_LL,
    H_LG,
    M_LL,
    H_GL,
    H_GG,
    M_GL,
    N_LL,
    N_LG,
    K_LL,
):
    slack_bus = net.ext_grid.bus.values[0]  # Slack узел
    pv_buses = net.gen.bus.values  # PV-узлы (генераторные)
    pq_buses = np.setdiff1d(
        net.bus.index, np.concatenate(([slack_bus], pv_buses))
    )  # Все остальные — PQ

    delta_P_L = df_input.loc[pq_buses, "P_pu"].values
    delta_P_G = df_input.loc[pv_buses, "P_pu"].values
    delta_Q_L = df_input.loc[pq_buses, "Q_pu"].values

    # Формируем матрицу A
    A = np.block([[H_LL, H_LG, M_LL], [H_GL, H_GG, M_GL], [N_LL, N_LG, K_LL]])

    # Формируем вектор b
    b = np.concatenate([delta_P_L, delta_P_G, delta_Q_L])

    # Решаем систему линейных уравнений
    x = np.linalg.solve(A, b)

    # Разбиваем результаты
    N_L = len(delta_P_L)
    N_G = len(delta_P_G)

    delta_L_values = x[:N_L]
    delta_G_values = x[N_L : N_L + N_G]
    U_L_values = x[N_L + N_G :]

    print("\n\tSYSTEM SOLVED SUCCESSFULLY!!!")
    return delta_L_values, delta_G_values, U_L_values


if __name__ == "__main__":
    case = "case4gs"

    net = read_data(case)
    pp.rundcpp(net)

    N_L, N_G, N_buses, H_LL, H_LG, M_LL, H_GL, H_GG, M_GL, N_LL, N_LG, K_LL = create_J(
        net
    )

    P_net = {}
    Q_net = {}
    for bus in net.bus.index:
        # Нагрузка
        load_bus = net.load[net.load.bus == bus]
        p_load = load_bus["p_mw"].sum() if not load_bus.empty else 0.0
        q_load = load_bus["q_mvar"].sum() if not load_bus.empty else 0.0

        # Нетто-инъекция (в p.u.)
        if bus != net.ext_grid.bus.values[0]:
            P_net[bus] = (-p_load) / net.sn_mva
            Q_net[bus] = (-q_load) / net.sn_mva
        else:
            P_net[bus] = 0.0
            Q_net[bus] = 0.0

    df_input = pd.DataFrame(
        {
            "bus": [bus for bus in net.bus.index],
            "P_pu": [0.2 * P_net[bus] for bus in net.bus.index],
            "Q_pu": [0.2 * Q_net[bus] for bus in net.bus.index],
        },
        index=net.bus.index,
    )

    print("\nData:\n")
    print(net.load)
    print(net.gen)
    print(net.ext_grid)

    print("\nPQ updates:\n", df_input)

    delta_L_values, delta_G_values, U_L_values = solve(
        df_input, net, H_LL, H_LG, M_LL, H_GL, H_GG, M_GL, N_LL, N_LG, K_LL
    )

    print("\ndelta_L_values: ", delta_L_values)
    print("delta_G_values: ", delta_G_values)
    print("U_L_values: ", U_L_values)

    print("\n\tTEST SOLVER.PY PASSED SUCCESSFULLY!!!\n")
