"""
Tkinter GUI for M3U sources and recurring Windows scheduled recordings.
Run from repo root:  python gui\\main.py
Headless (Task Scheduler):  python gui\\main.py run-job --job-id <uuid>
Frozen exe:                 iptv-gui.exe run-job --job-id <uuid>
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from config_store import AppConfig, Job, Source, job_by_id, load_config, save_config, source_by_id
from duration_parse import parse_duration
from job_runner import run_job
from m3u_load import load_m3u
from paths import ffmpeg_exe, is_frozen, project_root
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

        menubar = tk.Menu(self)
        fm = tk.Menu(menubar, tearoff=0)
        fm.add_command(label="Save config", command=self.on_save)
        fm.add_command(label="Sync Windows tasks", command=self.on_sync)
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
        self.after(100, self._maybe_prompt_install_ffmpeg)

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
        save_config(self.cfg)
        messagebox.showinfo("Saved", "Configuration written to config.json")

    def on_sync(self) -> None:
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
        if ok:
            messagebox.showinfo("Tasks", "Windows scheduled tasks are in sync.")
        else:
            messagebox.showerror("Task error", err)

    def on_ffmpeg_status(self) -> None:
        ff = ffmpeg_exe()
        if ff.is_file():
            messagebox.showinfo("FFmpeg", f"Embedded binary found:\n{ff}")
        else:
            messagebox.showwarning(
                "FFmpeg missing",
                f"No embedded FFmpeg at:\n{ff}\n\n"
                "Run scripts\\download_ffmpeg.ps1 (repo ffmpeg) or\n"
                "scripts\\download_ffmpeg.ps1 -DestDir .\\gui\\ffmpeg (portable next to the .exe).",
            )

    def _maybe_prompt_install_ffmpeg(self) -> None:
        if ffmpeg_exe().is_file():
            return
        yes = messagebox.askyesno(
            "FFmpeg missing",
            "FFmpeg is required for recording.\n\n"
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
                "$bin=Join-Path $inner.FullName 'bin\\ffmpeg.exe'; "
                "if (-not (Test-Path $bin)) { throw 'ffmpeg.exe not found in downloaded archive.' }; "
                "Copy-Item -Force $bin (Join-Path $dest 'ffmpeg.exe'); "
                "Remove-Item $work -Recurse -Force;"
            )
            cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_inline]
            r = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if r.returncode == 0 and ffmpeg_exe().is_file():
            return True, (r.stdout or "").strip()
        msg = (r.stderr or r.stdout or "").strip()
        return False, msg or f"Installer exited with code {r.returncode}."

    def _on_ffmpeg_install_done(self, ok: bool, msg: str) -> None:
        if ok:
            messagebox.showinfo("FFmpeg install", f"FFmpeg installed successfully:\n{ffmpeg_exe()}", parent=self)
        else:
            messagebox.showerror(
                "FFmpeg install failed",
                "Automatic install failed.\n\n"
                "You can run scripts\\download_ffmpeg.ps1 manually.\n\n"
                f"Details:\n{msg}",
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
        name = simpledialog.askstring("Source", "Display name:", parent=self)
        if not name:
            return
        path = filedialog.askopenfilename(title="M3U file (or Cancel to type URL)", filetypes=[("M3U", "*.m3u"), ("All", "*.*")])
        if not path:
            path = simpledialog.askstring("Source", "M3U file path or http(s) URL:", parent=self) or ""
        path = path.strip()
        if not path:
            return
        self.cfg.sources.append(Source.new(name, path))
        self.refresh_lists()

    def edit_source(self) -> None:
        s = self.selected_source()
        if not s:
            messagebox.showinfo("Edit", "Select a source first.")
            return
        name = simpledialog.askstring("Source", "Display name:", initialvalue=s.name, parent=self)
        if name is None:
            return
        path = simpledialog.askstring(
            "Source",
            "M3U file path or URL:",
            initialvalue=s.path_or_url,
            parent=self,
        )
        if path is None:
            return
        s.name = name.strip()
        s.path_or_url = path.strip()
        self.refresh_lists()

    def remove_source(self) -> None:
        s = self.selected_source()
        if not s:
            return
        if not messagebox.askyesno("Remove", f"Remove source {s.name!r}?"):
            return
        self.cfg.sources = [x for x in self.cfg.sources if x.id != s.id]
        self.cfg.jobs = [j for j in self.cfg.jobs if j.source_id != s.id]
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
        self.refresh_lists()

    def run_selected_job_now(self) -> None:
        j = self.selected_job()
        if not j:
            messagebox.showinfo("Run now", "Select a job first.")
            return
        if not messagebox.askyesno("Run now", f"Start job now?\n\n{j.name}"):
            return

        def worker() -> None:
            code = run_job(j.id)
            self.after(0, lambda: self._on_manual_run_done(j.name, code))

        threading.Thread(target=worker, daemon=True).start()
        messagebox.showinfo(
            "Run now",
            "Job started in background.\n"
            "Check logs in gui\\logs\\job_<id>.log while it runs.",
        )

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

        bf = ttk.Frame(f)
        bf.grid(row=11, column=0, columnspan=2, pady=12)
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
        j.schedule.mode = "daily" if mode == "daily" else "weekly"
        j.schedule.days = [] if mode == "daily" else days
        j.schedule.hour = hour
        j.schedule.minute = minute

        save_config(self.cfg)
        self._on_done()
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
