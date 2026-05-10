"""
Tkinter GUI for M3U sources and recurring Windows scheduled recordings.
Run from repo root:  python gui\\main.py
Headless (Task Scheduler):  python gui\\main.py run-job --job-id <uuid>
Frozen exe:                 iptv-gui.exe run-job --job-id <uuid>
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import threading
import traceback
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from config_store import (
    AppConfig,
    CommercialRemovalSettings,
    Job,
    Source,
    job_by_id,
    load_config,
    save_config,
    source_by_id,
)
from duration_parse import parse_duration
from job_runner import run_job
from m3u_load import load_m3u
from paths import (
    ffmpeg_exe,
    ffprobe_exe,
    is_frozen,
    log_dir,
    project_root,
    resolve_mythcommflag_exe,
)
from recorder import build_ffmpeg_argv, run_ffmpeg
from scheduler_win import sync_all_tasks


def _python_for_tasks() -> Path:
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        w = exe.with_name("pythonw.exe")
        if w.is_file():
            return w
    return exe


def _main_script_path() -> Path:
    return Path(__file__).resolve()


def _error_log_path() -> Path:
    p = log_dir() / "error.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch(exist_ok=True)
    return p


def _append_error_log(text: str) -> None:
    p = _error_log_path()
    with open(p, "a", encoding="utf-8") as fp:
        fp.write(text)


def _log_exception(context: str, exc_type: type[BaseException], exc_value: BaseException, exc_tb) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    body = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    _append_error_log(f"\n---\n[{ts}] {context}\n{body}")


def _install_exception_hooks() -> None:
    def _sys_hook(exc_type: type[BaseException], exc_value: BaseException, exc_tb) -> None:
        _log_exception("Unhandled exception (main thread)", exc_type, exc_value, exc_tb)
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _sys_hook

    if hasattr(threading, "excepthook"):
        def _thread_hook(args: threading.ExceptHookArgs) -> None:
            tname = args.thread.name if args.thread else "unknown"
            _log_exception(f"Unhandled exception (thread: {tname})", args.exc_type, args.exc_value, args.exc_traceback)

        threading.excepthook = _thread_hook


def _run_job_cli() -> None:
    p = argparse.ArgumentParser(prog="iptv-gui")
    p.add_argument("run_job", nargs="?", help=argparse.SUPPRESS)
    p.add_argument("--job-id", required=True)
    args = p.parse_args()
    raise SystemExit(run_job(args.job_id))


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("IPTV Recorder (local)")
        self.cfg: AppConfig = load_config()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.report_callback_exception = self.on_tk_callback_exception

        menubar = tk.Menu(self)
        fm = tk.Menu(menubar, tearoff=0)
        fm.add_command(label="Save config", command=self.on_save)
        fm.add_command(label="Sync Windows tasks", command=self.on_sync)
        fm.add_command(label="Error Log", command=self.on_open_error_log)
        fm.add_separator()
        fm.add_command(label="Quit", command=self.destroy)
        menubar.add_cascade(label="File", menu=fm)
        hm = tk.Menu(menubar, tearoff=0)
        hm.add_command(label="FFmpeg status", command=self.on_ffmpeg_status)
        menubar.add_cascade(label="Help", menu=hm)
        self.config(menu=menubar)

        outer = ttk.Frame(self, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)

        # --- Sources ---
        sf = ttk.LabelFrame(outer, text="M3U sources", padding=6)
        sf.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        sf.grid_columnconfigure(0, weight=1)
        sf.grid_rowconfigure(0, weight=1)
        cols = ("name", "path")
        self.src_tree = ttk.Treeview(sf, columns=cols, show="headings", height=6, selectmode="browse")
        self.src_tree.heading("name", text="Name")
        self.src_tree.heading("path", text="File or URL")
        self.src_tree.column("name", width=160)
        self.src_tree.column("path", width=640)
        ys = ttk.Scrollbar(sf, orient=tk.VERTICAL, command=self.src_tree.yview)
        self.src_tree.configure(yscrollcommand=ys.set)
        self.src_tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        sb = ttk.Frame(sf)
        sb.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(sb, text="Add source", command=self.add_source).pack(side=tk.LEFT, padx=2)
        ttk.Button(sb, text="Edit", command=self.edit_source).pack(side=tk.LEFT, padx=2)
        ttk.Button(sb, text="Remove", command=self.remove_source).pack(side=tk.LEFT, padx=2)

        # --- Jobs ---
        jf = ttk.LabelFrame(outer, text="Recording jobs (recurring)", padding=6)
        jf.pack(fill=tk.BOTH, expand=True)
        jf.grid_columnconfigure(0, weight=1)
        jf.grid_rowconfigure(0, weight=1)
        jcols = ("name", "channel", "schedule", "duration", "output", "en")
        self.job_tree = ttk.Treeview(jf, columns=jcols, show="headings", height=8, selectmode="browse")
        self.job_tree.heading("name", text="Name")
        self.job_tree.heading("channel", text="Channel")
        self.job_tree.heading("schedule", text="Schedule")
        self.job_tree.heading("duration", text="Duration")
        self.job_tree.heading("output", text="Output folder")
        self.job_tree.heading("en", text="On")
        for c, w in zip(jcols, (120, 140, 180, 70, 260, 40)):
            self.job_tree.column(c, width=w)
        yj = ttk.Scrollbar(jf, orient=tk.VERTICAL, command=self.job_tree.yview)
        self.job_tree.configure(yscrollcommand=yj.set)
        self.job_tree.grid(row=0, column=0, sticky="nsew")
        yj.grid(row=0, column=1, sticky="ns")
        jb = ttk.Frame(jf)
        jb.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        jb_top = ttk.Frame(jb)
        jb_top.pack(anchor=tk.W)
        jb_bottom = ttk.Frame(jb)
        jb_bottom.pack(anchor=tk.W, pady=(4, 0))
        ttk.Button(jb_top, text="Add job", command=self.add_job).pack(side=tk.LEFT, padx=2)
        ttk.Button(jb_top, text="Edit", command=self.edit_job).pack(side=tk.LEFT, padx=2)
        ttk.Button(jb_top, text="Remove", command=self.remove_job).pack(side=tk.LEFT, padx=2)
        ttk.Button(jb_top, text="Run selected job now", command=self.run_selected_job_now).pack(side=tk.LEFT, padx=8)
        ttk.Button(jb_bottom, text="Test 15s capture", command=self.test_capture).pack(side=tk.LEFT, padx=2)
        ttk.Button(jb_bottom, text="Save config", command=self.on_save).pack(side=tk.LEFT, padx=2)
        ttk.Button(jb_bottom, text="Sync Windows tasks", command=self.on_sync).pack(side=tk.LEFT, padx=2)

        self.refresh_lists()
        self._fit_main_window_to_content()
        self.after(100, self._maybe_prompt_install_dependencies)

    def _fit_main_window_to_content(self) -> None:
        self.update_idletasks()
        pad = 24
        req_w = self.winfo_reqwidth() + pad
        req_h = self.winfo_reqheight() + pad
        max_w = int(self.winfo_screenwidth() * 0.95)
        max_h = int(self.winfo_screenheight() * 0.90)
        target_w = min(req_w, max_w)
        target_h = min(req_h, max_h)
        self.geometry(f"{target_w}x{target_h}")
        self.minsize(min(req_w, max_w), min(req_h, max_h))

    def refresh_lists(self) -> None:
        for i in self.src_tree.get_children():
            self.src_tree.delete(i)
        for s in self.cfg.sources:
            self.src_tree.insert("", tk.END, iid=s.id, values=(s.name, s.path_or_url))
        for i in self.job_tree.get_children():
            self.job_tree.delete(i)
        for j in self.cfg.jobs:
            sch = self._schedule_label(j)
            self.job_tree.insert(
                "",
                tk.END,
                iid=j.id,
                values=(j.name, j.channel, sch, j.duration, j.output_dir, "yes" if j.enabled else "no"),
            )

    @staticmethod
    def _schedule_label(j: Job) -> str:
        t = f"{j.schedule.hour:02d}:{j.schedule.minute:02d}"
        if j.schedule.mode == "daily":
            return f"daily @ {t}"
        days = ",".join(j.schedule.days) or "?"
        return f"weekly {days} @ {t}"

    def on_save(self) -> None:
        if self.persist_and_sync(
            parent=self,
            show_success=True,
            success_title="Saved",
            success_message="Configuration written and Windows tasks synced.",
        ):
            self.refresh_lists()

    def on_sync(self) -> None:
        self.persist_and_sync(
            parent=self,
            show_success=True,
            success_title="Tasks",
            success_message="Windows scheduled tasks are in sync.",
        )

    def persist_and_sync(
        self,
        *,
        parent: tk.Misc | None = None,
        show_success: bool = False,
        success_title: str = "Saved",
        success_message: str = "Configuration written to config.json",
    ) -> bool:
        save_config(self.cfg)
        frozen = is_frozen()
        launcher = Path(sys.executable) if frozen else _python_for_tasks()
        script = None if frozen else _main_script_path()
        ok, err = sync_all_tasks(
            self.cfg.jobs,
            launcher=launcher,
            work_dir=project_root(),
            frozen_main=frozen,
            main_script=script,
        )
        parent_win = parent if parent is not None else self
        if not ok:
            messagebox.showerror("Task error", err, parent=parent_win)
            return False
        if show_success:
            messagebox.showinfo(success_title, success_message, parent=parent_win)
        return True

    def on_close(self) -> None:
        if not self.persist_and_sync(parent=self):
            leave_anyway = messagebox.askyesno(
                "Exit with unsynced tasks?",
                "Task sync failed while closing.\n\nExit anyway?\n"
                "If you exit now, scheduled recordings may not run as expected.",
                parent=self,
            )
            if not leave_anyway:
                return
        self.destroy()

    def on_ffmpeg_status(self) -> None:
        ff = ffmpeg_exe()
        fp = ffprobe_exe()
        if ff.is_file() and fp.is_file():
            messagebox.showinfo("FFmpeg", f"Embedded binaries found:\n{ff}\n{fp}")
        else:
            messagebox.showwarning(
                "FFmpeg missing",
                f"Missing one or more binaries:\n{ff}\n{fp}\n\n"
                "Run scripts\\download_ffmpeg.ps1 from the repo root.",
            )

    def on_open_error_log(self) -> None:
        p = _error_log_path()
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["notepad.exe", str(p)])
            else:
                subprocess.Popen([str(p)])
        except Exception as e:
            messagebox.showerror("Error Log", f"Could not open error log:\n{e}", parent=self)

    def on_tk_callback_exception(self, exc_type, exc_value, exc_tb) -> None:
        _log_exception("Unhandled exception (Tk callback)", exc_type, exc_value, exc_tb)
        messagebox.showerror(
            "Unexpected Error",
            f"An unexpected error occurred.\n\nDetails were written to:\n{_error_log_path()}",
            parent=self,
        )

    def _maybe_prompt_install_dependencies(self) -> None:
        self._maybe_prompt_install_ffmpeg()
        self._maybe_prompt_install_postprocess_tools()

    def _has_ffmpeg_bundle(self) -> bool:
        return ffmpeg_exe().is_file() and ffprobe_exe().is_file()

    def _maybe_prompt_install_ffmpeg(self) -> None:
        if self._has_ffmpeg_bundle():
            return
        yes = messagebox.askyesno(
            "FFmpeg missing",
            "FFmpeg and FFprobe are required for recording and post-processing.\n\n"
            "Would you like to download and install it now using PowerShell?",
            parent=self,
        )
        if not yes:
            return
        messagebox.showinfo(
            "FFmpeg install",
            "Starting FFmpeg download/install now.\n"
            "This can take a minute.",
            parent=self,
        )

        def worker() -> None:
            ok, msg = self._install_ffmpeg_via_powershell()
            self.after(0, lambda: self._on_ffmpeg_install_done(ok, msg))

        threading.Thread(target=worker, daemon=True).start()

    def _maybe_prompt_install_postprocess_tools(self) -> None:
        if resolve_mythcommflag_exe() is not None:
            return
        yes = messagebox.askyesno(
            "mythcommflag missing",
            "Commercial removal now uses MythTV mythcommflag.\n\n"
            "Would you like to install mythcommflag now?",
            parent=self,
        )
        if not yes:
            return
        tool_path = filedialog.askopenfilename(
            title="Select mythcommflag executable or ZIP",
            filetypes=[
                ("Executable or ZIP", "*.exe *.zip"),
                ("Executable", "*.exe"),
                ("ZIP", "*.zip"),
                ("All files", "*.*"),
            ],
            parent=self,
        )
        if not tool_path:
            messagebox.showwarning(
                "mythcommflag not installed",
                "No mythcommflag executable/ZIP was selected.\n\n"
                "Commercial removal will remain unavailable until mythcommflag is installed.",
                parent=self,
            )
            return

        def worker() -> None:
            ok, msg = self._install_mythcommflag_via_powershell(Path(tool_path))
            details = [] if ok else [msg]
            self.after(0, lambda: self._on_postprocess_install_done(ok, details))

        threading.Thread(target=worker, daemon=True).start()

    def _install_ffmpeg_via_powershell(self) -> tuple[bool, str]:
        root = project_root()
        script = root / "scripts" / "download_ffmpeg.ps1"
        if script.is_file():
            cmd = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=str(root))
        else:
            dest = str((root / "ffmpeg").resolve()).replace("'", "''")
            ps_inline = (
                "$ErrorActionPreference='Stop'; "
                f"$dest='{dest}'; "
                "New-Item -ItemType Directory -Force -Path $dest | Out-Null; "
                "$zipUrl='https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip'; "
                "$work=Join-Path $env:TEMP ('ffmpeg_unpack_' + [Guid]::NewGuid().ToString()); "
                "New-Item -ItemType Directory -Force -Path $work | Out-Null; "
                "$zip=Join-Path $work 'ffmpeg.zip'; "
                "Invoke-WebRequest -Uri $zipUrl -OutFile $zip; "
                "Expand-Archive -Path $zip -DestinationPath $work -Force; "
                "$inner=Get-ChildItem -Path $work -Directory | Where-Object { $_.Name -like 'ffmpeg-*' } | Select-Object -First 1; "
                "if (-not $inner) { throw 'Unexpected zip layout.' }; "
                "$ffmpegBin=Join-Path $inner.FullName 'bin\\ffmpeg.exe'; "
                "$ffprobeBin=Join-Path $inner.FullName 'bin\\ffprobe.exe'; "
                "if (-not (Test-Path $ffmpegBin)) { throw 'ffmpeg.exe not found in downloaded archive.' }; "
                "if (-not (Test-Path $ffprobeBin)) { throw 'ffprobe.exe not found in downloaded archive.' }; "
                "Copy-Item -Force $ffmpegBin (Join-Path $dest 'ffmpeg.exe'); "
                "Copy-Item -Force $ffprobeBin (Join-Path $dest 'ffprobe.exe'); "
                "Remove-Item $work -Recurse -Force;"
            )
            cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_inline]
            r = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if r.returncode == 0 and self._has_ffmpeg_bundle():
            return True, (r.stdout or "").strip()
        msg = (r.stderr or r.stdout or "").strip()
        return False, msg or f"Installer exited with code {r.returncode}."

    def _on_ffmpeg_install_done(self, ok: bool, msg: str) -> None:
        if ok:
            messagebox.showinfo(
                "FFmpeg install",
                f"FFmpeg installed successfully:\n{ffmpeg_exe()}\n{ffprobe_exe()}",
                parent=self,
            )
        else:
            messagebox.showerror(
                "FFmpeg install failed",
                "Automatic install failed.\n\n"
                "You can run scripts\\download_ffmpeg.ps1 manually.\n\n"
                f"Details:\n{msg}",
                parent=self,
            )

    def _install_mythcommflag_via_powershell(self, selected_path: Path) -> tuple[bool, str]:
        root = project_root()
        script = root / "scripts" / "setup_mythcommflag.ps1"
        if not script.is_file():
            return False, f"missing installer script: {script}"
        if not selected_path.is_file():
            return False, f"selected path does not exist: {selected_path}"
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ]
        if selected_path.suffix.lower() == ".zip":
            cmd.extend(["-ZipPath", str(selected_path)])
        else:
            cmd.extend(["-ExePath", str(selected_path)])
        r = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=str(root))
        if r.returncode == 0 and resolve_mythcommflag_exe() is not None:
            return True, (r.stdout or "").strip()
        msg = (r.stderr or r.stdout or "").strip()
        return False, msg or f"installer exited with code {r.returncode}"

    def _on_postprocess_install_done(self, ok: bool, details: list[str]) -> None:
        if ok:
            messagebox.showinfo("Tools install", "mythcommflag is ready.", parent=self)
            return
        detail_text = "\n".join(details) if details else "Unknown installation error."
        messagebox.showerror(
            "Tools install failed",
            "mythcommflag installation failed.\n\n"
            f"{detail_text}",
            parent=self,
        )

    def selected_source(self) -> Source | None:
        sel = self.src_tree.selection()
        if not sel:
            return None
        return next((s for s in self.cfg.sources if s.id == sel[0]), None)

    def selected_job(self) -> Job | None:
        sel = self.job_tree.selection()
        if not sel:
            return None
        return job_by_id(self.cfg, sel[0])

    def add_source(self) -> None:
        editor = SourceEditor(self, title="Add source")
        self.wait_window(editor)
        if not editor.result:
            return
        name, source = editor.result
        self.cfg.sources.append(Source.new(name, source))
        self.refresh_lists()

    def edit_source(self) -> None:
        s = self.selected_source()
        if not s:
            messagebox.showinfo("Edit", "Select a source first.")
            return
        editor = SourceEditor(self, title="Edit source", name=s.name, source=s.path_or_url)
        self.wait_window(editor)
        if not editor.result:
            return
        s.name, s.path_or_url = editor.result
        self.refresh_lists()

    def remove_source(self) -> None:
        s = self.selected_source()
        if not s:
            return
        if not messagebox.askyesno("Remove", f"Remove source {s.name!r}?"):
            return
        self.cfg.sources = [x for x in self.cfg.sources if x.id != s.id]
        self.cfg.jobs = [j for j in self.cfg.jobs if j.source_id != s.id]
        if self.persist_and_sync(parent=self):
            self.refresh_lists()

    def add_job(self) -> None:
        if not self.cfg.sources:
            messagebox.showwarning("Jobs", "Add at least one M3U source first.")
            return
        JobEditor(self, self.cfg, None, on_done=self.refresh_lists)

    def edit_job(self) -> None:
        j = self.selected_job()
        if not j:
            messagebox.showinfo("Edit", "Select a job first.")
            return
        JobEditor(self, self.cfg, j, on_done=self.refresh_lists)

    def remove_job(self) -> None:
        j = self.selected_job()
        if not j:
            return
        if not messagebox.askyesno("Remove", f"Remove job {j.name!r}?"):
            return
        self.cfg.jobs = [x for x in self.cfg.jobs if x.id != j.id]
        if self.persist_and_sync(parent=self):
            self.refresh_lists()

    def run_selected_job_now(self) -> None:
        j = self.selected_job()
        if not j:
            messagebox.showinfo("Run now", "Select a job first.")
            return
        if not messagebox.askyesno("Run now", f"Start job now?\n\n{j.name}"):
            return

        try:
            self._launch_run_job_detached(j.id)
        except Exception as e:
            messagebox.showerror("Run now", f"Could not start job in detached mode:\n{e}")
            return
        messagebox.showinfo(
            "Run now",
            "Job started in independent background process.\n"
            "It will continue even if you close the GUI.\n\n"
            "Check logs in gui\\logs\\job_<id>.log while it runs.",
        )

    def _launch_run_job_detached(self, job_id: str) -> None:
        root = project_root()
        frozen = is_frozen()
        if frozen:
            cmd = [str(Path(sys.executable)), "run-job", "--job-id", job_id]
        else:
            cmd = [str(_python_for_tasks()), str(_main_script_path()), "run-job", "--job-id", job_id]

        kwargs: dict = {
            "cwd": str(root),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        env = dict(os.environ)
        if frozen:
            # For PyInstaller one-file builds, force a fresh child runtime
            # environment so the parent can clean up its own _MEI temp dir.
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
            env.pop("_MEIPASS2", None)
        kwargs["env"] = env
        if sys.platform == "win32":
            create_new_process_group = 0x00000200
            detached_process = 0x00000008
            create_breakaway_from_job = 0x01000000
            kwargs["creationflags"] = (
                create_new_process_group | detached_process | create_breakaway_from_job
            )
        else:
            kwargs["start_new_session"] = True
        try:
            subprocess.Popen(cmd, **kwargs)
        except OSError:
            # Fallback if breakaway is blocked by local policy.
            if sys.platform == "win32":
                kwargs["creationflags"] = create_new_process_group | detached_process
                subprocess.Popen(cmd, **kwargs)
            else:
                raise

    def _on_manual_run_done(self, name: str, code: int) -> None:
        if code == 0:
            messagebox.showinfo("Run now", f"Job finished successfully:\n{name}")
        else:
            messagebox.showerror(
                "Run now",
                f"Job finished with exit code {code}:\n{name}\n"
                "Check gui\\logs\\job_<id>.log for details.",
            )

    def test_capture(self) -> None:
        j = self.selected_job()
        if not j:
            messagebox.showinfo("Test", "Select a job to test (uses its channel and source).")
            return
        src = source_by_id(self.cfg, j.source_id)
        if not src:
            messagebox.showerror("Test", "Source missing.")
            return
        try:
            from m3u_load import find_channel

            ch = find_channel(load_m3u(src.path_or_url), j.channel)
        except Exception as e:
            messagebox.showerror("Test", str(e))
            return
        if not ffmpeg_exe().is_file():
            messagebox.showerror("FFmpeg", "Run scripts\\download_ffmpeg.ps1 first.")
            return
        out = Path(tempfile.gettempdir()) / f"iptv_test_{j.id[:8]}.ts"
        ua = j.user_agent or ch.user_agent
        ref = j.referer or ch.referer
        try:
            argv = build_ffmpeg_argv(
                stream_url=ch.url,
                output_path=out,
                duration_text="15s",
                user_agent=ua,
                referer=ref,
            )
        except Exception as e:
            messagebox.showerror("Test", str(e))
            return
        self.config(cursor="watch")
        self.update_idletasks()
        code = run_ffmpeg(argv, log_file=None)
        self.config(cursor="")
        if code == 0:
            messagebox.showinfo("Test", f"Saved 15s sample to:\n{out}")
        else:
            messagebox.showerror("Test", f"ffmpeg failed (code {code})")


class JobEditor(tk.Toplevel):
    def __init__(self, master: App, cfg: AppConfig, job: Job | None, *, on_done) -> None:
        super().__init__(master)
        self.cfg = cfg
        self._on_done = on_done
        self.job = job
        self.title("Job" if job else "New job")
        f = ttk.Frame(self, padding=10)
        f.pack(fill=tk.BOTH, expand=True)

        ttk.Label(f, text="Name").grid(row=0, column=0, sticky=tk.W)
        self.name_v = tk.StringVar(value=job.name if job else "")
        ttk.Entry(f, textvariable=self.name_v, width=44).grid(row=0, column=1, sticky=tk.W)

        ttk.Label(f, text="M3U source").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.src_v = tk.StringVar()
        src_ids = [s.id for s in cfg.sources]
        self.src_combo = ttk.Combobox(f, textvariable=self.src_v, values=[f"{s.name} ({s.id[:8]}…)" for s in cfg.sources], width=42, state="readonly")
        if job:
            for s in cfg.sources:
                if s.id == job.source_id:
                    self.src_v.set(f"{s.name} ({s.id[:8]}…)")
                    break
        elif cfg.sources:
            self.src_v.set(f"{cfg.sources[0].name} ({cfg.sources[0].id[:8]}…)")
        self.src_combo.grid(row=1, column=1, sticky=tk.W)

        ttk.Label(f, text="Channel").grid(row=2, column=0, sticky=tk.W)
        chf = ttk.Frame(f)
        chf.grid(row=2, column=1, sticky=tk.W)
        self.ch_v = tk.StringVar(value=job.channel if job else "")
        ttk.Entry(chf, textvariable=self.ch_v, width=32).pack(side=tk.LEFT)
        ttk.Button(chf, text="Load channels…", command=self.load_channels).pack(side=tk.LEFT, padx=6)

        ttk.Label(f, text="Duration").grid(row=3, column=0, sticky=tk.W)
        self.dur_v = tk.StringVar(value=job.duration if job else "90m")
        ttk.Entry(f, textvariable=self.dur_v, width=44).grid(row=3, column=1, sticky=tk.W)

        ttk.Label(f, text="Output folder").grid(row=4, column=0, sticky=tk.W)
        of = ttk.Frame(f)
        of.grid(row=4, column=1, sticky=tk.W)
        self.out_v = tk.StringVar(value=job.output_dir if job else str(Path.home() / "Videos" / "IPTV"))
        ttk.Entry(of, textvariable=self.out_v, width=34).pack(side=tk.LEFT)
        ttk.Button(of, text="Browse…", command=self.browse_out).pack(side=tk.LEFT, padx=4)

        ttk.Label(f, text="Filename pattern").grid(row=5, column=0, sticky=tk.W)
        self.pat_v = tk.StringVar(value=job.filename_pattern if job else "{date}_{channel}.ts")
        ttk.Entry(f, textvariable=self.pat_v, width=44).grid(row=5, column=1, sticky=tk.W)
        ttk.Label(f, text="{date} {time} {channel}", font=("TkDefaultFont", 8)).grid(row=6, column=1, sticky=tk.W)

        ttk.Label(f, text="Schedule").grid(row=7, column=0, sticky=tk.NW, pady=6)
        sf = ttk.Frame(f)
        sf.grid(row=7, column=1, sticky=tk.W)
        mode = job.schedule.mode if job else "daily"
        self.mode_v = tk.StringVar(value=mode)
        ttk.Radiobutton(sf, text="Daily", variable=self.mode_v, value="daily").pack(anchor=tk.W)
        ttk.Radiobutton(sf, text="Weekly (pick days)", variable=self.mode_v, value="weekly").pack(anchor=tk.W)
        days_fr = ttk.Frame(sf)
        days_fr.pack(anchor=tk.W, pady=4)
        self.day_vars: dict[str, tk.IntVar] = {}
        row1 = ttk.Frame(days_fr)
        row1.pack(anchor=tk.W)
        for i, d in enumerate(["mon", "tue", "wed", "thu"]):
            v = tk.IntVar(value=1 if job and d in job.schedule.days else 0)
            self.day_vars[d] = v
            ttk.Checkbutton(row1, text=d, variable=v, width=5).grid(row=0, column=i, padx=2)
        row2 = ttk.Frame(days_fr)
        row2.pack(anchor=tk.W)
        for i, d in enumerate(["fri", "sat", "sun"]):
            v = tk.IntVar(value=1 if job and d in job.schedule.days else 0)
            self.day_vars[d] = v
            ttk.Checkbutton(row2, text=d, variable=v, width=5).grid(row=0, column=i, padx=2)

        tf = ttk.Frame(sf)
        tf.pack(anchor=tk.W, pady=4)
        ttk.Label(tf, text="Time (24h)").pack(side=tk.LEFT)
        h = job.schedule.hour if job else 20
        m = job.schedule.minute if job else 0
        self.hour_v = tk.Spinbox(tf, from_=0, to=23, width=4)
        self.hour_v.delete(0, tk.END)
        self.hour_v.insert(0, f"{h:02d}")
        self.hour_v.pack(side=tk.LEFT, padx=4)
        ttk.Label(tf, text=":").pack(side=tk.LEFT)
        self.min_v = tk.Spinbox(tf, from_=0, to=59, width=4)
        self.min_v.delete(0, tk.END)
        self.min_v.insert(0, f"{m:02d}")
        self.min_v.pack(side=tk.LEFT, padx=4)

        en_v = tk.BooleanVar(value=job.enabled if job else True)
        self.en_v = en_v
        ttk.Checkbutton(f, text="Enabled", variable=en_v).grid(row=8, column=1, sticky=tk.W, pady=2)

        fmt_fr = ttk.Frame(f)
        fmt_fr.grid(row=9, column=1, sticky=tk.W, pady=2)
        ttk.Label(fmt_fr, text="Output format").pack(side=tk.LEFT)
        default_fmt = job.output_format if job else "ts"
        self.output_fmt_v = tk.StringVar(value=default_fmt if default_fmt in ("ts", "mp4", "mkv", "mov") else "ts")
        ttk.Combobox(
            fmt_fr,
            textvariable=self.output_fmt_v,
            values=["ts", "mp4", "mkv", "mov"],
            width=8,
            state="readonly",
        ).pack(side=tk.LEFT, padx=6)

        self.remove_commercials_v = tk.BooleanVar(value=job.remove_commercials_after_complete if job else False)
        ttk.Checkbutton(
            f,
            text="Remove Commercials after Complete",
            variable=self.remove_commercials_v,
        ).grid(row=10, column=1, sticky=tk.W, pady=2)

        settings = job.commercial_settings if (job and hasattr(job, "commercial_settings")) else CommercialRemovalSettings()
        hybrid_fr = ttk.LabelFrame(f, text="Commercial Removal Strategy", padding=6)
        hybrid_fr.grid(row=11, column=1, sticky=tk.W, pady=4)

        self.strategy_v = tk.StringVar(value=settings.strategy)
        ttk.Label(hybrid_fr, text="Mode").grid(row=0, column=0, sticky=tk.W)
        ttk.Combobox(
            hybrid_fr,
            textvariable=self.strategy_v,
            values=["myth_only", "legacy_only", "hybrid"],
            width=18,
            state="readonly",
        ).grid(row=0, column=1, sticky=tk.W, padx=6)

        self.enable_myth_v = tk.BooleanVar(value=settings.enable_myth)
        self.enable_legacy_v = tk.BooleanVar(value=settings.enable_legacy)
        self.enable_ffmpeg_signals_v = tk.BooleanVar(value=settings.enable_ffmpeg_signals)
        ttk.Checkbutton(hybrid_fr, text="Enable Myth", variable=self.enable_myth_v).grid(row=1, column=0, sticky=tk.W)
        ttk.Checkbutton(hybrid_fr, text="Enable Legacy", variable=self.enable_legacy_v).grid(row=1, column=1, sticky=tk.W)
        ttk.Checkbutton(hybrid_fr, text="Enable FFmpeg Signals", variable=self.enable_ffmpeg_signals_v).grid(
            row=1,
            column=2,
            sticky=tk.W,
            padx=(8, 0),
        )

        self.weight_myth_v = tk.StringVar(value=f"{settings.weight_myth:.2f}")
        self.weight_legacy_v = tk.StringVar(value=f"{settings.weight_legacy:.2f}")
        self.weight_ffmpeg_v = tk.StringVar(value=f"{settings.weight_ffmpeg_signals:.2f}")
        ttk.Label(hybrid_fr, text="Weight Myth").grid(row=2, column=0, sticky=tk.W)
        ttk.Entry(hybrid_fr, textvariable=self.weight_myth_v, width=6).grid(row=2, column=1, sticky=tk.W)
        ttk.Label(hybrid_fr, text="Legacy").grid(row=2, column=2, sticky=tk.W, padx=(8, 0))
        ttk.Entry(hybrid_fr, textvariable=self.weight_legacy_v, width=6).grid(row=2, column=3, sticky=tk.W)
        ttk.Label(hybrid_fr, text="Signals").grid(row=2, column=4, sticky=tk.W, padx=(8, 0))
        ttk.Entry(hybrid_fr, textvariable=self.weight_ffmpeg_v, width=6).grid(row=2, column=5, sticky=tk.W)

        self.confidence_threshold_v = tk.StringVar(value=f"{settings.confidence_threshold:.2f}")
        self.max_ratio_v = tk.StringVar(value=f"{settings.max_commercial_ratio:.2f}")
        self.min_keep_v = tk.StringVar(value=f"{settings.min_keep_segment_seconds:.1f}")
        ttk.Label(hybrid_fr, text="Confidence >= ").grid(row=3, column=0, sticky=tk.W)
        ttk.Entry(hybrid_fr, textvariable=self.confidence_threshold_v, width=6).grid(row=3, column=1, sticky=tk.W)
        ttk.Label(hybrid_fr, text="Max removed ratio").grid(row=3, column=2, sticky=tk.W, padx=(8, 0))
        ttk.Entry(hybrid_fr, textvariable=self.max_ratio_v, width=6).grid(row=3, column=3, sticky=tk.W)
        ttk.Label(hybrid_fr, text="Min keep sec").grid(row=3, column=4, sticky=tk.W, padx=(8, 0))
        ttk.Entry(hybrid_fr, textvariable=self.min_keep_v, width=6).grid(row=3, column=5, sticky=tk.W)

        self.episode_aware_v = tk.BooleanVar(value=settings.episode_aware)
        ttk.Checkbutton(hybrid_fr, text="Episode-aware segmentation", variable=self.episode_aware_v).grid(
            row=4,
            column=0,
            columnspan=2,
            sticky=tk.W,
            pady=(2, 0),
        )
        self.boundary_gap_v = tk.StringVar(value=f"{settings.episode_boundary_min_gap_seconds:.1f}")
        self.boundary_black_v = tk.StringVar(value=f"{settings.episode_boundary_black_min_seconds:.1f}")
        self.boundary_silence_v = tk.StringVar(value=f"{settings.episode_boundary_silence_min_seconds:.1f}")
        ttk.Label(hybrid_fr, text="Episode min gap").grid(row=5, column=0, sticky=tk.W)
        ttk.Entry(hybrid_fr, textvariable=self.boundary_gap_v, width=6).grid(row=5, column=1, sticky=tk.W)
        ttk.Label(hybrid_fr, text="Black min").grid(row=5, column=2, sticky=tk.W, padx=(8, 0))
        ttk.Entry(hybrid_fr, textvariable=self.boundary_black_v, width=6).grid(row=5, column=3, sticky=tk.W)
        ttk.Label(hybrid_fr, text="Silence min").grid(row=5, column=4, sticky=tk.W, padx=(8, 0))
        ttk.Entry(hybrid_fr, textvariable=self.boundary_silence_v, width=6).grid(row=5, column=5, sticky=tk.W)

        self.fail_safe_mode_v = tk.StringVar(value=settings.fail_safe_mode)
        self.low_risk_ratio_v = tk.StringVar(value=f"{settings.low_risk_max_commercial_ratio:.2f}")
        ttk.Label(hybrid_fr, text="Fail-safe").grid(row=6, column=0, sticky=tk.W)
        ttk.Combobox(
            hybrid_fr,
            textvariable=self.fail_safe_mode_v,
            values=["low_risk_cut", "no_cut"],
            width=14,
            state="readonly",
        ).grid(row=6, column=1, sticky=tk.W)
        ttk.Label(hybrid_fr, text="Low-risk max ratio").grid(row=6, column=2, sticky=tk.W, padx=(8, 0))
        ttk.Entry(hybrid_fr, textvariable=self.low_risk_ratio_v, width=6).grid(row=6, column=3, sticky=tk.W)

        bf = ttk.Frame(f)
        bf.grid(row=12, column=0, columnspan=2, pady=12)
        ttk.Button(bf, text="Save job", command=self.save).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="Cancel", command=self.destroy).pack(side=tk.LEFT, padx=4)

        self._fit_to_content()

    def _fit_to_content(self) -> None:
        self.update_idletasks()
        pad = 20
        req_w = self.winfo_reqwidth() + pad
        req_h = self.winfo_reqheight() + pad
        max_w = int(self.winfo_screenwidth() * 0.90)
        max_h = int(self.winfo_screenheight() * 0.85)
        target_w = min(req_w, max_w)
        target_h = min(req_h, max_h)
        self.geometry(f"{target_w}x{target_h}")
        self.minsize(min(req_w, max_w), min(req_h, max_h))

    def browse_out(self) -> None:
        d = filedialog.askdirectory(title="Output folder")
        if d:
            self.out_v.set(d)

    def _selected_source_id(self) -> str | None:
        label = self.src_v.get()
        for s in self.cfg.sources:
            if f"({s.id[:8]}" in label:
                return s.id
        if self.cfg.sources:
            return self.cfg.sources[0].id
        return None

    def load_channels(self) -> None:
        sid = self._selected_source_id()
        if not sid:
            return
        src = source_by_id(self.cfg, sid)
        if not src:
            return
        try:
            chs = load_m3u(src.path_or_url)
        except Exception as e:
            messagebox.showerror("M3U", str(e), parent=self)
            return
        picker = ChannelPicker(self, [c.name for c in chs])
        self.wait_window(picker)
        if picker.selected_name:
            self.ch_v.set(picker.selected_name)

    def save(self) -> None:
        name = self.name_v.get().strip()
        if not name:
            messagebox.showerror("Job", "Name required.", parent=self)
            return
        sid = self._selected_source_id()
        if not sid:
            messagebox.showerror("Job", "Select a source.", parent=self)
            return
        ch = self.ch_v.get().strip()
        if not ch:
            messagebox.showerror("Job", "Channel required.", parent=self)
            return
        try:
            parse_duration(self.dur_v.get().strip())
        except Exception as e:
            messagebox.showerror("Duration", str(e), parent=self)
            return
        days = [d for d, v in self.day_vars.items() if v.get()]
        mode = self.mode_v.get()
        if mode == "weekly" and not days:
            messagebox.showerror("Schedule", "Pick at least one weekday.", parent=self)
            return
        try:
            hour = int(self.hour_v.get())
            minute = int(self.min_v.get())
        except ValueError:
            messagebox.showerror("Schedule", "Invalid hour/minute.", parent=self)
            return
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            messagebox.showerror("Schedule", "Hour 0–23, minute 0–59.", parent=self)
            return
        try:
            weight_myth = float(self.weight_myth_v.get())
            weight_legacy = float(self.weight_legacy_v.get())
            weight_ffmpeg = float(self.weight_ffmpeg_v.get())
            confidence_threshold = float(self.confidence_threshold_v.get())
            max_ratio = float(self.max_ratio_v.get())
            min_keep = float(self.min_keep_v.get())
            boundary_gap = float(self.boundary_gap_v.get())
            boundary_black = float(self.boundary_black_v.get())
            boundary_silence = float(self.boundary_silence_v.get())
            low_risk_ratio = float(self.low_risk_ratio_v.get())
        except ValueError:
            messagebox.showerror("Commercial settings", "Commercial settings must use numeric values.", parent=self)
            return

        if self.job is None:
            j = Job.new(name, sid, ch, self.dur_v.get().strip(), self.out_v.get().strip())
            self.cfg.jobs.append(j)
            self.job = j
        else:
            j = self.job
            j.name = name
            j.source_id = sid
            j.channel = ch
            j.duration = self.dur_v.get().strip()
            j.output_dir = self.out_v.get().strip()
        selected_fmt = self.output_fmt_v.get().strip().lower() or "ts"
        if selected_fmt not in ("ts", "mp4", "mkv", "mov"):
            selected_fmt = "ts"
        pattern = self.pat_v.get().strip() or "{date}_{channel}.ts"
        base = Path(pattern).stem if Path(pattern).suffix else pattern
        j.filename_pattern = f"{base}.{selected_fmt}"
        j.output_format = selected_fmt
        j.enabled = self.en_v.get()
        j.remove_commercials_after_complete = self.remove_commercials_v.get()
        strategy = self.strategy_v.get().strip()
        if strategy not in ("myth_only", "legacy_only", "hybrid"):
            strategy = "myth_only"
        fail_safe_mode = self.fail_safe_mode_v.get().strip()
        if fail_safe_mode not in ("low_risk_cut", "no_cut"):
            fail_safe_mode = "low_risk_cut"
        j.commercial_settings = CommercialRemovalSettings(
            strategy=strategy,  # type: ignore[arg-type]
            enable_myth=self.enable_myth_v.get(),
            enable_legacy=self.enable_legacy_v.get(),
            enable_ffmpeg_signals=self.enable_ffmpeg_signals_v.get(),
            weight_myth=max(0.0, weight_myth),
            weight_legacy=max(0.0, weight_legacy),
            weight_ffmpeg_signals=max(0.0, weight_ffmpeg),
            confidence_threshold=max(0.0, min(1.0, confidence_threshold)),
            max_commercial_ratio=max(0.0, min(0.95, max_ratio)),
            min_keep_segment_seconds=max(0.0, min_keep),
            episode_aware=self.episode_aware_v.get(),
            episode_boundary_min_gap_seconds=max(15.0, boundary_gap),
            episode_boundary_black_min_seconds=max(0.1, boundary_black),
            episode_boundary_silence_min_seconds=max(0.1, boundary_silence),
            fail_safe_mode=fail_safe_mode,  # type: ignore[arg-type]
            low_risk_max_commercial_ratio=max(0.0, min(0.95, low_risk_ratio)),
        )
        j.schedule.mode = "daily" if mode == "daily" else "weekly"
        j.schedule.days = [] if mode == "daily" else days
        j.schedule.hour = hour
        j.schedule.minute = minute

        if not self.master.persist_and_sync(parent=self):
            return
        self._on_done()
        self.destroy()


class SourceEditor(tk.Toplevel):
    def __init__(self, parent: tk.Misc, *, title: str, name: str = "", source: str = "") -> None:
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.result: tuple[str, str] | None = None

        root = ttk.Frame(self, padding=10)
        root.grid(row=0, column=0, sticky="nsew")
        self.grid_columnconfigure(0, weight=1)
        root.grid_columnconfigure(1, weight=1)

        ttk.Label(root, text="Name").grid(row=0, column=0, sticky=tk.W, pady=(0, 6))
        self.name_v = tk.StringVar(value=name)
        name_entry = ttk.Entry(root, textvariable=self.name_v, width=48)
        name_entry.grid(row=0, column=1, sticky="ew", pady=(0, 6))

        ttk.Label(root, text="Source").grid(row=1, column=0, sticky=tk.W)
        src_fr = ttk.Frame(root)
        src_fr.grid(row=1, column=1, sticky="ew")
        src_fr.grid_columnconfigure(0, weight=1)
        self.source_v = tk.StringVar(value=source)
        src_entry = ttk.Entry(src_fr, textvariable=self.source_v, width=48)
        src_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(src_fr, text="Browse…", command=self._browse_source).grid(row=0, column=1, padx=(6, 0))
        ttk.Label(
            root,
            text="Enter local .m3u path or http(s) URL.",
            font=("TkDefaultFont", 8),
        ).grid(row=2, column=1, sticky=tk.W, pady=(4, 0))

        btns = ttk.Frame(root)
        btns.grid(row=3, column=0, columnspan=2, sticky=tk.E, pady=(12, 0))
        ttk.Button(btns, text="Save", command=self._save).pack(side=tk.LEFT)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side=tk.LEFT, padx=(6, 0))

        self.bind("<Return>", lambda _e: self._save())
        self.bind("<Escape>", lambda _e: self.destroy())
        name_entry.focus_set()

    def _browse_source(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select M3U source file",
            filetypes=[("M3U", "*.m3u"), ("All files", "*.*")],
            parent=self,
        )
        if selected:
            self.source_v.set(selected)

    def _save(self) -> None:
        name = self.name_v.get().strip()
        source = self.source_v.get().strip()
        if not name:
            messagebox.showerror("Source", "Name is required.", parent=self)
            return
        if not source:
            messagebox.showerror("Source", "Source is required.", parent=self)
            return
        self.result = (name, source)
        self.destroy()


class ChannelPicker(tk.Toplevel):
    def __init__(self, parent: tk.Misc, names: list[str]) -> None:
        super().__init__(parent)
        self.title("Pick channel")
        self.geometry("520x460")
        self.transient(parent)
        self.grab_set()
        self.selected_name: str | None = None
        self._all = sorted(set(n.strip() for n in names if n.strip()), key=str.lower)

        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)
        ttk.Label(root, text="Search channel").pack(anchor=tk.W)
        self.query = tk.StringVar()
        ent = ttk.Entry(root, textvariable=self.query)
        ent.pack(fill=tk.X, pady=(0, 8))
        ent.focus_set()
        ent.bind("<KeyRelease>", lambda _e: self._refresh())
        ent.bind("<Return>", lambda _e: self._ok())

        self.listbox = tk.Listbox(root, activestyle="dotbox")
        self.listbox.pack(fill=tk.BOTH, expand=True)
        self.listbox.bind("<Double-Button-1>", lambda _e: self._ok())
        self.listbox.bind("<Return>", lambda _e: self._ok())

        btn = ttk.Frame(root)
        btn.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn, text="Select", command=self._ok).pack(side=tk.LEFT)
        ttk.Button(btn, text="Cancel", command=self.destroy).pack(side=tk.LEFT, padx=8)

        self._refresh()

    def _refresh(self) -> None:
        q = self.query.get().strip().lower()
        if not q:
            show = self._all
        else:
            show = [n for n in self._all if q in n.lower()]
        self.listbox.delete(0, tk.END)
        for n in show[:5000]:
            self.listbox.insert(tk.END, n)
        if self.listbox.size() > 0:
            self.listbox.selection_set(0)
            self.listbox.activate(0)

    def _ok(self) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        self.selected_name = self.listbox.get(sel[0])
        self.destroy()


def main() -> None:
    _install_exception_hooks()
    if len(sys.argv) >= 2 and sys.argv[1] == "run-job":
        p = argparse.ArgumentParser()
        p.add_argument("run_job", nargs="?")
        p.add_argument("--job-id", required=True)
        args = p.parse_args()
        raise SystemExit(run_job(args.job_id))
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
