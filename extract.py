"""Allowlisted tool summaries; nested tool payloads never leave this module."""

import hashlib
import math
import re
from urllib.parse import urlsplit

from .rules import ERR_CHARS, EXPR_CHARS, MAX_FAILED_CHECKS


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return value if isinstance(value, (list, tuple)) else []


def _text(value):
    return value if isinstance(value, str) else None


def _bool(value):
    return value if isinstance(value, bool) else None


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
        return round(number, 4) if math.isfinite(number) else None
    except (OverflowError, ValueError):
        return None


def _last_path(value):
    if not isinstance(value, str):
        return None
    try:
        return urlsplit(value).path.rstrip("/").rsplit("/", 1)[-1] or None
    except ValueError:
        return None


def expression_hash(expr):
    """Hash the full expression after removing whitespace, before preview cuts."""
    if not isinstance(expr, str):
        return None
    try:
        return hashlib.sha1(re.sub(r"\s+", "", expr).encode()).hexdigest()[:10]
    except UnicodeError:
        return None


def _error(value):
    text = _text(value)
    return text[:ERR_CHARS] if text else None


def start_summary(role: str, args: dict) -> dict:
    """Return only parameter identifiers or counts known before tool execution."""
    args = _dict(args)
    if role == "simulate":
        return {"n": len(_list(args.get("alpha_expressions")))}
    if role == "precheck":
        return {"n": len(_list(args.get("expressions")))}
    if role == "result":
        return {"sim": _last_path(args.get("multisimulation_url"))}
    if role == "evaluate":
        return {"sim": _last_path(args.get("simulation_url"))}
    if role in ("prod", "save"):
        return {"alpha": _text(args.get("alpha_id"))}
    return {}


def wqb_create_multi_simulation(args: dict, result) -> dict:
    args, result = _dict(args), _dict(result)
    expressions = _list(args.get("alpha_expressions"))
    summary = {
        "status": _text(result.get("status")),
        "sim": _text(result.get("multisimulation_id")),
        "ok": result.get("success") is True,
        "region": _text(args.get("region")),
        "universe": _text(args.get("universe")),
        "delay": args.get("delay") if type(args.get("delay")) is int else None,
    }
    if summary["status"] == "submitted":
        summary["exprs"] = [
            [expression_hash(expr), expr[:EXPR_CHARS] if isinstance(expr, str) else None]
            for expr in expressions
        ]
    else:
        summary["n"] = len(expressions)
        summary["err"] = _error(result.get("error")) or _error(result.get("message"))
    return summary


def local_wait_multi_simulation(args: dict, result) -> dict:
    args, result = _dict(args), _dict(result)
    alphas = []
    for item in _list(result.get("alpha_results")):
        item = _dict(item)
        details = _dict(item.get("details"))
        regular = details.get("regular")
        expression = regular if isinstance(regular, str) else _dict(regular).get("code")
        metrics = _dict(details.get("is"))
        alphas.append([
            expression_hash(expression), _text(item.get("alpha_id")),
            _number(metrics.get("sharpe")), _number(metrics.get("fitness")),
            _number(metrics.get("turnover")),
        ])
    summary = {
        "sim": _text(result.get("multisimulation_id")) or _last_path(args.get("multisimulation_url")),
        "status": _text(result.get("status")),
        "alphas": alphas,
        "ok": result.get("status") != "failed",
    }
    if summary["status"] == "failed":
        summary["err"] = _error(_dict(result.get("failure")).get("error")) or _error(result.get("message"))
    return summary


def evaluate_simulation_alphas(args: dict, result) -> dict:
    args, result = _dict(args), _dict(result)
    alphas = []
    for item in _list(result.get("all_alphas")):
        item = _dict(item)
        checks = [check for check in _list(item.get("failed_checks")) if isinstance(check, str)]
        alphas.append([
            _text(item.get("alpha_id")), expression_hash(item.get("expression")),
            _bool(item.get("eval_passed")), _number(item.get("sharpe")),
            _number(item.get("fitness")), checks[:MAX_FAILED_CHECKS],
        ])
    summary = {
        "sim": _last_path(args.get("simulation_url")),
        "alphas": alphas,
        "best": _text(result.get("best_alpha_id")),
    }
    if not alphas and not result.get("has_best"):
        summary.update(ok=False, err=_error(result.get("recommendation")))
    return summary


def check_alpha_prod_correlation(args: dict, result) -> dict:
    args, result = _dict(args), _dict(result)
    summary = {"alpha": _text(args.get("alpha_id")), "prod": _number(result.get("prod"))}
    error = _error(result.get("error"))
    if error:
        summary.update(ok=False, err=error)
    return summary


def save_candidate_alpha(args: dict, result) -> dict:
    args, result = _dict(args), _dict(result)
    summary = {
        "alpha": _text(args.get("alpha_id")),
        "passed": _bool(result.get("all_checks_passed")),
        "saved": _bool(result.get("saved_locally")),
    }
    error = _error(result.get("error"))
    if error:
        summary.update(ok=False, err=error)
    return summary


def check_expression_group_diversity(args: dict, result) -> dict:
    status = _text(_dict(result).get("status"))
    return {
        "status": status if status in ("pass", "fail") else None,
        "n": len(_list(_dict(args).get("expressions"))),
    }


NAME_ROLES = {
    "wqb_create_multi_simulation": "simulate",
    "local_wait_multi_simulation": "result",
    "evaluate_simulation_alphas": "evaluate",
    "check_alpha_prod_correlation": "prod",
    "save_candidate_alpha": "save",
    "check_expression_group_diversity": "precheck",
}
TRACKED = {role: globals()[name] for name, role in NAME_ROLES.items()}
