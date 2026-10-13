# FileGuard

Self-hosted file manager with right-click security/utility actions. Built because FileBrowser has no plugin system for custom buttons — only a shell-command runner, which isn't the UX wanted (real right-click actions, not typed commands).

## Stack

- Flask (Python), single `app.py`, one template (`templates/browse.html`)
- `python:3.12-alpine` base image
- HTTP Basic Auth on every route (`@app.before_request`)
- No database — filesystem is the only state

## Folder scope

Browsable root is `/data` inside the container. Access is restricted by **Docker volume mounts only** (not app-level path filtering) — each host folder is mounted individually, so the container has zero visibility into anything not explicitly mounted:

```
-v /home/cu3d/Documents:/data/Documents
-v /home/cu3d/Downloads:/data/Downloads
-v /home/cu3d/assets:/data/assets
-v /home/cu3d/Pictures:/data/Pictures
-v /home/cu3d/Music:/data/Music
-v /home/cu3d/calibre:/data/calibre
-v /home/cu3d/Videos:/data/Videos
-v <filebrowser_config_volume>:/config:ro
```

The `/config:ro` mount reuses FileBrowser's existing config volume read-only, so FileGuard can read the ClamAV database (`/config/clamav`) and VirusTotal API key (`/config/vt_api_key`) without duplicating them.

## Auth

`AUTH_USER` / `AUTH_PASS` env vars, HTTP Basic Auth. No default password — `AUTH_PASS=""` always fails auth, so the container refuses to be usable until a real password is injected via `--env-file` at `docker run`. No session/token concept — every request re-checks the header.

## Routes

### Browsing
- `GET /`, `/browse/`, `/browse/<path>` — lists a directory as a grid of tiles (folders first, then files, alphabetical). Builds breadcrumbs from the path for the clickable header nav. `safe_path()` normalizes and confirms the resolved path stays under `ROOT` (`/data`) — blocks `../` traversal.

### Actions (all GET with `?path=<rel_path>`, called via right-click context menu)
- `/api/clamscan` — runs `clamscan --database=/config/clamav <file>` on a single file. Returns stdout+stderr and the return code (1 = infected).
- `/api/vtcheck` — SHA-256 hashes the file, looks it up against VirusTotal API v3 (`x-apikey` header from `/config/vt_api_key`). 404 from VT means unseen hash, not clean — returns a manual-upload link in that case. Otherwise returns `last_analysis_stats` (malicious/suspicious/harmless/undetected) and a report URL.
- `/api/convert` — transcodes any video to `.mp4` via ffmpeg (`libx264`, `veryfast`, `crf 23`, `aac 192k`). Refuses if a same-named `.mp4` already exists. 1-hour subprocess timeout.
- `/api/extract` — archive extraction. Dispatches on extension: `.zip` (`unzip`), `.tar`/`.tar.gz`/`.tgz` (`tar`), `.7z` (`7z`), `.rar` (`unrar`, see below). Always extracts into a new folder named after the archive; refuses if that folder already exists. 30-min timeout.
- `/api/compress` — zips a file or folder (`zip -r`) into a sibling `.zip` named after the target. Refuses if that `.zip` already exists. 30-min timeout.

All action routes return JSON `{"ok": bool, ...}`; errors truncate subprocess stderr/stdout to the last 2000 chars.

## RAR support (why it's weird)

Alpine has no `unrar`/`rar` CLI package. Dockerfile downloads RARLAB's official free `unrar` binary directly (`rarlinux-x64-720.tar.gz`). That binary is glibc-linked but Alpine is musl — needed the `gcompat` package (musl→glibc shim) or it fails with a misleading "exec: no such file or directory" even though the file is right there.

## 7z quirk

Every other extractor takes the output dir as its own trailing arg. 7z wants `-o<dir>` concatenated with no space — handled as a special case in `api_extract` (`cmd[-1] = cmd[-1] + out_dir` only when `cmd[0] == "7z"`).

## Frontend (`templates/browse.html`)

Single HTML file, vanilla JS, no framework/build step. Dark theme, CSS grid of tiles with emoji icons chosen by extension. Right-click on any tile with a `data-path` attribute opens a positioned context menu (`#ctxmenu`) with the 5 actions above. Results show in a bottom-docked panel (`#resultbox`); long-running actions show an indeterminate animated progress bar + elapsed-time counter (`startProgress()`/`stopProgress()`), since there's no real percentage feedback from ffmpeg/zip/etc — just activity + time elapsed.

Successful convert/extract/compress trigger `location.reload()` after a short delay so the new file/folder shows up in the grid.

## Known limitations / not built

- No true progress percentage (ffmpeg could expose this via its own progress output, but isn't parsed — only an indeterminate bar + timer)
- No multi-file select / batch actions
- No upload, rename, move, or delete from the UI — browse + the 5 actions only
- No session expiry concept at all (plain Basic Auth, re-checked every request)
