# Video Preview Tile Generator — Agent Guide

## Architecture

Single-file FastAPI backend (`app/main.py`) with vanilla HTML/CSS/JS frontend (`app/static/`). No build step — Python runs directly via `uvicorn main:app`. Frontend is served as static files by FastAPI.

## Dev commands

```bash
# Run locally (macOS/Linux, ffmpeg required)
uvicorn main:app --host 0.0.0.0 --port 8080

# Stop: Ctrl+C or kill $(lsof -ti :8080)
```

## Docker deployment

Images hosted at `ghcr.io/s-zh/video-preview-tool:latest`. Auto-built by GitHub Actions on push to `main` (`.github/workflows/docker-build.yml`).

```bash
# Build locally (from project root)
./build.sh                          # handles China mirror fallback
docker build -t video-preview-tool:latest ./app

# Update running container
docker compose pull && docker compose up -d
```

Longer truth: `build.sh` auto-detects Docker Hub reachability, falls back to Chinese mirrors with `APT_MIRROR` and `PIP_INDEX` build args. The `Dockerfile` accepts these as `ARG` for apt/pip mirror substitution.

## Backend gotchas

### ffmpeg VAAPI filter chain

VAAPI surfaces **must** be downloaded before `fps` filter — `fps` hangs on VAAPI input. The correct chain prefix is `hwdownload,format=nv12` before `fps`. This applies to VAAPI, CUDA, and D3D11VA paths. See `detect_hwaccel()` in `app/main.py` which sets `filter_prefix` per backend.

### Performance: keyframe-only decode

`-skip_frame nokey` is used for HW decode paths. This decodes only keyframes (~1 every 2s) instead of all frames. For a 21-min video this reduces 37800 frames to ~630 — ~60× faster.

### Task persistence

- Tasks saved to JSON at `TASKS_DB_PATH` (default: `/tmp/video-preview-tool/tasks.json`) on every state change
- On restart, running tasks are marked `cancelled` (can't resume subprocesses)
- Orphan `/tmp/previews/` dirs not referenced by any task are cleaned up at startup

### Config env vars

| Variable | Default | Notes |
|---|---|---|
| `BASE_PATH` | `/mnt/host` | Root for file browsing |
| `PORT` | `8080` | Server port |
| `CONCURRENCY` | `2` | Parallel ffmpeg processes |
| `TASKS_DB_PATH` | `/tmp/video-preview-tool/tasks.json` | Persistence file |

### HW acceleration auto-detection

`detect_hwaccel()` in `main.py` probes `ffmpeg -hwaccels` output and available devices. Priority order per platform:
- **macOS**: VideoToolbox
- **Linux**: CUDA (if nvidia-smi or /dev/nvidia0 exists) → VAAPI (if /dev/dri/renderD128 exists) → software
- **Windows**: CUDA → D3D11VA → software

### REST API endpoints

All under `/api/`: `browse`, `scan`, `start`, `status/{id}`, `cancel/{id}`, `tasks`, `delete/{id}`, `retry/{id}`, `cleanup`, `download/{id}`, `preview/{task_id}/{index}`, `config`, `health`.

## Frontend gotchas

- Lightbox source paths come from `result_sources[]` (parallel to `results[]`), passed as `encodeURIComponent(JSON.stringify(sources))` in onclick attribute, decoded in `openLightbox()`
- Gallery items get `gallery-item-active` blue highlight class when lightbox is closed
- There's a duplicate `updateLightbox()` function in `app.js` (second one at ~line 351 wins at runtime)
- Preview images are ZIPped on demand (not pre-cached); JPEG is already compressed so DEFLATE adds negligible benefit
- Polling (`setInterval 1s`) during running tasks only re-renders progress/file-status, not the gallery

## Style conventions

- Commit messages use conventional commits: `fix:`, `feat:`, `chore:`
- No Python type annotations used beyond FastAPI's Pydantic models
- Frontend is vanilla JS (no framework), inline event handlers in HTML attributes
- All translations/user-facing text in Chinese
- Frontend file naming: `index.html`, `app.js`, `style.css` — no router, no bundler

## Conventional commit & push

After code changes: `git add -A && git commit -m "type: message" && git push origin main`. Docker image auto-builds via GitHub Actions on push to `main`.
