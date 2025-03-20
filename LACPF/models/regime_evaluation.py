import pandas as pd
import numpy as np
import pandapower as pp
from tabulate import tabulate


def evaluate_regimes(result):
    net_base = result["net_lacpf"]
    net_ac = result["net_ac"]
    net_dc = result["net_dc"]

    slack_buses = list(net.ext_grid.bus.values)  # Slack-узлы (обычно 1 узел, но на всякий случай оставляем массив)
    pv_buses = list(net.gen.bus.values)  # PV-узлы (генераторные, кроме slack)
    pq_buses = np.setdiff1d(net.bus.index, np.concatenate((slack_buses, pv_buses)))  # Чистые PQ-узлы

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


    voltage_violations = net_base.res_bus.loc[pq_buses, "vm_pu"] < 0.9
    angle_violations = net_base.res_bus.loc[pq_buses, "va_degree"].abs() > 30

    if voltage_violations.any():
        violating_buses = net_base.res_bus.loc[pq_buses[voltage_violations], "vm_pu"]
        print("\n⚠️ WARNING: Voltage below 0.9 pu detected in the following buses:")
        print(violating_buses)
    else:
        print("\n🟢 All LACPF voltages are within the limits")

    if angle_violations.any():
        violating_buses = net_base.res_bus.loc[pq_buses[angle_violations], "va_degree"]
        print("\n⚠️ WARNING: Voltage angle exceeds 30 degrees in the following buses:")
        print(violating_buses)
    else:
        print("\n🟢 All LACPF angles are within the limits")


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
    # df_comparison["in_model"] = df_comparison["bus_type"].isin(["PQ", "PV"])

    print("\nCalculations comparison:")
    # print(df_comparison)
    print(tabulate(df_comparison, headers="keys", tablefmt="psql"))

    print("\n\tREGIME EVALUATION SUCCESSFULLY!!!")
    return 0


if __name__ == "__main__":

    from LACPF.models.calculate_regime import calculate_regime
    from LACPF.core.read_data import read_data
    from LACPF.core.perturbation import build_full_perturbation_template

    case = "case4gs"
    net = read_data(case)
    pp.rundcpp(net)

    perturbation = build_full_perturbation_template(net, proc=50)
    result = calculate_regime(net, perturbation)

    evaluate_regimes(result)

    print("\n\tTEST REGIME_EVALUATION.PY PASSED SUCCESSFULLY!!!\n")
