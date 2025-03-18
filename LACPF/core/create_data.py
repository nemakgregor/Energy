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

    J = np.block([[H_LL, H_LG, M_LL], [H_GL, H_GG, M_GL], [N_LL, N_LG, K_LL]])
    rows, cols = J.shape

    rank_J = np.linalg.matrix_rank(J)
    print(f"\nРанг матрицы Якоби: {rank_J}, размерность J: {rows}x{cols}")

    for name, matrix in zip(matrix_names, matrices):
        if np.isnan(matrix).any():
            print(f"\nERROR:\tMatrix {name} contains NaN values")

    if rows == cols:
        print("\nМатрица квадратная — проверяем детерминант и спектр:")
        det_J = np.linalg.det(J)
        print(f"Детерминант J: {det_J:.4e}")

        eigenvalues = np.linalg.eigvals(J)
        print(f"Собственные значения J:\n{eigenvalues}")

        if np.isclose(det_J, 0):
            print(
                "Матрица вырождена (det = 0), решение либо не существует, либо их бесконечно много."
            )
        else:
            print(
                "Матрица невырождена (det ≠ 0), система имеет единственное решение при любом b."
            )
    else:
        print("\nМатрица прямоугольная — проверяем разрешимость по рангу:")

    if rank_J == rows:
        print("Система совместна при любом b (ранг равен числу уравнений).")
    else:
        print("Система НЕ совместна при любом b. Проверяем конкретный вектор b:")

        # Тестовая правая часть (замени на свой b при необходимости)
        b = np.random.randn(rows)
        Ab = np.hstack([J, b.reshape(-1, 1)])
        rank_Ab = np.linalg.matrix_rank(Ab)

        print(f"Ранг расширенной матрицы [J|b]: {rank_Ab}")
        if rank_Ab == rank_J:
            print("Конкретная система Jx = b совместна.")
        else:
            print("Конкретная система Jx = b несовместна.")

    # Дополнительно — проверка положительной определённости (если J симметричная):
    if rows == cols and np.allclose(J, J.T):
        try:
            np.linalg.cholesky(J)
            print("Матрица J положительно определена.")
        except np.linalg.LinAlgError:
            print("Матрица J не положительно определена.")

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


if __name__ == "__main__":
    case = "case4gs"

    net = read_data(case)
    pp.rundcpp(net)

    N_L, N_G, N_buses, H_LL, H_LG, M_LL, H_GL, H_GG, M_GL, N_LL, N_LG, K_LL = create_J(
        net
    )

    print("\n\tTEST CREATE_DATA_FOR_OPT.PY SUCCESSFULLY!\n")
