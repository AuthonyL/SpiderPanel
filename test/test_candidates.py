"""Read candidate expressions without importing or touching the ledger writers."""

import json

from SpiderPanel import rules
from SpiderPanel.server import PanelRuntime
from test_server import append
from test_state import DAY, TS, line


EXPRESSION = "rank(" + "close + " * 50 + "volume)"


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")


def pipeline(root):
    append(root, DAY, line("simulate", status="submitted", sim="sim", exprs=[["h", EXPRESSION[:120]]]))
    append(root, DAY, line("result", ts=TS+1, status="completed", sim="sim", alphas=[["h", "a1", 1.8, 1.2, .2]]))
    append(root, DAY, line("evaluate", ts=TS+2, sim="sim", best="a1", alphas=[["a1", "h", True, 1.8, 1.2, []]]))
    append(root, DAY, line("prod", ts=TS+3, alpha="a1", prod=.65))
    append(root, DAY, line("save", ts=TS+4, alpha="a1", passed=True, saved=True))


def test_missing_and_unreadable_ledgers_are_ignored(tmp_path, capsys):
    from SpiderPanel.candidates import load_candidate_expressions
    assert load_candidate_expressions((tmp_path / "missing.jsonl", tmp_path)) == {}
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_malformed_lines_and_empty_or_non_string_fields_are_ignored(tmp_path):
    from SpiderPanel.candidates import load_candidate_expressions
    path = tmp_path / "bad.jsonl"
    rows = [None, [], 7, True, "text", {}]
    for value in (None, 7, True, [], {}, "", " "):
        rows.extend([{"alpha_id": value, "expression": "close"}, {"alpha_id": "a1", "expression": value}])
    rows.append({"alpha_id": "a1", "expression": EXPRESSION})
    write(path, rows)
    with path.open("ab") as file:
        file.write(b'\n{\n\xff\n' + b'[' * 2000 + b'\n{"alpha_id":"a2","expression":"volume"}')
    assert load_candidate_expressions((path,)) == {"a1": EXPRESSION, "a2": "volume"}


def test_both_ledgers_merge_and_later_rows_win_without_a_final_newline(tmp_path):
    from SpiderPanel.candidates import load_candidate_expressions
    regular, super_alpha = tmp_path / "regular.jsonl", tmp_path / "super.jsonl"
    write(regular, [{"alpha_id": "a1", "expression": "old"}, {"alpha_id": "a1", "expression": "close"},
                    {"alpha_id": "a2", "expression": "volume"}])
    write(super_alpha, [{"alpha_id": "a1", "expression": EXPRESSION}, {"alpha_id": "a3", "expression": "returns"}])
    originals = [path.read_bytes() for path in (regular, super_alpha)]
    assert load_candidate_expressions((regular,)) == {"a1": "close", "a2": "volume"}
    assert load_candidate_expressions((regular, super_alpha)) == {"a1": EXPRESSION, "a2": "volume", "a3": "returns"}
    assert [path.read_bytes() for path in (regular, super_alpha)] == originals


def test_runtime_backfills_candidate_alpha_and_best_without_changing_log_state(tmp_path):
    path = tmp_path / "regular.jsonl"
    write(path, [{"alpha_id": "a1", "expression": EXPRESSION}])
    pipeline(tmp_path)
    runtime = PanelRuntime(tmp_path, day=DAY, clock=lambda: TS+10, progress_path=tmp_path / "progress.json",
                           candidate_paths=(path, tmp_path / "super.jsonl"))
    try:
        runtime.poll()
        snap = runtime.snapshot()
        assert snap["review"][0]["id"] == "a1" and snap["review"][0]["status"] == "candidate"
        assert snap["review"][0]["expr"] == EXPRESSION
        assert next(alpha for alpha in snap["alphas"] if alpha["id"] == "a1")["expr"] == EXPRESSION
        assert snap["best"]["expr"] == EXPRESSION
        assert runtime.state.snapshot("replay")["review"][0]["expr"] == EXPRESSION[:120]
    finally:
        runtime.close()


def test_unencodable_ledger_strings_are_ignored_without_breaking_payload(tmp_path):
    from SpiderPanel.candidates import load_candidate_expressions
    path = tmp_path / "regular.jsonl"
    write(path, [{"alpha_id": "a1", "expression": EXPRESSION}])
    with path.open("ab") as file:
        file.write(b'\n{"alpha_id":"a1","expression":"rank(\\ud800)"}\n'
                   b'{"alpha_id":"\\udfff","expression":"close"}\n'
                   b'{"alpha_id":"a2","expression":"volume"}')
    pipeline(tmp_path)
    runtime = PanelRuntime(tmp_path, day=DAY, clock=lambda: TS+10, progress_path=tmp_path / "progress.json",
                           candidate_paths=(path,))
    try:
        runtime.poll()
        assert runtime.snapshot()["review"][0]["expr"] == EXPRESSION
        assert load_candidate_expressions((path,)) == {"a1": EXPRESSION, "a2": "volume"}
    finally:
        runtime.close()


def test_appended_ledger_expression_invalidates_payload_after_poll_interval(tmp_path):
    now = [TS+10]
    path = tmp_path / "regular.jsonl"
    write(path, [{"alpha_id": "other", "expression": "close"}])
    pipeline(tmp_path)
    runtime = PanelRuntime(tmp_path, day=DAY, clock=lambda: now[0], progress_path=tmp_path / "progress.json",
                           candidate_paths=(path,))
    try:
        runtime.poll()
        key, _ = runtime.payload()
        assert runtime.snapshot()["review"][0]["expr"] == EXPRESSION[:120]
        with path.open("a", encoding="utf-8") as file:
            file.write("\n" + json.dumps({"alpha_id": "a1", "expression": EXPRESSION}))
        now[0] += 1
        runtime.poll()
        assert runtime.payload()[0] == key
        now[0] += rules.PROGRESS_POLL_SECONDS + 1
        runtime.poll()
        changed, _ = runtime.payload()
        assert changed != key and changed[:-1] == key[:-1]
        assert runtime.snapshot()["review"][0]["expr"] == EXPRESSION
        assert runtime.snapshot()["alphas"][0]["expr"] == EXPRESSION
        assert runtime.snapshot()["best"]["expr"] == EXPRESSION
        runtime.poll()
        assert runtime.payload()[0] == changed
    finally:
        runtime.close()


def test_explicit_candidate_paths_are_read_only(tmp_path):
    paths = tuple(tmp_path / "sources" / name for name in (
        "regular.jsonl", "super.jsonl"))
    write(paths[0], [{"alpha_id": "a1", "expression": EXPRESSION}])
    write(paths[1], [{"alpha_id": "a1", "expression": EXPRESSION + " + 1"}])
    originals = [path.read_bytes() for path in paths]
    pipeline(tmp_path)
    runtime = PanelRuntime(tmp_path, day=DAY, clock=lambda: TS+10, candidate_paths=paths)
    try:
        assert runtime.candidate_paths == paths
        runtime.poll()
        assert runtime.snapshot()["review"][0]["expr"] == EXPRESSION + " + 1"
        assert [path.read_bytes() for path in paths] == originals
        assert sorted(paths[0].parent.iterdir()) == list(paths)
    finally:
        runtime.close()


def test_demo_ignores_configured_candidate_paths(tmp_path):
    path = tmp_path / "sources/regular.jsonl"
    write(path, [{"alpha_id": "a1", "expression": EXPRESSION}])
    pipeline(tmp_path)
    runtime = PanelRuntime(tmp_path, day=DAY, mode="demo", clock=lambda: TS+10, candidate_paths=(path,))
    try:
        assert runtime.candidate_paths == ()
        runtime.poll()
        assert runtime.snapshot()["review"][0]["expr"] == EXPRESSION[:120]
    finally:
        runtime.close()
