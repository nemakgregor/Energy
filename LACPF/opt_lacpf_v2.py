import numpy as np
import pandas as pd

from tabulate import tabulate

import pandapower as pp

from read_data import read_data
from create_data_v3 import create_J

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

    return delta_L_values, delta_G_values, U_L_values


def create_df_input(net):
    """
    Создает DataFrame с величинами возмущений на основе разницы между генерацией и нагрузкой (нетто-инъекция)
    в каждом узле, а затем модифицирует копию сети net_perturbed, изменяя нагрузки:
      - Если нагрузка есть, прибавляет возмущения к существующим значениям.
      - Если нагрузки нет, создаёт новый элемент нагрузки с заданными возмущениями.
    """
    net_perturbed = net.deepcopy()  # Работаем с копией сети

    # Для каждого узла вычисляем нетто-инъекцию (генерация - нагрузка) в p.u.
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

    # Формируем DataFrame возмущений
    df_input = pd.DataFrame(
        {
            "bus": [bus for bus in net.bus.index],
            "P_pu": [0.2 * P_net[bus] for bus in net.bus.index],
            "Q_pu": [0.2 * Q_net[bus] for bus in net.bus.index],
        },
        index=net.bus.index,
    )

    # print("\nPQ updates:\n", df_input)

    # bus_to_perturb = 11  # Задаем номер узла, который хотим возмутить
    # df_input = pd.DataFrame(
    #     {
    #         "P_pu": [0] * len(net.bus.index),
    #         "Q_pu": [0] * len(net.bus.index),
    #     },
    #     index=net.bus.index,
    # )
    # df_input.at[bus_to_perturb, "P_pu"] = 0.05 * P_net[bus_to_perturb]
    # df_input.at[bus_to_perturb, "Q_pu"] = 0.05 * Q_net[bus_to_perturb]

    for bus in net.bus.index:
        delta_P = -df_input.loc[bus, "P_pu"] * net.sn_mva  # возмущение в MW
        delta_Q = -df_input.loc[bus, "Q_pu"] * net.sn_mva  # возмущение в Mvar
        load_idx = net_perturbed.load[net_perturbed.load.bus == bus].index
        if not load_idx.empty:
            net_perturbed.load.loc[load_idx, "p_mw"] += delta_P
            net_perturbed.load.loc[load_idx, "q_mvar"] += delta_Q

    return df_input, net_perturbed

def 


if __name__ == "__main__":
    data_path = "../data matpower/"
    case = "case30"

    net = read_data(data_path, case)

    # pp.runpp(net)

    # print("\n\tAC:")
    # print(net.res_bus)

    slack_buses = (
        net.ext_grid.bus.values
    )  # Slack-узлы (обычно 1 узел, но на всякий случай оставляем массив)
    pv_buses = net.gen.bus.values  # PV-узлы (генераторные, кроме slack)
    pq_buses = np.setdiff1d(
        net.bus.index, np.concatenate((slack_buses, pv_buses))
    )  # Чистые PQ-узлы

    net_mod = net.deepcopy()
    # pp.runpp(net_mod)

    N_L, N_G, N_buses, H_LL, H_LG, M_LL, H_GL, H_GG, M_GL, N_LL, N_LG, K_LL = create_J(
        net_mod
    )

    # print("\nH_LL range:", np.min(H_LL), np.max(H_LL))
    # print("H_LG range:", np.min(H_LG), np.max(H_LG))
    # print("H_GL range:", np.min(H_GL), np.max(H_GL))
    # print("H_GG range:", np.min(H_GG), np.max(H_GG))
    # print("M_LL range:", np.min(M_LL), np.max(M_LL))
    # print("N_LL range:", np.min(N_LL), np.max(N_LL))
    # print("K_LL range:", np.min(K_LL), np.max(K_LL))

    df_input, net_perturbed_ac = create_df_input(net_mod)
    net_perturbed_dc = net_perturbed_ac.deepcopy()

    delta_L_values, delta_G_values, U_L_values = solve(
        df_input,
        net_mod,
        H_LL,
        H_LG,
        M_LL,
        H_GL,
        H_GG,
        M_GL,
        N_LL,
        N_LG,
        K_LL,
    )

    # Check for NaN or None values in the results
    if any(v is None or np.isnan(v) for v in delta_L_values):
        raise ValueError("\n\tNaN or None values found in delta_L_values!!!\n")

    if any(v is None or np.isnan(v) for v in delta_G_values):
        raise ValueError("\n\tNaN or None values found in delta_G_values!!!\n")

    if any(v is None or np.isnan(v) for v in U_L_values):
        raise ValueError("\n\tNaN or None values found in U_L_values!!!\n")

    delta_L_values = [0 if v is None or np.isnan(v) else v for v in delta_L_values]
    delta_G_values = [0 if v is None or np.isnan(v) else v for v in delta_G_values]
    U_L_values = [0 if v is None or np.isnan(v) else v for v in U_L_values]

    # Проверяем соответствие размеров массивов
    if len(pq_buses) != len(delta_L_values):
        raise ValueError(
            f"Mismatch: {len(pq_buses)} PQ buses but {len(delta_L_values)} delta values"
        )

    if len(pv_buses) != len(delta_G_values):
        raise ValueError(
            f"Mismatch: {len(pv_buses)} PV buses but {len(delta_G_values)} delta values"
        )

    # Обновляем углы напряжений
    net_mod.res_bus.loc[pq_buses, "va_degree"] += (
        np.array(delta_L_values) * 57
    )  # Изменяем углы PQ-узлов (нагрузочных)
    net_mod.res_bus.loc[pv_buses, "va_degree"] += (
        np.array(delta_G_values) * 57
    )  # Изменяем углы PV-узлов (генераторных)

    # Обновляем модули напряжений только для PQ-узлов
    net_mod.res_bus.loc[pq_buses, "vm_pu"] += U_L_values

    pp.runpp(net_perturbed_ac)
    pp.rundcpp(net_perturbed_dc)

    df_comparison = pd.DataFrame(
        {
            "V_AC": net_perturbed_ac.res_bus["vm_pu"].values.round(4),
            "V_model": net_mod.res_bus["vm_pu"].values.round(4),
            "V_DC": net_perturbed_dc.res_bus["vm_pu"].values.round(4),
            "ok_V?": np.where(
                np.abs(
                    net_mod.res_bus["vm_pu"].values
                    - net_perturbed_ac.res_bus["vm_pu"].values
                )
                <= np.abs(
                    net_perturbed_dc.res_bus["vm_pu"].values
                    - net_perturbed_ac.res_bus["vm_pu"].values
                ),
                1,
                0,
            ),
            "Ang_AC": net_perturbed_ac.res_bus["va_degree"].values.round(4),
            "Ang_model": net_mod.res_bus["va_degree"].values.round(4),
            "Ang_DC": net_perturbed_dc.res_bus["va_degree"].values.round(4),
            "ok_Ang?": np.where(
                np.abs(
                    net_mod.res_bus["va_degree"].values
                    - net_perturbed_ac.res_bus["va_degree"].values
                )
                <= np.abs(
                    net_perturbed_dc.res_bus["va_degree"].values
                    - net_perturbed_ac.res_bus["va_degree"].values
                ),
                1,
                0,
            ),
        },
        index=net_mod.res_bus.index,  # Убеждаемся, что индексы совпадают
    )

    # Добавляем итоговую строку с общим количеством значений 1 в столбцах ok_V? и ok_Ang?
    total_ok_V = df_comparison["ok_V?"].sum()
    total_ok_Ang = df_comparison["ok_Ang?"].sum()
    total_row = pd.DataFrame(
        {
            "V_AC": [""],
            "V_model": [""],
            "V_DC": [""],
            # "|": [""],
            "ok_V?": [f"{total_ok_V}/{len(df_comparison)}"],
            # "||": [""],
            "Ang_AC": [""],
            "Ang_model": [""],
            "Ang_DC": [""],
            # "|": [""],
            "ok_Ang?": [f"{total_ok_Ang}/{len(df_comparison)}"],
        },
        index=["Total"],
    )
    df_comparison = pd.concat([df_comparison, total_row])

    # Создаём столбец с типом узла: Slack, PV или PQ
    def bus_type(bus_idx):
        if np.isin(bus_idx, slack_buses):
            return "Slack"
        elif np.isin(bus_idx, pv_buses):
            return "PV"
        else:
            return "PQ"

    df_comparison["bus_type"] = df_comparison.index.map(bus_type)
    # df_comparison["in_model"] = df_comparison["bus_type"].isin(["PQ", "PV"])

    print("\n\tCalculations comparison:\n")
    # print(df_comparison)
    print(tabulate(df_comparison, headers="keys", tablefmt="psql"))

    df_res = pd.DataFrame(
        {
            "P": net_perturbed_ac.gen.set_index("bus").p_mw.sub(
                net_perturbed_ac.load.set_index("bus").p_mw, fill_value=0
            ),
            "Q": -net_perturbed_ac.load.set_index("bus").q_mvar,
            "V": net_mod.res_bus.vm_pu,
            "theta": net_mod.res_bus.va_degree,
        }
    ).reset_index()

    # Save df_res to Excel
    df_res.to_excel("df_res.xlsx", index=False)

    print(df_res)

    print("TEST OPT_LACPF.PY SUCCESSFULLY!\n")
