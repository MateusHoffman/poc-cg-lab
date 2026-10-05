from __future__ import annotations

import ast

class SandboxError(Exception):
    pass


def pmt(principal: float, monthly_rate: float, months: int) -> float:
    principal = float(principal)
    monthly_rate = float(monthly_rate)
    months = int(months)
    if months <= 0 or principal < 0 or monthly_rate < 0:
        raise SandboxError("parâmetros financeiros inválidos")
    if monthly_rate == 0:
        return principal / months
    growth = (1 + monthly_rate) ** months
    return principal * monthly_rate * growth / (growth - 1)


def tco(price: float, yearly_km: float, cost_per_km: float, years: int) -> float:
    return float(price) + float(yearly_km) * float(cost_per_km) * int(years)


_FUNCTIONS = {"pmt": pmt, "tco": tco, "round": round, "abs": abs, "min": min, "max": max}

_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.FloorDiv,
    ast.USub,
    ast.UAdd,
    ast.Call,
)


def run_sandbox(code: str) -> float:
    """Executa só expressões matemáticas.

    Equivalente local ao isolamento do Bedrock AgentCore Code Interpreter:
    sem import, sem atributo, sem acesso a arquivo ou rede.
    """
    if len(code) > 240:
        raise SandboxError("expressão longa demais")
    try:
        tree = ast.parse(code, mode="eval")
    except SyntaxError as exc:
        raise SandboxError("sintaxe recusada") from exc

    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise SandboxError(f"nó bloqueado: {type(node).__name__}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
                raise SandboxError("função não permitida")
            if node.keywords or any(isinstance(arg, ast.Starred) for arg in node.args):
                raise SandboxError("chamada não permitida")
        if isinstance(node, ast.Name) and node.id not in _FUNCTIONS:
            raise SandboxError(f"nome bloqueado: {node.id}")
        if isinstance(node, ast.Pow) and isinstance(node.right, ast.Constant):
            exponent = node.right.value
            if isinstance(exponent, (int, float)) and abs(exponent) > 12:
                raise SandboxError("expoente recusado")

    result = eval(compile(tree, "<sandbox>", "eval"), {"__builtins__": {}}, _FUNCTIONS)
    if isinstance(result, bool) or not isinstance(result, (int, float)):
        raise SandboxError("resultado inválido")
    return float(result)
