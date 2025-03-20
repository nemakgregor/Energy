import pandapower as pp
import numpy as np

from LACPF.core.read_data import read_data


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

    check_jacobian(J)

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


import numpy as np


def check_jacobian(J, matrix_names=None, matrices=None):
    """
    Performs a detailed analysis of the Jacobian matrix J:
    - Rank check
    - NaN check (if matrix_names and matrices are provided)
    - Condition number
    - SVD singular value analysis
    - Determinant and eigenvalues (if square)
    - Rank-based solvability check
    - Positive definiteness check (if symmetric)
    Prints a final verdict on solvability.
    """
    rows, cols = J.shape
    rank_J = np.linalg.matrix_rank(J)
    print(f"\nJacobian matrix rank: {rank_J}, dimensions: {rows}x{cols}")

    # Check for NaN values in additional matrices
    if matrix_names and matrices:
        for name, matrix in zip(matrix_names, matrices):
            if np.isnan(matrix).any():
                print(f"\nERROR: Matrix {name} contains NaN values")

    # Compute condition number
    cond_J = np.linalg.cond(J)
    print(f"Condition number cond(J): {cond_J:.4e}")
    bad_condition = cond_J > 1e12
    if bad_condition:
        print("WARNING: Matrix is ill-conditioned or nearly singular!")

    # Compute SVD and check the smallest singular value
    u, s, vh = np.linalg.svd(J)
    min_singular = s.min()
    print(f"Minimum singular value: {min_singular:.4e}")
    singular_issue = np.isclose(min_singular, 0)
    if singular_issue:
        print("SVD indicates that the matrix is singular or nearly singular!")

    # Check determinant and eigenvalues if the matrix is square
    if rows == cols:
        print("\nMatrix is square — checking determinant and eigenvalues:")
        det_J = np.linalg.det(J)
        print(f"Determinant of J: {det_J:.4e}")

        eigenvalues = np.linalg.eigvals(J)
        print(f"Eigenvalues of J:\n{eigenvalues}")

        if np.isclose(det_J, 0):
            print(
                "Matrix is singular (det ≈ 0), the system may have no solution or infinitely many solutions."
            )
        else:
            print(
                "Matrix is non-singular (det ≠ 0), the system has a unique solution for any right-hand side b."
            )
    else:
        print("\nMatrix is rectangular — checking solvability by rank:")

    # General solvability check by rank
    solvable = True
    if rank_J == rows:
        print(
            "The system is consistent for any b (rank equals the number of equations)."
        )
    else:
        print(
            "The system is NOT consistent for any b. Testing a random right-hand side b:"
        )
        solvable = False

        # Create a random test vector b and check the rank of the augmented matrix [J | b]
        b = np.random.randn(rows)
        Ab = np.hstack([J, b.reshape(-1, 1)])
        rank_Ab = np.linalg.matrix_rank(Ab)

        print(f"Rank of the augmented matrix [J|b]: {rank_Ab}")
        if rank_Ab == rank_J:
            print("This particular system Jx = b is consistent.")
            solvable = True
        else:
            print("This particular system Jx = b is inconsistent.")
            solvable = False

    # Check positive definiteness if the matrix is symmetric
    if rows == cols and np.allclose(J, J.T):
        try:
            np.linalg.cholesky(J)
            print("Matrix J is positive definite.")
        except np.linalg.LinAlgError:
            print("Matrix J is NOT positive definite.")

    # Final verdict based on all checks
    if bad_condition or singular_issue:
        print("⚠️ WARNING: The matrix is ill-conditioned or numerically singular.")
        solvable = False

    if solvable:
        print("✅ The system can be solved successfully.")
    else:
        print("❌ The system cannot be reliably solved.")

    return solvable  # Optional: return the result as True/False


if __name__ == "__main__":
    case = "case4gs"

    net = read_data(case)
    pp.rundcpp(net)

    N_L, N_G, N_buses, H_LL, H_LG, M_LL, H_GL, H_GG, M_GL, N_LL, N_LG, K_LL = create_J(
        net
    )

    print("\n\tTEST CREATE_DATA_FOR_OPT.PY SUCCESSFULLY!\n")
