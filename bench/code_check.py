"""Run only a restricted algorithm fixture in a separate bounded process.

This is not a general Python sandbox. Do not expand the grammar to arbitrary
programs. The curated exercise needs only local collections, loops and arithmetic.
"""
import ast
import json
import sys

ALLOWED = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return,
           ast.Assign, ast.AugAssign, ast.If, ast.For, ast.Expr, ast.Pass, ast.Break,
           ast.Continue, ast.Name, ast.Load, ast.Store, ast.Constant, ast.List,
           ast.Tuple, ast.Dict, ast.Subscript, ast.BinOp, ast.Add, ast.Sub,
           ast.Compare, ast.Eq, ast.NotEq, ast.In, ast.NotIn, ast.Lt, ast.Gt,
           ast.LtE, ast.GtE, ast.Is, ast.IsNot, ast.Call, ast.UnaryOp, ast.USub,
           ast.UAdd, ast.Not, ast.BoolOp, ast.And, ast.Or, ast.IfExp)


def evaluate(source):
    tree = ast.parse(source)
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef) or tree.body[0].name != "two_sum":
        raise ValueError("Only the two_sum function is accepted")
    fn = tree.body[0]
    if fn.decorator_list or fn.returns or fn.args.defaults or fn.args.kw_defaults or fn.args.vararg or fn.args.kwarg or fn.args.kwonlyargs or fn.args.posonlyargs:
        raise ValueError("Use a plain two-argument function")
    if [a.arg for a in fn.args.args] != ["nums", "target"] or any(a.annotation for a in fn.args.args):
        raise ValueError("Expected two_sum(nums, target)")
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED):
            raise ValueError("Unsupported code construct")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ValueError("Private names are not allowed")
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in {"enumerate", "range", "len"} or node.keywords):
            raise ValueError("Only enumerate, range and len calls are accepted")
        if isinstance(node, ast.Constant) and (not isinstance(node.value, (int, str, type(None))) or
                                              isinstance(node.value, int) and abs(node.value) > 100000 or
                                              isinstance(node.value, str) and len(node.value) > 2000):
            raise ValueError("Constant outside the fixture limits")
    scope = {"__builtins__": {}, "enumerate": enumerate, "range": range, "len": len}
    exec(compile(tree, "<benchmark-exercise>", "exec"), scope)
    checks = []
    for label, values, target, solvable in [
        ("basic pair", [2, 7, 11, 15], 9, True), ("duplicates", [3, 3], 6, True),
        ("negative values", [-3, 4, 3, 90], 0, True), ("no solution", [1, 2, 3], 99, False),
        ("empty input", [], 0, False), ("cannot reuse one index", [3], 6, False),
        ("zero pair", [0, 5, 0], 0, True), ("later pair", [1, 8, 3, 4], 7, True),
    ]:
        original = list(values)
        try:
            result = scope["two_sum"](values, target)
            passed = result is None if not solvable else (
                isinstance(result, (tuple, list)) and len(result) == 2 and
                all(type(i) is int and 0 <= i < len(values) for i in result) and
                result[0] != result[1] and sum(original[i] for i in result) == target)
            passed = bool(passed and values == original)
        except Exception:
            passed = False
        checks.append({"name": label, "passed": passed})
    return checks


if __name__ == "__main__":
    try:
        source = sys.stdin.read(20001)
        if len(source) > 20000:
            raise ValueError("Exercise is too large")
        print(json.dumps({"checks": evaluate(source)}))
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": "Use the plain-function subset described in the fixture README."}))
