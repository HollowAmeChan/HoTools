"""Small, portable expression subset shared by native drivers and HoFBX.

The parser keeps authored expressions intact; the driver generator verifies
what Blender's RNA field actually stores before accepting a generated driver.
"""
import ast
import math
import re

FUNCTIONS = {"min": (2, 2), "max": (2, 2), "abs": (1, 1), "clamp": (3, 3)}
RESERVED = {"x", "y", "z", "pi", *FUNCTIONS}


def validate_name(name):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name or "") or name in RESERVED:
        raise ValueError(f"额外变量名无效或保留：{name}")


def parse(expression, names=()):
    if not expression:
        raise ValueError("表达式不能为空")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise ValueError("表达式语法无效") from exc
    nodes = list(ast.walk(tree))
    allowed_names = {"x", "y", "z", "pi", *names}
    for node in nodes:
        if isinstance(node, ast.Constant):
            if type(node.value) not in (int, float) or not math.isfinite(float(node.value)):
                raise ValueError("仅支持有限数值常量")
        elif isinstance(node, ast.Name):
            if node.id not in allowed_names and node.id not in FUNCTIONS:
                raise ValueError(f"未知变量：{node.id}")
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                raise ValueError("仅支持 min/max/abs/clamp 函数")
            lo, hi = FUNCTIONS[node.func.id]
            if node.keywords or not lo <= len(node.args) <= hi:
                raise ValueError(f"{node.func.id} 参数数量错误")
        elif not isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Load,
                                   ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow,
                                   ast.UAdd, ast.USub)):
            raise ValueError(f"不支持的表达式语法：{type(node).__name__}")
    # Function identifiers are legal only in the callee position.
    def emit(node):
        if isinstance(node, ast.Constant):
            return repr(node.value)
        if isinstance(node, ast.Name):
            if node.id not in allowed_names:
                raise ValueError(f"函数必须带参数：{node.id}")
            return "3.141592653589793" if node.id == "pi" else node.id
        if isinstance(node, ast.BinOp):
            symbol = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.Pow: "**"}[type(node.op)]
            return f"({emit(node.left)}{symbol}{emit(node.right)})"
        if isinstance(node, ast.UnaryOp):
            return f"({'-' if isinstance(node.op, ast.USub) else '+'}{emit(node.operand)})"
        if isinstance(node, ast.Call):
            args = [emit(arg) for arg in node.args]
            if node.func.id == "clamp":
                return f"min(max({args[0]},{args[1]}),{args[2]})"
            return f"{node.func.id}({','.join(args)})"
        return emit(node.body)
    result = emit(tree)
    # Blender 4.5 accepts the complete generated expression; keep it intact so
    # a dense RBF control domain does not need a custom-property proxy.
    return f"min(max({result},0),1)"
