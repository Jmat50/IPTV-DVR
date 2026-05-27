# Caption overhaul rollout

## Staged enablement

1. **Default for new jobs:** `caption_mode: off` (unchanged until user opts in).
2. **Migration:** existing `download_captions: true` loads as `auto` on next config read/save.
3. **Promote to default:** after validation, switch Job Editor default from `off` to `auto` in code.

## Acceptance checks

| Scenario | Expected |
|----------|----------|
| Mode `off` | No sidecar processes; record unchanged. |
| Mode `post_only`, `.ts`, embedded 608 | `.srt` after record via FFmpeg fallback. |
| Mode `live_ccextractor`, CCExtractor present | `.srt` exists at end; may grow during record. |
| Mode `auto`, no CCExtractor | Same as `post_only`. |
| HLS subs on manifest | `.vtt` during record when probe succeeds. |
| Live worker failure | Post-extract still runs; log notes live failure. |
| Scheduled late start | Caption duration matches trimmed `-t`. |
| Manual run-now | Full duration; no window skip. |
| Manual early stop (Ctrl+C / end FFmpeg process) | Non-empty `.ts` is preserved, normalized, and treated as successful early stop (no false failure marker). |

## Runtime integrity checks

- `gui\tools\ccextractor\` (or frozen `tools\ccextractor\`) must contain:
  - `ccextractor.exe`
  - `libgpac.dll`
  - sibling runtime DLL set from the downloaded bundle
- Build script must not treat CCExtractor as installed when only the EXE exists.
- Live worker invocation contract:
  - `ccextractor --stream 15 -out=srt <recording.ts> -o <recording.srt.partial>`
  - finalization = validate `.srt.partial` then atomic rename to `.srt`
- Partial-stop TS normalization contract (`.ts` with bytes + non-zero FFmpeg exit):
  - run remux with `+genpts+discardcorrupt`, `ignore_err`, `make_zero`
  - apply video `setts` rewrite using probed `avg_frame_rate`
  - then run caption finalization
  - classify user-stop exits (`3221225786`, `-1073741510`, `130`) as success when output exists

## Known failure signatures

- `libgpac.dll was not found` -> incomplete runtime install.
- `a value is required for '--stream <STREAM>'` -> wrong stream-mode argument shape.
- `captions: live worker produced no valid SRT` -> worker ran but output was empty/invalid.
- `Error reading HTTP response: End of file` with HLS parse errors -> upstream transport instability; rely on reconnect, fallback, and rerun if needed.
- `Recording failed (ffmpeg exit code 3221225786)` with non-empty `.ts` -> user stop path should be treated as success; investigate if marker still appears.

## Regression gates

- `go test ./...`
- `python -m compileall gui`
- `cd gui && python -m unittest caption_mode_test caption_worker_test`
- Windows: one 15s test capture with captions `auto` + CCExtractor installed.
