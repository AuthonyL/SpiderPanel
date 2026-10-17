import copy
import json

import pytest

from SpiderPanel import extract, rules


CREATE = "wqb_create_multi_simulation"
WAIT = "local_wait_multi_simulation"
EVALUATE = "evaluate_simulation_alphas"
PROD = "check_alpha_prod_correlation"
SAVE = "save_candidate_alpha"
PRECHECK = "check_expression_group_diversity"
FORBIDDEN = {
    "details", "raw", "children", "recommendation", "validation_result",
    "precheck_result", "check_result", "expression_features", "author", "pnl",
}


@pytest.mark.parametrize("name,args,expected", [
    (CREATE, {"alpha_expressions": ["rank(close)", "volume"]}, {"n": 2}),
    (PRECHECK, {"expressions": ["rank(close)"]}, {"n": 1}),
    (WAIT, {"multisimulation_url": "https://example.invalid/simulations/wait_sim/?secret=1"}, {"sim": "wait_sim"}),
    (EVALUATE, {"simulation_url": "https://example.invalid/simulations/eval_sim/?secret=1"}, {"sim": "eval_sim"}),
    (PROD, {"alpha_id": "alpha_prod"}, {"alpha": "alpha_prod"}),
    (SAVE, {"alpha_id": "alpha_save"}, {"alpha": "alpha_save"}),
])
def test_start_summary_is_parameter_only(name, args, expected):
    args.update(raw="private", prod=99, status="completed", region="USA")
    before = copy.deepcopy(args)
    assert extract.start_summary(extract.NAME_ROLES[name], args) == expected
    assert args == before


@pytest.mark.parametrize("name,expected", [
    (CREATE, {"n": 0}), (PRECHECK, {"n": 0}),
    (WAIT, {"sim": None}), (EVALUATE, {"sim": None}),
    (PROD, {"alpha": None}), (SAVE, {"alpha": None}),
])
@pytest.mark.parametrize("args", [None, [], 42, {
    "alpha_expressions": 2, "expressions": {}, "alpha_id": [],
    "multisimulation_url": [], "simulation_url": "http://[malformed",
}])
def test_start_summary_malformed_arguments_do_not_leak(name, args, expected):
    assert extract.start_summary(extract.NAME_ROLES[name], args) == expected


def assert_whitelist(value):
    if isinstance(value, dict):
        assert not FORBIDDEN.intersection(value)
        for item in value.values():
            assert_whitelist(item)
    elif isinstance(value, list):
        for item in value:
            assert_whitelist(item)


def run(name, args, result):
    before = copy.deepcopy(result)
    summary = extract.TRACKED[extract.NAME_ROLES[name]](args, result)
    assert result == before
    assert_whitelist(summary)
    json.dumps(summary, allow_nan=False)
    return summary


def test_create_submitted_and_validation_failed(sample):
    args = {"alpha_expressions": ["rank(close)", "ts_delta(volume, 5)"]}
    summary = run(CREATE, args, sample("create_submitted"))
    assert summary == {
        "status": "submitted", "sim": "sim_demo", "ok": True,
        "region": None, "universe": None, "delay": None,
        "exprs": [[extract.expression_hash("rank(close)"), "rank(close)"],
                  [extract.expression_hash("ts_delta(volume, 5)"), "ts_delta(volume, 5)"]],
    }
    summary = run(CREATE, args, sample("create_validation_failed"))
    assert summary["ok"] is False
    assert summary["n"] == 2
    assert summary["err"] == "❌ 表达式组检查未通过，未提交回测"
    assert "exprs" not in summary
    summary = run(CREATE, args, {"status": "busy", "message": "retry", "success": 1})
    assert summary["err"] == "retry"
    assert summary["ok"] is False


@pytest.mark.parametrize("args,expected", [
    ({"region": "ASI", "universe": "TOP500", "delay": 1}, ("ASI", "TOP500", 1)),
    ({"region": 1, "universe": [], "delay": True}, (None, None, None)),
    ({"delay": 1.0}, (None, None, None)),
])
def test_simulate_session_settings(args, expected):
    summary = extract.TRACKED["simulate"](args, {"status": "submitted", "success": True})
    assert (summary["region"], summary["universe"], summary["delay"]) == expected


def test_wait_completed_string_regular_and_error_entry(sample):
    result = sample("wait_completed")
    summary = run(WAIT, {}, result)
    assert summary["sim"] == "sim_demo"
    assert summary["status"] == "completed"
    assert len(summary["alphas"]) == 8
    assert summary["alphas"][0][1:] == ["alpha_01", 0.04, 0.0, 0.8638]
    result["alpha_results"][0]["details"]["regular"] = "rank(close)"
    result["alpha_results"].append({"alpha_id": "alpha_error", "error": "no data"})
    summary = run(WAIT, {}, result)
    assert summary["alphas"][0][0] == extract.expression_hash("rank(close)")
    assert summary["alphas"][-1] == [None, "alpha_error", None, None, None]


def test_wait_failed_and_pending(sample):
    summary = run(WAIT, {}, sample("wait_failed"))
    assert summary["ok"] is False
    assert summary["err"] == "Not found."
    for status in ("pending", "failed"):
        summary = run(WAIT, {"multisimulation_url": "https://example.invalid/simulations/fallback/?x=1"},
                      {"status": status, "message": "wait again"})
        assert summary["sim"] == "fallback"
        assert summary["ok"] is (status == "pending")
        if status == "failed":
            assert summary["err"] == "wait again"


def test_evaluate_normal_empty_and_hash_agreement(sample):
    result = sample("evaluate")
    result["all_alphas"][0]["expression"] = " rank( \n close ) "
    summary = run(EVALUATE, {"simulation_url": "https://example.invalid/simulations/eval_sim"}, result)
    assert summary["sim"] == "eval_sim"
    assert summary["best"] is None
    assert len(summary["alphas"]) == 8
    assert summary["alphas"][0][2:5] == [False, -0.82, -0.39]
    assert summary["alphas"][0][5] == ["sharpe", "fitness", "margin", "sub_universe_sharpe", "low_2y_sharpe"]
    waited = run(WAIT, {}, sample("wait_completed"))
    assert summary["alphas"][0][1] == waited["alphas"][0][0]
    result.update(has_best=True, best_alpha_id="alpha_01")
    assert run(EVALUATE, {}, result)["best"] == "alpha_01"
    summary = run(EVALUATE, {}, {"all_alphas": [], "has_best": False, "recommendation": "超时" * 300})
    assert summary["ok"] is False
    assert len(summary["err"]) == 200


def test_prod_null_error_and_numeric_value(sample):
    result = sample("prod")["result"]  # Client envelope is not the tool return.
    assert run(PROD, {"alpha_id": "alpha_prod"}, result) == {"alpha": "alpha_prod", "prod": None}
    result["prod"] = 0.123456
    assert run(PROD, {"alpha_id": "alpha_prod"}, result)["prod"] == 0.1235
    result.update(prod=None, error="API unavailable")
    assert run(PROD, {"alpha_id": "alpha_prod"}, result) == {
        "alpha": "alpha_prod", "prod": None, "err": "API unavailable", "ok": False,
    }


@pytest.mark.parametrize("fixture,passed", [("save_ok", True), ("save_rejected", False)])
def test_save_business_result_is_not_tool_error(sample, fixture, passed):
    result = sample(fixture)
    summary = run(SAVE, {"alpha_id": result["alpha_id"]}, result)
    assert summary == {"alpha": result["alpha_id"], "passed": passed, "saved": passed}
    result["error"] = "failed to save"
    summary = run(SAVE, {"alpha_id": result["alpha_id"]}, result)
    assert summary["ok"] is False
    assert summary["err"] == "failed to save"


@pytest.mark.parametrize("status", ["pass", "fail"])
def test_precheck_pass_and_fail(sample, status):
    result = sample("diversity")
    result["status"] = status
    assert run(PRECHECK, {"expressions": ["rank(close)"] * 8}, result) == {"status": status, "n": 8}


@pytest.mark.parametrize("name", [CREATE, WAIT, EVALUATE, PROD, SAVE, PRECHECK])
@pytest.mark.parametrize("bad", [None, {}, [], "wrong", 42, {
    "alpha_expressions": 7, "expressions": {}, "alpha_results": [None, 4, {"details": "bad", "error": {"raw": 1}}],
    "all_alphas": [None, {"expression": [], "failed_checks": [{"details": "private"}, 8]}],
    "prod": {}, "status": [], "failure": [], "error": {"raw": 1}, "has_best": [],
    "alpha_id": {}, "multisimulation_id": {}, "best_alpha_id": {},
    "saved_locally": [], "all_checks_passed": {},
}])
def test_malformed_inputs_do_not_raise_or_leak(name, bad):
    summary = extract.TRACKED[extract.NAME_ROLES[name]](bad, bad)
    assert isinstance(summary, dict)
    assert_whitelist(summary)
    json.dumps(summary, allow_nan=False)


@pytest.mark.parametrize("bad", [True, "0.12", None, float("nan"), float("inf"), -float("inf"), 10**1000])
def test_non_numeric_or_non_finite_metrics_are_null(bad):
    assert extract.TRACKED["prod"]({}, {"prod": bad})["prod"] is None


@pytest.mark.parametrize("value", [0, 1, -1])
def test_integer_metrics_are_floats(value):
    prod = extract.TRACKED["prod"]({}, {"prod": value})["prod"]
    assert isinstance(prod, float)
    assert prod == value


def test_hash_whitespace_and_preview_limits():
    assert extract.expression_hash("rank( close )") == extract.expression_hash("\trank(close)\n")
    assert len(extract.expression_hash("rank(close)")) == 10
    assert extract.expression_hash(None) is None
    summary = run(CREATE, {"alpha_expressions": ["中" * (rules.EXPR_CHARS + 1)]}, {"status": "submitted", "success": True})
    assert len(summary["exprs"][0][1]) == rules.EXPR_CHARS


@pytest.mark.parametrize("name", [CREATE, WAIT, EVALUATE])
def test_malformed_unicode_expression_does_not_raise(name):
    expression = "rank(\ud800)"
    summary = extract.TRACKED[extract.NAME_ROLES[name]](
        {"alpha_expressions": [expression]},
        {"status": "submitted", "success": True,
         "alpha_results": [{"details": {"regular": {"code": expression}}}],
         "all_alphas": [{"expression": expression}]},
    )
    hash_value = (summary["exprs"][0][0] if name == CREATE else
                  summary["alphas"][0][0 if name == WAIT else 1])
    assert hash_value is None


def test_fixtures_are_small_and_anonymous():
    from pathlib import Path
    for path in (Path(__file__).parent / "fixtures").glob("*.json"):
        assert path.stat().st_size < 10_000
        text = path.read_text()
        assert '"author"' not in text
        assert "worldquantbrain.com" not in text
