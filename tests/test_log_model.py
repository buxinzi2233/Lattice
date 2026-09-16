from __future__ import annotations

from PySide6.QtTest import QSignalSpy

from tooldeck.gui.log_model import LogLineModel, parse_log_line


def test_log_line_parser_extracts_timestamp_level_and_message(qapp):
    assert parse_log_line("[12:11:02.082] INFO Runtime initialized") == (
        parse_log_line("12:11:02.082 INFO Runtime initialized")
    )
    entry = parse_log_line("[12:11:02.082] COMMAND $ exec ./start.sh")
    assert entry is not None
    assert entry.timestamp == "12:11:02.082"
    assert entry.level == "command"
    assert entry.message == "$ exec ./start.sh"

    warning = parse_log_line("Worker memory pressure crossed the configured threshold")
    assert warning is not None
    assert warning.level == "warn"


def test_log_line_model_appends_incrementally_and_bounds_history(qapp):
    model = LogLineModel(max_lines=3)
    rows_inserted = QSignalSpy(model.rowsInserted)
    model.append_text("[10:00:00] INFO one\n[10:00:01] WARN two\n")

    assert model.count == 2
    assert rows_inserted.count() == 1
    assert model.get(1) == {"logTime": "10:00:01", "logLevel": "warn", "logMessage": "two"}

    model.append_text("[10:00:02] ERROR three\n[10:00:03] INFO four\n")
    assert model.count == 3
    assert [model.get(row)["logMessage"] for row in range(3)] == ["two", "three", "four"]

    model.clear("DISPLAY BUFFER CLEARED")
    assert model.count == 1
    assert model.get(0)["logLevel"] == "command"
