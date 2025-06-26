import pandapower as pp
import copy

from LACPF.core.create_data import create_J
from LACPF.core.perturbation import (
    build_full_perturbation_template,
    create_perturbation,
)
from LACPF.core.solver import solve
from LACPF.core.NRM import run_newton_pf


def calculate_regime(net, perturbation):

    N_L, N_G, N_buses, H_LL, H_LG, M_LL, H_GL, H_GG, M_GL, N_LL, N_LG, K_LL, G, B = (
        create_J(net)
    )
    net_mod, df_perturbation = create_perturbation(net, perturbation)

    try:
        delta_L_values, delta_G_values, U_L_values = solve(
            df_perturbation, net, H_LL, H_LG, M_LL, H_GL, H_GG, M_GL, N_LL, N_LG, K_LL
        )
        print("\nLACPF solved successfully")
    except Exception as e:
        print(f"\n\tLACPF failed: {e}")

    # Клонируем сеть для AC и DC расчётов
    net_ac = copy.deepcopy(net_mod)
    net_dc = copy.deepcopy(net_mod)
    net_nr = copy.deepcopy(net_mod)

    try:
        run_newton_pf(net_nr)
        print("NR AC solved successfully")
    except Exception as e:
        print(f"\tNR AC Power Flow failed: {e}")

    # Считаем AC Power Flow
    try:
        pp.runpp(net_ac)
        print("AC PF solved successfully")
    except Exception as e:
        print(f"\tAC Power Flow failed: {e}")

    # Считаем DC Power Flow
    try:
        pp.rundcpp(net_dc)
        print("DC PF solved successfully")
    except Exception as e:
        print(f"\tDC Power Flow failed: {e}")

    # Update net_mod.res_load with net_mod.load values for p_mw and q_mvar
    net_mod.res_load["p_mw"] = net_mod.load["p_mw"]
    net_mod.res_load["q_mvar"] = net_mod.load["q_mvar"]
    net_mod.res_ext_grid["p_mw"] = 0
    net_mod.res_ext_grid["q_mvar"] = 0

    print("\n\tREGIME CALCULATED SUCCESSFULLY!!!")
    return {
        "delta_L": delta_L_values,
        "delta_G": delta_G_values,
        "U_L": U_L_values,
        "net_nr": net_nr,
        "net_ac": net_ac,
        "net_dc": net_dc,
        "net_lacpf": net_mod,
        "G": G,
        "B": B,
    }


if __name__ == "__main__":
    from LACPF.core.read_data import read_data

    case = "case4gs"

    net_base = read_data(case)
    pp.rundcpp(net_base)

    perturbation = build_full_perturbation_template(net_base, proc=50)

    result = calculate_regime(net_base, perturbation)

    print("\n\tTEST CALCULATE_REGIME.PY PASSED SUCCESSFULLY!!!\n")
