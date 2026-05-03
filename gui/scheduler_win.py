"""Create/update/remove Windows scheduled tasks for recording jobs."""

from __future__ import annotations

import subprocess
from pathlib import Path

from config_store import Job

PS_DAY = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}


def task_name_for_job(job_id: str) -> str:
    # Task Scheduler name limits; UUID is fine.
    return f"IPTVRecApp_{job_id}"


def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _run_ps(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )


def delete_task(task_name: str) -> None:
    ps = f"Unregister-ScheduledTask -TaskName {_ps_quote(task_name)} -Confirm:$false -ErrorAction SilentlyContinue"
    _run_ps(ps)


def list_app_tasks() -> list[str]:
    ps = (
        "Get-ScheduledTask -ErrorAction SilentlyContinue | "
        "Where-Object { $_.TaskName -like 'IPTVRecApp_*' } | "
        "ForEach-Object { $_.TaskName }"
    )
    r = _run_ps(ps)
    if r.returncode != 0 or not r.stdout.strip():
        return []
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def _trigger_ps(job: Job) -> str:
    h, m = job.schedule.hour, job.schedule.minute
    if job.schedule.mode == "daily":
        return (
            f"$tr = New-ScheduledTaskTrigger -Daily "
            f"-At (Get-Date -Hour {h} -Minute {m} -Second 0)"
        )
    days = [d.strip().lower() for d in job.schedule.days if d.strip()]
    if not days:
        raise ValueError("weekly schedule needs at least one weekday")
    ps_days = ",".join(PS_DAY[d] for d in days)
    return (
        f"$tr = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 "
        f"-DaysOfWeek {ps_days} -At (Get-Date -Hour {h} -Minute {m} -Second 0)"
    )


def register_job_task(
    job: Job,
    *,
    launcher: Path,
    argument: str,
    work_dir: Path,
) -> tuple[bool, str]:
    """Create or replace one scheduled task. *argument* is the full task Arguments string (after the program)."""
    name = task_name_for_job(job.id)
    try:
        trig = _trigger_ps(job)
    except ValueError as e:
        return False, str(e)

    arg_ps = _ps_quote(argument)
    ps = f"""
$ErrorActionPreference = 'Stop'
{trig}
$st = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -ExecutionTimeLimit (New-TimeSpan -Hours 24)
$a = New-ScheduledTaskAction -Execute {_ps_quote(str(launcher))} `
  -Argument {arg_ps} `
  -WorkingDirectory {_ps_quote(str(work_dir))}
Register-ScheduledTask -TaskName {_ps_quote(name)} -Action $a -Trigger $tr -Settings $st -Force | Out-Null
""".strip()
    r = _run_ps(ps)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip() or f"exit {r.returncode}"
        return False, msg
    return True, ""


def sync_all_tasks(
    jobs: list[Job],
    *,
    launcher: Path,
    work_dir: Path,
    frozen_main: bool,
    main_script: Path | None = None,
) -> tuple[bool, str]:
    """
    Register tasks for every enabled job; remove IPTVRecApp_* tasks
    whose job id is no longer present (disabled or deleted).
    """
    enabled = [j for j in jobs if j.enabled]
    want = {task_name_for_job(j.id) for j in enabled}
    for existing in list_app_tasks():
        if existing not in want:
            delete_task(existing)
    errors: list[str] = []
    for j in enabled:
        if frozen_main:
            arg = f"run-job --job-id {j.id}"
        else:
            if main_script is None:
                return False, "internal error: main_script required when not frozen"
            arg = f'"{main_script}" run-job --job-id {j.id}'
        ok, err = register_job_task(j, launcher=launcher, argument=arg, work_dir=work_dir)
        if not ok:
            errors.append(f"{j.name}: {err}")
    if errors:
        return False, "\n".join(errors)
    return True, ""
