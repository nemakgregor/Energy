import pandapower as pp
import copy

from LACPF.core.read_data import read_data
from LACPF.core.create_data import create_J
from LACPF.core.perturbation import (
    build_full_perturbation_template,
    create_perturbation,
)
from LACPF.core.solver import solve


def calculate_regime(net, perturbation):

    N_L, N_G, N_buses, H_LL, H_LG, M_LL, H_GL, H_GG, M_GL, N_LL, N_LG, K_LL = create_J(
        net
    )
    net_mod, df_perturbation = create_perturbation(net, perturbation)

    delta_L_values, delta_G_values, U_L_values = solve(
        df_perturbation, net, H_LL, H_LG, M_LL, H_GL, H_GG, M_GL, N_LL, N_LG, K_LL
    )

   # Клонируем сеть для AC и DC расчётов
    net_ac = copy.deepcopy(net_mod)
    net_dc = copy.deepcopy(net_mod)

    # Считаем AC Power Flow
    try:
        pp.runpp(net_ac)
        print("\nAC Power Flow solved successfully")
    except Exception as e:
        print(f"\n\tAC Power Flow failed: {e}")

    # Считаем DC Power Flow
    try:
        pp.rundcpp(net_dc)
        print("DC Power Flow solved successfully")
    except Exception as e:
        print(f"\tDC Power Flow failed: {e}")

    print("\n\tREGIME CALCULATED SUCCESSFULLY!!!")
    return {
        "delta_L": delta_L_values,
        "delta_G": delta_G_values,
        "U_L": U_L_values,
        "net_ac": net_ac,
        "net_dc": net_dc,
        "net_lacpf": net_mod,
    }


if __name__ == "__main__":

    case = "case4gs"

    net = read_data(case)
    pp.rundcpp(net)

    perturbation = build_full_perturbation_template(net, proc=50)

    result = calculate_regime(net, perturbation)

    print("\n\tTEST CALCULATE_REGIME.PY PASSED SUCCESSFULLY!!!\n")
