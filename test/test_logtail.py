from datetime import date

from SpiderPanel import logtail, rules


def test_byte_offsets_partial_lines_and_poll_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(rules, "MAX_LINES_PER_POLL", 1)
    path = tmp_path / "log.jsonl"
    path.write_bytes('中文\n半'.encode())
    tail = logtail.Tail(path)
    assert list(tail.read_lines()) == ['中文\n'.encode()]
    assert tail.offset == 7
    assert list(tail.read_lines()) == []
    assert not tail.at_eof and tail.caught_up
    with path.open("ab") as file:
        file.write('行\n最后\n'.encode())
    assert list(tail.read_lines()) == ['半行\n'.encode()]
    assert list(tail.read_lines()) == ['最后\n'.encode()]
    assert tail.at_eof


def test_tail_truncation_and_missing_file(tmp_path):
    path = tmp_path / "missing.jsonl"
    tail = logtail.Tail(path)
    assert list(tail.read_lines()) == [] and tail.at_eof
    path.write_bytes(b"first\n")
    assert list(tail.read_lines()) == [b"first\n"]
    path.write_bytes(b"new\n")
    assert list(tail.read_lines()) == [b"new\n"]


def test_oversized_bad_line_is_skipped_without_losing_next_line(tmp_path):
    path = tmp_path / "oversized.jsonl"
    path.write_bytes(b"x" * rules.MAX_LINE_BYTES + b"\nok\n")
    tail = logtail.Tail(path)
    assert list(tail.read_lines()) == [None, b"ok\n"]
    assert tail.at_eof


def test_line_at_byte_budget_is_read_intact(tmp_path):
    path = tmp_path / "boundary.jsonl"
    raw = b"x" * (rules.MAX_LINE_BYTES - 1) + b"\n"
    path.write_bytes(raw)
    tail = logtail.Tail(path)
    assert list(tail.read_lines()) == [raw]
    assert tail.at_eof


def test_once_snapshot_ignores_content_appended_after_start(tmp_path):
    path = tmp_path / "snapshot.jsonl"
    path.write_bytes(b"old\n")
    tail = logtail.Tail(path, snapshot=True)
    with path.open("ab") as file:
        file.write(b"new\n")
    assert list(tail.read_lines()) == [b"old\n"]
    assert tail.caught_up and not tail.at_eof


def test_retention_only_matching_old_files_are_deleted(tmp_path):
    for name in ("2026-01-01.jsonl", "2026-01-03.jsonl", "2026-01-10.jsonl", "2026-01-01.txt",
                 "prefix-2026-01-01.jsonl", "2026-99-99.jsonl"):
        (tmp_path / name).write_text("keep or expire")
    (tmp_path / "2025-01-01.jsonl").mkdir()
    assert logtail.cleanup_logs(tmp_path, date(2026, 1, 10)) == 1
    assert not (tmp_path / "2026-01-01.jsonl").exists()
    assert len(list(tmp_path.iterdir())) == 6
