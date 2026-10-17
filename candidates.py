"""Read the candidate ledgers as data; never import or lock their writers."""

import json
from pathlib import Path


def load_candidate_expressions(paths):
    result = {}
    for path in paths:
        try:
            with Path(path).open("rb") as file:
                for raw in file:
                    try:
                        row = json.loads(raw)
                    except (ValueError, RecursionError):
                        continue
                    if not isinstance(row, dict):
                        continue
                    alpha, expression = row.get("alpha_id"), row.get("expression")
                    if isinstance(alpha, str) and alpha.strip() and isinstance(expression, str) and expression.strip():
                        try:
                            alpha.encode("utf-8")
                            expression.encode("utf-8")
                        except UnicodeError:
                            continue
                        result[alpha] = expression
        except (OSError, ValueError, TypeError, OverflowError, RecursionError):
            continue
    return result
