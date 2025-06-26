import json
import logging
import os

def log_solution(solution, output_path, logger=None):
    """Write solver output to ``output_path`` as JSON and log the action."""
    logger = logger or logging.getLogger(__name__)
    if not solution["solution"]:
        with open(output_path, "w") as f:
            f.write(f"Status: {solution['status']}\nNo solution found.")
        logger.info("No feasible solution. Status: %s", solution["status"])
        logger.info("Solution written to %s", output_path)
        return
    output = {
        "status": solution["status"],
        "objective": solution["objective"],
        "variables": solution["solution"],
    }
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    logger.info("Solution written to %s", output_path)

def print_solution(solution):
    """Pretty-print a solver output dictionary."""
    if not solution["solution"]:
        print(f"Status: {solution['status']}\nNo solution found.")
        return

    print(f"Objective: {solution['objective']:.2f}")
    for var_name, var_value in solution["solution"].items():
        if "dispatch" in var_name and var_value > 1e-3:
            print(f"{var_name}: {var_value:.2f} MW")
        if "commit" in var_name and var_value > 0.5:
            print(f"{var_name}: {var_value:.0f}")
        if "reserve_slack" in var_name and var_value > 1e-3:
            print(f"{var_name}: {var_value:.2f} MW")
        if "balance_slack" in var_name and var_value > 1e-3:
            print(f"{var_name}: {var_value:.2f} MW")
        if "charge" in var_name and var_value > 1e-3:
            print(f"{var_name}: {var_value:.2f} MW")
        if "discharge" in var_name and var_value > 1e-3:
            print(f"{var_name}: {var_value:.2f} MW")
        if "level" in var_name:
            print(f"{var_name}: {var_value:.2f} MWh")

