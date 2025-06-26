from gurobipy import GRB


def solve_model(model):
    model.optimize()
    if model.status in [GRB.OPTIMAL, GRB.SUBOPTIMAL]:
        solution = {v.VarName: v.X for v in model.getVars()}
        return {"status": model.status, "solution": solution, "objective": model.ObjVal}
    if model.status == GRB.INFEASIBLE:
        model.computeIIS()
        model.write("scuc_model.ilp")
        print("Model infeasible. IIS written to scuc_model.ilp")
        print("Model validation (IIS):")
        for c in model.getConstrs():
            if c.IISConstr:
                print(
                    f"Infeasible constraint: {c.ConstrName}, RHS: {c.RHS}, Sense: {c.Sense}, Slack: {c.Slack}"
                )
        for v in model.getVars():
            if v.IISLB:
                print(f"Infeasible lower bound: {v.VarName}")
            if v.IISUB:
                print(f"Infeasible upper bound: {v.VarName}")
    return {"status": model.status, "solution": None, "objective": None}
