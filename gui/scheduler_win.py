"""Create/update/remove Windows scheduled tasks for recording jobs."""

from __future__ import annotations

import re
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
WAKE_TIMERS_GUID = "BD3B718A-0680-4D9D-8AB2-E1D2B4AC806D"
PLAN_GUID_RE = re.compile(r"Power Scheme GUID:\s*([0-9a-fA-F\-]{36})", re.IGNORECASE)


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


def list_running_app_tasks() -> list[str]:
    ps = (
        "Get-ScheduledTask -ErrorAction SilentlyContinue | "
        "Where-Object { $_.TaskName -like 'IPTVRecApp_*' -and $_.State -eq 'Running' } | "
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


def _schedule_meta_args(job: Job) -> str:
    days = ",".join(d.strip().lower() for d in job.schedule.days if d.strip())
    base = (
        f" --scheduled-mode {job.schedule.mode}"
        f" --scheduled-hour {job.schedule.hour}"
        f" --scheduled-minute {job.schedule.minute}"
    )
    if days:
        return base + f" --scheduled-days {days}"
    return base


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
  -WakeToRun `
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
    verify = _run_ps(
        (
            "$ErrorActionPreference='Stop'; "
            f"$t=Get-ScheduledTask -TaskName {_ps_quote(name)}; "
            "if (-not $t.Settings.WakeToRun) { "
            "  throw 'WakeToRun is not enabled on the task settings.' "
            "}"
        )
    )
    if verify.returncode != 0:
        msg = (verify.stderr or verify.stdout or "").strip() or "could not verify WakeToRun"
        return False, msg
    return True, ""


def wake_readiness_warning() -> str:
    """
    Return a warning message if host wake-timer policy appears disabled.
    Empty string means no warning.
    """
    ac_val, dc_val = wake_timer_values()
    if ac_val is None and dc_val is None:
        return ""
    # 0 means disabled. 1/2 are enabled modes.
    if ac_val == 0 or dc_val == 0:
        return (
            "Windows 'Allow wake timers' appears disabled for the current power plan.\n"
            "Scheduled wake may not fire until this is enabled in Power Options."
        )
    return ""


def wake_timer_values() -> tuple[int | None, int | None]:
    """
    Returns (ac, dc) wake timer values from current power scheme.
    None means value could not be determined.
    """
    q = subprocess.run(
        ["powercfg.exe", "/q", "SCHEME_CURRENT", "SUB_SLEEP", WAKE_TIMERS_GUID],
        capture_output=True,
        text=True,
        check=False,
    )
    if q.returncode != 0:
        return None, None
    text = (q.stdout or "") + "\n" + (q.stderr or "")
    ac = re.search(r"Current AC Power Setting Index:\s*0x([0-9a-fA-F]+)", text)
    dc = re.search(r"Current DC Power Setting Index:\s*0x([0-9a-fA-F]+)", text)
    ac_val = int(ac.group(1), 16) if ac else None
    dc_val = int(dc.group(1), 16) if dc else None
    return ac_val, dc_val


def wake_timer_value_label(v: int | None) -> str:
    if v is None:
        return "unknown"
    if v == 0:
        return "disabled"
    if v == 1:
        return "enabled"
    if v == 2:
        return "important-only"
    return f"value={v}"


def _list_power_scheme_guids() -> list[str]:
    r = subprocess.run(
        ["powercfg.exe", "/l"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        return []
    guids: list[str] = []
    for line in (r.stdout or "").splitlines():
        m = PLAN_GUID_RE.search(line)
        if m:
            guids.append(m.group(1))
    # Keep order, remove duplicates.
    out: list[str] = []
    seen: set[str] = set()
    for g in guids:
        k = g.lower()
        if k not in seen:
            out.append(g)
            seen.add(k)
    return out


def enable_wake_timers() -> tuple[bool, str]:
    """
    Try to enable wake timers across available power plans (AC and DC).
    Returns (ok, message).
    """
    schemes = _list_power_scheme_guids()
    if not schemes:
        schemes = ["SCHEME_CURRENT"]

    errors: list[str] = []
    for scheme in schemes:
        cmds = [
            ["powercfg.exe", "/setacvalueindex", scheme, "SUB_SLEEP", WAKE_TIMERS_GUID, "1"],
            ["powercfg.exe", "/setdcvalueindex", scheme, "SUB_SLEEP", WAKE_TIMERS_GUID, "1"],
        ]
        for cmd in cmds:
            r = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if r.returncode != 0:
                err = (r.stderr or r.stdout or "").strip() or f"exit {r.returncode}"
                errors.append(f"{' '.join(cmd)} -> {err}")
    # Re-apply current scheme so Windows uses the updated setting right away.
    activate = subprocess.run(
        ["powercfg.exe", "/setactive", "SCHEME_CURRENT"],
        capture_output=True,
        text=True,
        check=False,
    )
    if activate.returncode != 0:
        err = (activate.stderr or activate.stdout or "").strip() or f"exit {activate.returncode}"
        errors.append(f"powercfg.exe /setactive SCHEME_CURRENT -> {err}")
    if errors:
        return False, "\n".join(errors)
    warn = wake_readiness_warning()
    if warn:
        return False, warn
    return True, "Wake timers enabled for all available power plans."


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
    running = set(list_running_app_tasks())
    for existing in list_app_tasks():
        if existing not in want:
            if existing in running:
                continue
            delete_task(existing)
    errors: list[str] = []
    for j in enabled:
        if task_name_for_job(j.id) in running:
            continue
        if frozen_main:
            arg = f"run-job --job-id {j.id}{_schedule_meta_args(j)}"
        else:
            if main_script is None:
                return False, "internal error: main_script required when not frozen"
            arg = f'"{main_script}" run-job --job-id {j.id}{_schedule_meta_args(j)}'
        ok, err = register_job_task(j, launcher=launcher, argument=arg, work_dir=work_dir)
        if not ok:
            errors.append(f"{j.name}: {err}")
    if errors:
        return False, "\n".join(errors)
    return True, ""
