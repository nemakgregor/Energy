import pandas as pd
import numpy as np
import pandapower as pp
from tabulate import tabulate


def evaluate_regimes(result):
    net_base = result["net_lacpf"]
    net_ac = result["net_ac"]
    net_dc = result["net_dc"]

    slack_buses = list(
        net_base.ext_grid.bus.values
    )  # Slack-узлы (обычно 1 узел, но на всякий случай оставляем массив)
    pv_buses = list(net_base.gen.bus.values)  # PV-узлы (генераторные, кроме slack)
    pq_buses = np.setdiff1d(
        net_base.bus.index, np.concatenate((slack_buses, pv_buses))
    )  # Чистые PQ-узлы

    delta_L_values = result["delta_L"]
    delta_G_values = result["delta_G"]
    U_L_values = result["U_L"]

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
    net_base.res_bus.loc[pq_buses, "va_degree"] += (
        np.array(delta_L_values) * 57
    )  # Изменяем углы PQ-узлов (нагрузочных)
    net_base.res_bus.loc[pv_buses, "va_degree"] += (
        np.array(delta_G_values) * 57
    )  # Изменяем углы PV-узлов (генераторных)

    # Обновляем модули напряжений только для PQ-узлов
    net_base.res_bus.loc[pq_buses, "vm_pu"] += U_L_values
    print("\nLACPF results applied to the net_base")

    df_comparison = pd.DataFrame(
        {
            "V_AC": net_ac.res_bus["vm_pu"].values.round(4),
            "V_model": net_base.res_bus["vm_pu"].values.round(4),
            "V_DC": net_dc.res_bus["vm_pu"].values.round(4),
            "ok_V?": np.where(
                np.abs(
                    net_base.res_bus["vm_pu"].values - net_ac.res_bus["vm_pu"].values
                )
                <= np.abs(
                    net_dc.res_bus["vm_pu"].values - net_ac.res_bus["vm_pu"].values
                ),
                1,
                0,
            ),
            "Ang_AC": net_ac.res_bus["va_degree"].values.round(4),
            "Ang_model": net_base.res_bus["va_degree"].values.round(4),
            "Ang_DC": net_dc.res_bus["va_degree"].values.round(4),
            "ok_Ang?": np.where(
                np.abs(
                    net_base.res_bus["va_degree"].values
                    - net_ac.res_bus["va_degree"].values
                )
                <= np.abs(
                    net_dc.res_bus["va_degree"].values
                    - net_ac.res_bus["va_degree"].values
                ),
                1,
                0,
            ),
        },
        index=net_base.res_bus.index,  # Убеждаемся, что индексы совпадают
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
        if bus_idx in slack_buses:
            return "Slack"
        elif bus_idx in pv_buses:
            return "PV"
        else:
            return "PQ"

    df_comparison["bus_type"] = df_comparison.index.map(bus_type)
    print("\nCalculations comparison:")
    print(tabulate(df_comparison, headers="keys", tablefmt="psql"))

    voltage_violations = net_base.res_bus.loc[pq_buses, "vm_pu"] < 0.9
    angle_violations = net_base.res_bus.loc[pq_buses, "va_degree"].abs() > 30

    if voltage_violations.any():
        violating_buses = net_base.res_bus.loc[pq_buses[voltage_violations], "vm_pu"]
        print("\t⚠️ WARNING: Voltage below 0.9 pu detected in the following buses:")
        print(violating_buses)
    else:
        print("✅ All LACPF voltages are within the limits")

    if angle_violations.any():
        violating_buses = net_base.res_bus.loc[pq_buses[angle_violations], "va_degree"]
        print("\t⚠️ WARNING: Voltage angle exceeds 30 degrees in the following buses:")
        print(violating_buses)
    else:
        print("✅ All LACPF angles are within the limits")

    def compute_pq(net, name, print_results=False):
        if print_results:
            print("\nname: ", name)
            print("gen (net.res_gen):\n", net.res_gen)

        if not net.res_gen.empty:
            gen = net.res_gen.join(net.gen[["bus"]], how="left")
            gen = gen.groupby("bus")[["p_mw", "q_mvar"]].sum()
        else:
            gen = pd.DataFrame(columns=["p_mw", "q_mvar"])

        gen = gen.reindex(net.bus.index, fill_value=0.0)

        if print_results:
            print("load (net.res_load):\n", net.res_load)

        if not net.res_load.empty:
            load = net.res_load.join(net.load[["bus"]], how="left")
            load = load.groupby("bus")[["p_mw", "q_mvar"]].sum()
        else:
            load = pd.DataFrame(columns=["p_mw", "q_mvar"])

        load = load.reindex(net.bus.index, fill_value=0.0)

        if print_results:
            print("slack (net.res_ext_grid):\n", net.res_ext_grid)

        if not net.res_ext_grid.empty:
            slack_bus = net.ext_grid.bus.values[0]
            slack_p = (
                net.res_ext_grid.p_mw.values[0] if "p_mw" in net.res_ext_grid else 0.0
            )
            slack_q = (
                net.res_ext_grid.q_mvar.values[0]
                if "q_mvar" in net.res_ext_grid
                else 0.0
            )
            slack = pd.DataFrame(0.0, index=net.bus.index, columns=["p_mw", "q_mvar"])
            slack.loc[slack_bus, "p_mw"] = slack_p
            slack.loc[slack_bus, "q_mvar"] = slack_q
        else:
            slack = pd.DataFrame(0.0, index=net.bus.index, columns=["p_mw", "q_mvar"])

        pq = (gen - load + slack).fillna(0.0)

        if print_results:
            print("\nComputed PQ for '{}':\n".format(name))
            print(pq)
        return pq

    pq_lacpf = compute_pq(net_base, "base")
    pq_ac = compute_pq(net_ac, "ac")
    pq_dc = compute_pq(net_dc, "dc")

    df_pq = pd.DataFrame(index=net_base.bus.index)
    df_pq["P_LACPF"] = df_pq.index.map(pq_lacpf["p_mw"].to_dict()).fillna(0).round(4)
    df_pq["Q_LACPF"] = df_pq.index.map(pq_lacpf["q_mvar"].to_dict()).fillna(0).round(4)
    df_pq["P_AC"] = df_pq.index.map(pq_ac["p_mw"].to_dict()).fillna(0).round(4)
    df_pq["Q_AC"] = df_pq.index.map(pq_ac["q_mvar"].to_dict()).fillna(0).round(4)
    df_pq["P_DC"] = df_pq.index.map(pq_dc["p_mw"].to_dict()).fillna(0).round(4)
    df_pq["Q_DC"] = df_pq.index.map(pq_dc["q_mvar"].to_dict()).fillna(0).round(4)

    df_pq["bus_type"] = df_pq.index.map(bus_type)

    total_row = pd.DataFrame(df_pq.drop(columns="bus_type").sum(), columns=["Total"]).T
    total_row["bus_type"] = "Total"

    df_pq = pd.concat([df_pq, total_row], ignore_index=False)

    print("\nPQ values:")
    print(tabulate(df_pq, headers="keys", tablefmt="psql"))

    TOLERANCE = 10

    total_p_lacpf = total_row["P_LACPF"].values[0]
    total_q_lacpf = total_row["Q_LACPF"].values[0]
    total_p_ac = total_row["P_AC"].values[0]
    total_q_ac = total_row["Q_AC"].values[0]
    total_p_dc = total_row["P_DC"].values[0]
    total_q_dc = total_row["Q_DC"].values[0]

    def check_balance(val, label):
        if abs(val) > TOLERANCE:
            print(
                f"\t⚠️ WARNING: {label} balance = {val:.4f} exceeds tolerance ±{TOLERANCE}"
            )
        else:
            print(f"✅ {label} balance = {val:.4f} OK")

    check_balance(total_p_lacpf, "P_LACPF")
    check_balance(total_q_lacpf, "Q_LACPF")
    check_balance(total_p_ac, "P_AC")
    check_balance(total_q_ac, "Q_AC")
    check_balance(total_p_dc, "P_DC")
    check_balance(total_q_dc, "Q_DC")

    print("\n\tREGIME EVALUATION SUCCESSFULLY!!!")
    return 0


if __name__ == "__main__":

    from LACPF.models.calculate_regime import calculate_regime
    from LACPF.core.read_data import read_data
    from LACPF.core.perturbation import build_full_perturbation_template

    case = "case4gs"
    net = read_data(case)
    pp.rundcpp(net)

    perturbation = build_full_perturbation_template(net, proc=20)
    result = calculate_regime(net, perturbation)

    evaluate_regimes(result)

    print("\n\tTEST REGIME_EVALUATION.PY PASSED SUCCESSFULLY!!!\n")
