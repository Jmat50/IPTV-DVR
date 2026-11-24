"""Unit tests for Windows scheduled-task helpers (no Task Scheduler required)."""

from __future__ import annotations

from pathlib import Path

from scheduler_win import build_cmd_wrapper_argument, task_launch_log_path, task_name_for_job


def test_task_name_for_job() -> None:
    assert task_name_for_job("abc-123") == "IPTVRecApp_abc-123"


def test_task_launch_log_path() -> None:
    assert task_launch_log_path(Path(r"C:\app\gui")) == Path(r"C:\app\gui\logs\task_launch.log")


def test_build_cmd_wrapper_argument_quotes_paths_with_spaces() -> None:
    arg = build_cmd_wrapper_argument(
        launcher=Path(r"C:\VIsual Studio\IPTV-DVR\gui\iptv-gui.exe"),
        argument="run-job --job-id deadbeef --scheduled-mode daily --scheduled-hour 3 --scheduled-minute 0",
        log_file=Path(r"C:\VIsual Studio\IPTV-DVR\gui\logs\task_launch.log"),
        job_id="deadbeef",
    )
    assert arg.startswith('/v:on /c "')
    assert arg.endswith('"')
    assert r'"C:\VIsual Studio\IPTV-DVR\gui\iptv-gui.exe"' in arg
    assert "run-job --job-id deadbeef" in arg
    assert r'"C:\VIsual Studio\IPTV-DVR\gui\logs\task_launch.log"' in arg
    assert "IPTVRecApp start" in arg
    assert "IPTVRecApp exit !IPTV_RC!" in arg
    assert "exit /b !IPTV_RC!" in arg
    assert "job=deadbeef" in arg
