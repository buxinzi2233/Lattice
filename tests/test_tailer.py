from __future__ import annotations

from tooldeck.tailer import LogTailer


def test_incremental_read_and_carriage_return_folding(tmp_path):
    path = tmp_path / "app.log"
    path.write_bytes(b"first\nstep 1\rstep 2\rcomplete\npartial")
    tailer = LogTailer(path)
    assert tailer.read() == "first\ncomplete\n"
    assert tailer.read() == ""
    with path.open("ab") as handle:
        handle.write(b" line\n")
    assert tailer.read() == "partial line\n"


def test_truncation_resets_offset(tmp_path):
    path = tmp_path / "app.log"
    path.write_text("old content long\n", encoding="utf-8")
    tailer = LogTailer(path)
    assert tailer.read() == "old content long\n"
    path.write_text("new\n", encoding="utf-8")
    assert tailer.read() == "new\n"


def test_invalid_utf8_is_replaced(tmp_path):
    path = tmp_path / "app.log"
    path.write_bytes(b"bad: \xff\n")
    assert "\ufffd" in LogTailer(path).read()
