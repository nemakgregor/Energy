from pandapower.converter import from_mpc
import pandapower as pp
import math
import numpy as np


def read_data(data_path, case):
    net = from_mpc(
        data_path + case + ".m", casename_mpc=case, validate_conversion=False
    )

    print("\n", data_path, case, "\nREAD DATA SUCCESSFULLY!\n")

    frequency = 50
    omega = 2 * math.pi * frequency

    if not net.line.empty:
        for idx, line in net.line.iterrows():
            from_bus = line["from_bus"]
            to_bus = line["to_bus"]

            # Определяем базовое напряжение для линии (используем напряжение from_bus)
            V_base = net.bus.loc[from_bus, "vn_kv"]
            S_base = net.sn_mva
            Z_base = V_base**2 / S_base
            I_base = S_base / (V_base * (3**0.5))

            # Рассчитываем параметры в per unit
            r_pu = line["r_ohm_per_km"] / Z_base
            x_pu = line["x_ohm_per_km"] / Z_base

            C = line["c_nf_per_km"] * line["length_km"] / 1e9
            b = omega * C
            b_pu = b * Z_base
            p_pu = line["max_i_ka"] / I_base

            # Записываем результаты в таблицу Pandapower
            net.line.loc[idx, "r_pu"] = r_pu
            net.line.loc[idx, "x_pu"] = x_pu
            net.line.loc[idx, "b_pu"] = b_pu
            net.line.loc[idx, "p_pu"] = p_pu

            # print(
            #     f"Branch {idx}: r_pu = {r_pu:.2f}, x_pu = {x_pu:.2f}, b_pu = {b_pu:.2f}, p_pu = {p_pu:.2f}"
            # )

    net.gen["max_p_pu"] = net.gen["max_p_mw"] / net.sn_mva
    net.load["p_pu"] = net.load["p_mw"] / net.sn_mva

    pp.rundcpp(net)

    if net.converged:
        print("DC Power flow converged successfully.\n")
    else:
        print("DC Power flow did NOT converge.\n")

    return net


if __name__ == "__main__":
    data_path = "../data matpower/"
    case = "case30"

    net = read_data(data_path, case)

    print("\nTEST READ_DATA.PY SUCCESSFULLY!\n")
