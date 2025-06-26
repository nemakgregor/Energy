import os
import logging
from config import get_config
from data_handler import load_case, validate_data
from model_builder import build_model
from solver import solve_model
from solution_logger import log_solution, print_solution
from logger import setup_logger


logger = logging.getLogger(__name__)


def process_case(file_path, config, output_dir, logger):
    try:
        data = load_case(file_path)

        errors, warnings, available_capacity_t0, max_demand, adjusted_reserve = (
            validate_data(data)
        )
        if errors:
            logger.error("Errors in %s: %s", file_path, errors)
            return
        if warnings:
            logger.warning("Warnings in %s: %s", file_path, warnings)
        logger.info(
            "Processing %s: Capacity %.2f MW, Demand %.2f MW, Reserve %.2f MW",
            file_path,
            available_capacity_t0,
            max_demand,
            max(adjusted_reserve),
        )

        model, vars = build_model(
            data, available_capacity_t0, max_demand, adjusted_reserve, config
        )
        solution = solve_model(model)

        output_path = os.path.join(
            output_dir, f"solution_{os.path.basename(file_path)}"
        )
        log_solution(solution, output_path, logger)
        print_solution(solution)
    except Exception as e:
        logger.error("Error processing %s: %s", file_path, e)


def run_batch(input_files, config=None, output_dir="solutions", log_file="process.log"):
    config = get_config(config)
    os.makedirs(output_dir, exist_ok=True)
    logger = setup_logger(log_file)
    for file_path in input_files:
        process_case(file_path, config, output_dir, logger)


if __name__ == "__main__":
    config = {
        "time_limit": 120,
        "mip_gap": 0.1,
        "verbose": True,
        "use_warm_start": True,
        "include_contingencies": False,
        "fixed_generators": [],
        "ignore_lines": [],
        "cost_scale": 1000.0,
    }

    input_files = [
        r"C:\Users\egor1\Desktop\Energy\Repo\SCUC\scuc_solver\data\case14.json"
    ]
    run_batch(input_files, config, log_file="scuc_process.log")
