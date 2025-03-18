import pandas as pd

import pandapower as pp
import copy

from LACPF.core.read_data import read_data


def create_perturbation(net, perturbation):

    net_perturbed = copy.deepcopy(net)

    # df_perturbation = pd.DataFrame(columns=["P_pu", "Q_pu"])

    df_perturbation = pd.DataFrame({
        "bus": perturbation["bus"],
        "P_pu": -perturbation["P_load_pu"] * perturbation["delta_load_percent"] / 100,
        "Q_pu": -perturbation["Q_load_pu"] * perturbation["delta_load_percent"] / 100
    }).reset_index(drop=True)

    for bus in net.bus.index:
        delta_P = -df_perturbation.loc[bus, "P_pu"] * net.sn_mva  # возмущение в MW
        delta_Q = -df_perturbation.loc[bus, "Q_pu"] * net.sn_mva  # возмущение в Mvar
        load_idx = net_perturbed.load[net_perturbed.load.bus == bus].index
        if not load_idx.empty:
            net_perturbed.load.loc[load_idx, "p_mw"] += delta_P
            net_perturbed.load.loc[load_idx, "q_mvar"] += delta_Q

    return net_perturbed, df_perturbation


def build_full_perturbation_template(net):
    buses = net.bus.index
    sn_mva = net.sn_mva  # базовая мощность сети для перевода в p.u.

    # Готовим списки
    p_load_pu = []
    q_load_pu = []
    p_gen_pu = []
    delta_load_percent = []

    for bus in buses:
        # Собираем нагрузку по узлу
        p_load_mw = (
            net.load.loc[net.load["bus"] == bus, "p_mw"].sum()
            if not net.load.empty
            else 0
        )
        q_load_mvar = (
            net.load.loc[net.load["bus"] == bus, "q_mvar"].sum()
            if not net.load.empty
            else 0
        )

        # Собираем генерацию по узлу
        p_gen_mw = (
            net.gen.loc[net.gen["bus"] == bus, "p_mw"].sum() if not net.gen.empty else 0
        )

        # В p.u.
        p_load_pu.append(p_load_mw / sn_mva)
        q_load_pu.append(q_load_mvar / sn_mva)
        p_gen_pu.append(p_gen_mw / sn_mva)

        # Если нагрузки нет - возмущение запрещаем (0%)
        if p_load_mw == 0 and q_load_mvar == 0:
            delta_load_percent.append(0)
        else:
            delta_load_percent.append(
                50
            )  # Здесь можно задать базу, дальше менять выборочно

    perturbation = pd.DataFrame(
        {
            "bus": buses,
            "P_load_pu": p_load_pu,
            "Q_load_pu": q_load_pu,
            "P_gen_pu": p_gen_pu,
            "delta_load_percent": delta_load_percent,
        }
    )

    return perturbation


if __name__ == "__main__":
    case = "case4gs"

    net = read_data(case)
    pp.rundcpp(net)

    print("\nNet data:")
    print(net.bus)
    print(net.load)
    print(net.gen)

    perturbation = build_full_perturbation_template(net)
    print("\nPerturbation template:\n", perturbation)

    net_mod, df_perturbation = create_perturbation(net, perturbation)

    print("\nNet data after perturbation:")
    print(net_mod.load)

    print("\nPerturbation data:")
    print(df_perturbation)

    print("\n\tTEST PERTURBATION.PY PASSED SUCCESSFULLY!!!\n")
