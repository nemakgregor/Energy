import logging
from gurobipy import GRB


logger = logging.getLogger(__name__)


def solve_model(model):
    model.optimize()
    if model.status in [GRB.OPTIMAL, GRB.SUBOPTIMAL]:
        solution = {v.VarName: v.X for v in model.getVars()}
        return {"status": model.status, "solution": solution, "objective": model.ObjVal}
    if model.status == GRB.INFEASIBLE:
        model.computeIIS()
        model.write("scuc_model.ilp")
        logger.error("Model infeasible. IIS written to scuc_model.ilp")
        logger.error("Model validation (IIS):")
        for c in model.getConstrs():
            if c.IISConstr:
                logger.error(
                    "Infeasible constraint: %s, RHS: %s, Sense: %s, Slack: %s",
                    c.ConstrName,
                    c.RHS,
                    c.Sense,
                    c.Slack,
                )
        for v in model.getVars():
            if v.IISLB:
                logger.error("Infeasible lower bound: %s", v.VarName)
            if v.IISUB:
                logger.error("Infeasible upper bound: %s", v.VarName)
    return {"status": model.status, "solution": None, "objective": None}
