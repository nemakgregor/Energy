from pandapower.converter import from_mpc
import pandapower as pp
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import norm

from read_data import read_data


def create_J(net):

    slack_bus = net.ext_grid.bus.values[0]  # Slack bus
    pv_buses = np.unique(net.gen.bus.values)  # PV buses (gen)
    pq_buses = np.setdiff1d(
        net.bus.index, np.concatenate(([slack_bus], pv_buses))
    )  # PQ buses (load)

    N_buses = len(net.bus)  # Total number of buses
    N_L = len(pq_buses)  # Number of PQ buses (load)
    N_G = len(pv_buses)  # Number of PV buses (gen)

    # Extract voltage, angle, power
    V = net.res_bus.vm_pu.values  # Voltage magnitude
    delta = net.res_bus.va_degree.values * 0.017  # Voltage angle in radians
    P = -net.res_bus.p_mw.values / net.sn_mva  # Active power
    Q = -net.res_bus.q_mvar.values / net.sn_mva  # Reactive power

    bus_lookup = {bus: idx for idx, bus in enumerate(net.bus.index)}

    G = np.zeros((N_buses, N_buses))
    B = np.zeros((N_buses, N_buses))

    for _, line in net.line.iterrows():
        from_bus = bus_lookup[line["from_bus"]]
        to_bus = bus_lookup[line["to_bus"]]

        R = line.r_pu
        X = line.x_pu
        Y = 1 / (R + 1j * X)
        Gij = Y.real
        Bij = Y.imag

        # Диагональные элементы
        G[from_bus, from_bus] += Gij
        G[to_bus, to_bus] += Gij
        B[from_bus, from_bus] += Bij
        B[to_bus, to_bus] += Bij

        # Вне-диагональные элементы
        G[from_bus, to_bus] -= Gij
        G[to_bus, from_bus] -= Gij
        B[from_bus, to_bus] -= Bij
        B[to_bus, from_bus] -= Bij

    print("\nПроверка симметричности G:", np.allclose(G, G.T))
    print("Проверка симметричности B:", np.allclose(B, B.T))

    # PQ-узлы идут первыми
    ordered_nodes = list(pq_buses) + list(pv_buses)

    # Отдельный lookup для PQ-узлов (для V-части Якобиана)
    pq_lookup = {bus: idx for idx, bus in enumerate(pq_buses)}

    # Исправленный код для расчета H, N, M, K

    H = np.zeros((N_L + N_G, N_L + N_G))
    for row_idx, bus_i in enumerate(ordered_nodes):
        real_i = bus_lookup[bus_i]

        for col_idx, bus_j in enumerate(ordered_nodes):
            real_j = bus_lookup[bus_j]

            if bus_i != bus_j:
                H[row_idx, col_idx] = (
                    V[real_i]
                    * V[real_j]
                    * (
                        G[real_i, real_j] * np.sin(delta[real_i] - delta[real_j])
                        - B[real_i, real_j] * np.cos(delta[real_i] - delta[real_j])
                    )
                )
            else:
                # H[row_idx, col_idx] = sum(
                #     V[real_i]
                #     * V[real_j]
                #     * (
                #         B[real_i, real_j] * np.cos(delta[real_i] - delta[real_j])
                #         + G[real_i, real_j] * np.sin(delta[real_i] - delta[real_j])
                #     )
                #     for real_j in range(len(ordered_nodes))
                #     if real_j != real_i
                # )

                H[row_idx, col_idx] = -(V[real_i] ** 2) * B[real_i, real_i]

    M = np.zeros((N_L + N_G, N_L))
    for row_idx, bus_i in enumerate(ordered_nodes):
        real_i = bus_lookup[bus_i]

        for col_idx, bus_j in enumerate(pq_buses):
            real_j = bus_lookup[bus_j]

            if bus_i != bus_j:
                M[row_idx, col_idx] = (
                    V[real_i]
                    * V[real_j]
                    * (
                        G[real_i, real_j] * np.cos(delta[real_i] - delta[real_j])
                        + B[real_i, real_j] * np.sin(delta[real_i] - delta[real_j])
                    )
                )
            else:
                # M[row_idx, col_idx] = (
                #     sum(
                #         V[real_i]
                #         * V[real_j]
                #         * (
                #             G[real_i, real_j] * np.cos(delta[real_i] - delta[real_j])
                #             + B[real_i, real_j] * np.sin(delta[real_i] - delta[real_j])
                #         )
                #         for real_j in range(len(ordered_nodes))
                #         if real_j != real_i
                #     )
                #     + 2 * V[real_i] ** 2 * G[real_i, real_i]
                # )
                M[row_idx, col_idx] = (
                    P[real_i] / V[real_i] + V[real_i] * G[real_i, real_i]
                )

    N_mat = np.zeros((N_L, N_L + N_G))
    for row_idx, bus_i in enumerate(pq_buses):
        real_i = bus_lookup[bus_i]

        for col_idx, bus_j in enumerate(ordered_nodes):
            real_j = bus_lookup[bus_j]

            if bus_i != bus_j:
                N_mat[row_idx, col_idx] = (
                    -V[real_i]
                    * V[real_j]
                    * (
                        G[real_i, real_j] * np.cos(delta[real_i] - delta[real_j])
                        + B[real_i, real_j] * np.sin(delta[real_i] - delta[real_j])
                    )
                )
            else:
                # N_mat[row_idx, col_idx] = sum(
                #     V[real_i]
                #     * V[real_j]
                #     * (
                #         G[real_i, real_j] * np.cos(delta[real_i] - delta[real_j])
                #         + B[real_i, real_j] * np.sin(delta[real_i] - delta[real_j])
                #     )
                #     for real_j in range(len(ordered_nodes))
                #     if real_j != real_i
                # )

                N_mat[row_idx, col_idx] = (
                    -P[real_i] - (V[real_i] ** 2) * G[real_i, real_i]
                )

    K = np.zeros((N_L, N_L))
    for row_idx, bus_i in enumerate(pq_buses):
        real_i = bus_lookup[bus_i]

        for col_idx, bus_j in enumerate(pq_buses):
            real_j = bus_lookup[bus_j]

            if bus_i != bus_j:
                K[row_idx, col_idx] = (
                    V[real_i]
                    * V[real_j]
                    * (
                        G[real_i, real_j] * np.sin(delta[real_i] - delta[real_j])
                        - B[real_i, real_j] * np.cos(delta[real_i] - delta[real_j])
                    )
                )
            else:
                # K[row_idx, col_idx] = (
                #     sum(
                #         V[real_i]
                #         * V[real_j]
                #         * (
                #             G[real_i, real_j] * np.sin(delta[real_i] - delta[real_j])
                #             - B[real_i, real_j] * np.cos(delta[real_i] - delta[real_j])
                #         )
                #         for real_j in range(len(ordered_nodes))
                #         if real_j != real_i
                #     )
                #     - 2 * V[real_i] ** 2 * B[real_i, real_i]
                # )
                K[row_idx, col_idx] = -V[real_i] * B[real_i, real_i]

    # Разбиваем матрицы на блочные подматрицы в соответствии с количеством PQ и PV узлов.
    H_LL = H[:N_L, :N_L]  # влияние углов в PQ-узлах на PQ-узлы
    H_LG = H[:N_L, N_L:]  # влияние углов в PQ-узлах на PV-узлы
    H_GL = H[N_L:, :N_L]  # влияние углов в PV-узлах на PQ-узлы
    H_GG = H[N_L:, N_L:]  # влияние углов в PV-узлах на PV-узлы

    M_LL = M[:N_L, :N_L]  # влияние напряжений в PQ-узлах на PQ-узлы
    M_GL = M[N_L:, :N_L]  # влияние напряжений в PQ-узлах на PV-узлы

    N_LL = N_mat[:N_L, :N_L]  # аналогично для реактивной мощности
    N_LG = N_mat[:N_L, N_L:]
    K_LL = K[:N_L, :N_L]

    J = np.block([[H_LL, H_LG, M_LL], [H_GL, H_GG, M_GL], [N_LL, N_LG, K_LL]])

    rank = np.linalg.matrix_rank(J)
    print(f"\nРанг матрицы Якоби: {rank}, размерность J: {J.shape}")

    # Проверка матриц на наличие NaN
    matrices = [H_LL, H_LG, M_LL, H_GL, H_GG, M_GL, N_LL, N_LG, K_LL]
    matrix_names = [
        "H_LL",
        "H_LG",
        "M_LL",
        "H_GL",
        "H_GG",
        "M_GL",
        "N_LL",
        "N_LG",
        "K_LL",
    ]
    for name, matrix in zip(matrix_names, matrices):
        if np.isnan(matrix).any():
            print(f"\nERROR:\tMatrix {name} contains NaN values")

    print("\n\tJ CREATED SUCCESSFULLY!")

    return (
        N_L,
        N_G,
        N_buses,
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


def generate_load_profiles(net, peak_factor=0.3, noise_level=0.05, seed=42):
    """
    Генерирует почасовой профиль нагрузки (P и Q) для КАЖДОГО load в сети,
    обеспечивая реалистичный вид: утренний и вечерний пики, ночной минимум, цикличность.

    :param net: pandapower сеть с данными о нагрузках
    :param peak_factor: степень изменения нагрузки в пиках (0.3 = ±30% от среднего)
    :param noise_level: уровень случайных вариаций нагрузки
    :param seed: фиксированное значение для повторяемости генерации
    :return: DataFrame с профилем нагрузки для каждого load
    """
    np.random.seed(seed)  # Фиксируем seed для повторяемости
    num_hours = 24
    profiles = []

    # Создаем форму суточного профиля: утренний и вечерний пики
    hours = np.arange(num_hours)
    morning_peak = norm.pdf(hours, loc=8, scale=2.5)  # Утренний пик
    evening_peak = norm.pdf(hours, loc=19, scale=3)  # Вечерний пик
    night_min = 0.2  # Минимальное ночное потребление
    daily_variation = night_min + peak_factor * (morning_peak + evening_peak)
    daily_variation /= daily_variation.max()  # Нормируем

    for load_id, load in net.load.iterrows():
        bus = load["bus"]  # ID узла
        P_base = load["p_mw"]  # Базовая активная мощность
        Q_base = load["q_mvar"]  # Базовая реактивная мощность

        # Пропускаем узлы с нулевой нагрузкой
        if P_base <= 0 and Q_base <= 0:
            continue

        # Генерируем профиль P и Q
        noise = np.random.uniform(-noise_level, noise_level, num_hours)
        P_profile = P_base * daily_variation * (1 + noise)
        Q_profile = Q_base * daily_variation * (1 + noise)

        # Гарантируем цикличность: P(0) = P(23), Q(0) = Q(23)
        P_profile[-1] = P_profile[0]
        Q_profile[-1] = Q_profile[0]

        # Заполняем DataFrame
        for hour in range(num_hours):
            profiles.append(
                {
                    "load_id": load_id,  # ID нагрузки
                    "bus_id": bus,  # ID узла
                    "base_P": P_base / net.sn_mva,
                    "base_Q": Q_base / net.sn_mva,
                    "hour": hour,
                    "P_pu": P_profile[hour] / net.sn_mva,  # Приводим к pu
                    "Q_pu": Q_profile[hour] / net.sn_mva,
                }
            )

    profiles = pd.DataFrame(profiles)

    profiles["delta_P_L"] = profiles["P_pu"] - profiles["base_P"]
    profiles["delta_Q_L"] = profiles["Q_pu"] - profiles["base_Q"]

    print("\n\tLOAD PROFILES GENERATED SUCCESSFULLY!")
    return profiles


if __name__ == "__main__":
    data_path = "../data matpower/"
    case = "case4gs"

    net = read_data(data_path, case)
    pp.rundcpp(net)

    N_L, N_G, N_buses, H_LL, H_LG, M_LL, H_GL, H_GG, M_GL, N_LL, N_LG, K_LL = create_J(
        net
    )

    load_profiles = generate_load_profiles(net)

    # Convert the profiles list to a DataFrame for easier plotting
    profiles_df = pd.DataFrame(load_profiles)

    # Plot the load profiles
    plt.figure(figsize=(12, 6))
    bus_colors = {}  # Dictionary to store colors for each bus
    color_cycle = plt.cm.tab20.colors  # Use a colormap with enough distinct colors
    color_index = 0

    for bus_id in profiles_df["bus_id"].unique():
        if bus_id not in bus_colors:
            bus_colors[bus_id] = color_cycle[color_index % len(color_cycle)]
            color_index += 1

    for load_id in profiles_df["load_id"].unique():
        load_profile = profiles_df[profiles_df["load_id"] == load_id]
        bus_id = load_profile["bus_id"].iloc[0]
        color = bus_colors[bus_id]

        plt.plot(
            load_profile["hour"],
            load_profile["P_pu"],
            label=f"P {load_id}",
            linestyle="-",
            color=color,
        )
        plt.plot(
            load_profile["hour"],
            load_profile["base_P"],
            label=f"base P {load_id}",
            linestyle="--",
            color=color,
        )

    plt.xlabel("Hour")
    plt.ylabel("Load")
    plt.legend()
    plt.grid(True)
    plt.show()

    print("\n\tTEST CREATE_DATA_FOR_OPT.PY SUCCESSFULLY!\n")
