"""Small CP-SAT-compatible test adapter backed by scipy.optimize.milp.

It implements only the OR-Tools API surface used by this project. Production
uses Google OR-Tools; this adapter lets the same solver model run in restricted
build environments where the compiled OR-Tools wheel is unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csr_matrix

OPTIMAL = 4
FEASIBLE = 2
INFEASIBLE = 3


class LinearExpr:
    def __init__(self, coeffs=None, constant: float = 0.0):
        self.coeffs = dict(coeffs or {})
        self.constant = float(constant)

    @staticmethod
    def coerce(value):
        if isinstance(value, LinearExpr):
            return value
        if isinstance(value, (int, float, np.integer, np.floating)):
            return LinearExpr(constant=float(value))
        raise TypeError(f"Unsupported expression value: {type(value)!r}")

    def _combine(self, other, sign: float):
        other = LinearExpr.coerce(other)
        coeffs = dict(self.coeffs)
        for index, coefficient in other.coeffs.items():
            coeffs[index] = coeffs.get(index, 0.0) + sign * coefficient
            if abs(coeffs[index]) < 1e-12:
                coeffs.pop(index)
        return LinearExpr(coeffs, self.constant + sign * other.constant)

    def __add__(self, other):
        return self._combine(other, 1.0)

    def __radd__(self, other):
        return LinearExpr.coerce(other)._combine(self, 1.0)

    def __sub__(self, other):
        return self._combine(other, -1.0)

    def __rsub__(self, other):
        return LinearExpr.coerce(other)._combine(self, -1.0)

    def __mul__(self, scalar):
        if not isinstance(scalar, (int, float)):
            return NotImplemented
        return LinearExpr(
            {index: scalar * value for index, value in self.coeffs.items()},
            scalar * self.constant,
        )

    __rmul__ = __mul__

    def __neg__(self):
        return self * -1

    def __eq__(self, other):  # type: ignore[override]
        return BoundedExpr(self - other, 0.0, 0.0)

    def __le__(self, other):
        return BoundedExpr(self - other, -np.inf, 0.0)

    def __ge__(self, other):
        return BoundedExpr(self - other, 0.0, np.inf)


class IntVar(LinearExpr):
    def __init__(self, index: int, name: str, lower: int = 0, upper: int = 1):
        super().__init__({index: 1.0}, 0.0)
        self.index = index
        self.name = name
        self.lower = lower
        self.upper = upper


@dataclass
class BoundedExpr:
    expr: LinearExpr
    lower: float
    upper: float


class CpModel:
    def __init__(self):
        self.variables: list[IntVar] = []
        self.constraints: list[BoundedExpr] = []
        self.objective = LinearExpr()

    def NewBoolVar(self, name: str) -> IntVar:
        variable = IntVar(len(self.variables), name, 0, 1)
        self.variables.append(variable)
        return variable

    def NewIntVar(self, lower: int, upper: int, name: str) -> IntVar:
        variable = IntVar(len(self.variables), name, lower, upper)
        self.variables.append(variable)
        return variable

    def Add(self, constraint):
        if isinstance(constraint, bool):
            if not constraint:
                self.constraints.append(BoundedExpr(LinearExpr(), 1.0, 0.0))
            return constraint
        if not isinstance(constraint, BoundedExpr):
            raise TypeError("Add expects a linear comparison.")
        self.constraints.append(constraint)
        return constraint

    def AddMaxEquality(self, target: IntVar, expressions):
        expressions = list(expressions)
        if not expressions:
            self.Add(target == 0)
            return
        # Boolean target equals OR(expressions).
        for expression in expressions:
            self.Add(target >= expression)
        self.Add(target <= sum(expressions))

    def Minimize(self, expression):
        self.objective = LinearExpr.coerce(expression)


class CpSolver:
    def __init__(self):
        self.parameters = SimpleNamespace(
            max_time_in_seconds=None,
            num_search_workers=None,
        )
        self._values: np.ndarray | None = None

    def Solve(self, model: CpModel):
        count = len(model.variables)
        if count == 0:
            valid = all(
                constraint.lower <= constraint.expr.constant <= constraint.upper
                for constraint in model.constraints
            )
            self._values = np.zeros(0)
            return OPTIMAL if valid else INFEASIBLE

        c = np.zeros(count)
        for index, coefficient in model.objective.coeffs.items():
            c[index] = coefficient

        rows = []
        lowers = []
        uppers = []
        for constraint in model.constraints:
            row = np.zeros(count)
            for index, coefficient in constraint.expr.coeffs.items():
                row[index] = coefficient
            rows.append(row)
            lowers.append(constraint.lower - constraint.expr.constant)
            uppers.append(constraint.upper - constraint.expr.constant)

        linear_constraints = None
        if rows:
            linear_constraints = LinearConstraint(
                csr_matrix(np.asarray(rows)), np.asarray(lowers), np.asarray(uppers)
            )

        options = {"disp": False}
        if self.parameters.max_time_in_seconds:
            options["time_limit"] = float(self.parameters.max_time_in_seconds)

        result = milp(
            c=c,
            integrality=np.ones(count),
            bounds=Bounds(
                np.asarray([variable.lower for variable in model.variables], dtype=float),
                np.asarray([variable.upper for variable in model.variables], dtype=float),
            ),
            constraints=linear_constraints,
            options=options,
        )
        if not result.success or result.x is None:
            self._values = None
            return INFEASIBLE
        self._values = np.rint(result.x).astype(int)
        return OPTIMAL

    def Value(self, expression):
        if self._values is None:
            raise RuntimeError("Solve must be called first.")
        expression = LinearExpr.coerce(expression)
        value = expression.constant
        for index, coefficient in expression.coeffs.items():
            value += coefficient * self._values[index]
        return int(round(value))
