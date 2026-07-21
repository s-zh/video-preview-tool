import os
import io
import time
import uuid
import asyncio
import logging
import zipfile
import tempfile
import platform
import subprocess
import shutil
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Video Preview Tool")

BASE_PATH = os.environ.get("BASE_PATH", "/mnt/host")
VIDEO_EXTENSIONS = {
    '.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv',
    '.webm', '.m4v', '.mpg', '.mpeg', '.ts', '.3gp',
}

tasks: dict = {}

CONCURRENCY = int(os.environ.get("CONCURRENCY", "2"))

_SEMAPHORE: Optional[asyncio.Semaphore] = None
_HWACCEL_INFO: Optional[dict] = None


def _get_ffmpeg_hwaccels() -> list:
    try:
        r = subprocess.run(
            ["ffmpeg", "-hwaccels"],
            capture_output=True, text=True, timeout=15,
        )
        lines = r.stdout.split("\n")
        return [line.strip().lower() for line in lines
                if line.strip() and "hwaccel" not in line.lower()]
    except Exception as e:
        logger.warning(f"ffmpeg -hwaccels failed: {e}")
        return []


def _identify_gpu() -> str:
    try:
        r = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.split("\n"):
            if "VGA" in line or "3D" in line or "Display" in line:
                if "Intel" in line:
                    return "Intel QSV"
                if "AMD" in line or "ATI" in line:
                    return "AMD"
                return "GPU"
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return f"NVIDIA {r.stdout.strip().split(chr(10))[0]}"
    except Exception:
        pass
    return "GPU"


def detect_hwaccel() -> dict:
    system = platform.system()
    info = {"type": "", "name": "Software (CPU)", "args": [], "filter_prefix": ""}

    hwaccels = _get_ffmpeg_hwaccels()
    logger.info(f"ffmpeg available hwaccels: {hwaccels}")
    logger.info(f"System: {system}")

    if system == "Darwin":
        if "videotoolbox" in hwaccels:
            info = {
                "type": "videotoolbox",
                "name": "VideoToolbox (Apple Silicon)",
                "args": ["-hwaccel", "videotoolbox"],
                "filter_prefix": "",
            }
            logger.info("Using VideoToolbox HW acceleration")

    elif system == "Linux":
        if "cuda" in hwaccels and (
            shutil.which("nvidia-smi") or os.path.exists("/dev/nvidia0")
        ):
            gpu = _identify_gpu()
            info = {
                "type": "cuda",
                "name": f"CUDA ({gpu})",
                "args": ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"],
                "filter_prefix": "hwdownload,format=nv12",
            }
            logger.info(f"Using CUDA HW acceleration ({gpu})")
        elif os.path.exists("/dev/dri/renderD128"):
            gpu = _identify_gpu()
            info = {
                "type": "vaapi",
                "name": f"VAAPI ({gpu})",
                "args": ["-hwaccel", "vaapi", "-hwaccel_output_format", "vaapi"],
                "filter_prefix": "hwdownload,format=nv12",
            }
            logger.info(f"Using VAAPI HW acceleration ({gpu})")
        else:
            logger.info("No HW acceleration device found, using software decode")

    elif system == "Windows":
        if "cuda" in hwaccels and shutil.which("nvidia-smi"):
            info = {
                "type": "cuda",
                "name": "CUDA (NVIDIA)",
                "args": ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"],
                "filter_prefix": "hwdownload,format=nv12",
            }
            logger.info("Using CUDA HW acceleration")
        elif "d3d11va" in hwaccels:
            info = {
                "type": "d3d11va",
                "name": "D3D11VA (WDDM)",
                "args": ["-hwaccel", "d3d11va", "-hwaccel_output_format", "d3d11"],
                "filter_prefix": "hwdownload,format=nv12",
            }
            logger.info("Using D3D11VA HW acceleration")
        else:
            logger.info("No HW acceleration available on Windows")

    return info


def _find_font() -> str:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    env_font = os.environ.get("DRAWTEXT_FONT", "")
    if env_font and os.path.exists(env_font):
        return env_font
    return ""


_FONT_PATH: str = ""

def get_font() -> str:
    global _FONT_PATH
    if not _FONT_PATH:
        _FONT_PATH = _find_font()
    return _FONT_PATH


def get_semaphore() -> asyncio.Semaphore:
    global _SEMAPHORE
    if _SEMAPHORE is None:
        _SEMAPHORE = asyncio.Semaphore(CONCURRENCY)
    return _SEMAPHORE


def get_hwaccel() -> dict:
    global _HWACCEL_INFO
    if _HWACCEL_INFO is None:
        _HWACCEL_INFO = detect_hwaccel()
    return _HWACCEL_INFO


class BrowseRequest(BaseModel):
    path: str = BASE_PATH


class StartRequest(BaseModel):
    path: str
    files: List[str]
    grid_cols: int = 6
    grid_rows: int = 4
    thumb_width: int = 320
    thumb_height: int = 180
    show_timestamps: bool = False


def validate_path(path: str) -> Path:
    p = Path(path).resolve()
    base = Path(BASE_PATH).resolve()
    base_s = str(base)
    if base_s != '/':
        base_s += '/'
    if not str(p).startswith(base_s) and str(p) != str(base):
        raise HTTPException(403, "Access denied: path outside allowed base")
    if not p.exists():
        raise HTTPException(404, "Path not found")
    return p


@app.get("/api/config")
async def get_config():
    hw = get_hwaccel()
    return {
        "base_path": BASE_PATH,
        "video_extensions": list(sorted(VIDEO_EXTENSIONS)),
        "hwaccel": hw["type"],
        "hwaccel_name": hw["name"],
        "concurrency": CONCURRENCY,
    }


@app.post("/api/browse")
async def browse(req: BrowseRequest):
    path = validate_path(req.path)
    if not path.is_dir():
        raise HTTPException(400, "Not a directory")

    dirs, videos = [], []
    try:
        for entry in path.iterdir():
            if entry.is_dir() and not entry.name.startswith('.'):
                dirs.append(entry.name)
            elif entry.is_file() and entry.suffix.lower() in VIDEO_EXTENSIONS:
                videos.append(entry.name)
    except PermissionError:
        raise HTTPException(403, "Permission denied")

    parent = None
    if path != Path(BASE_PATH).resolve():
        parent = str(path.parent)

    display = str(path).removeprefix(BASE_PATH) or "/"

    return {
        "current_path": str(path),
        "display_path": display,
        "directories": sorted(dirs),
        "video_files": sorted(videos),
        "parent": parent,
    }


@app.post("/api/scan")
async def scan(req: StartRequest):
    path = validate_path(req.path)
    if not path.is_dir():
        raise HTTPException(400, "Not a directory")

    video_files = []
    try:
        for entry in path.rglob("*"):
            if entry.is_file() and entry.suffix.lower() in VIDEO_EXTENSIONS:
                video_files.append(str(entry))
    except PermissionError as e:
        logger.warning(f"Permission denied during scan: {e}")

    return {"files": sorted(video_files), "count": len(video_files)}


@app.post("/api/start")
async def start_task(req: StartRequest):
    valid_files = [f for f in req.files if Path(f).exists()]
    if not valid_files:
        raise HTTPException(400, "No valid video files found")

    path_obj = Path(req.path)
    task_name = path_obj.name or str(path_obj)
    display_path = str(path_obj).removeprefix(BASE_PATH) or "/"

    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        "id": task_id,
        "name": task_name,
        "path": req.path,
        "display_path": display_path,
        "status": "running",
        "progress": 0,
        "current_file": "",
        "total_files": len(valid_files),
        "completed_files": 0,
        "failed_files": [],
        "cancelled": False,
        "results": [],
        "files": valid_files,
        "grid_cols": req.grid_cols,
        "grid_rows": req.grid_rows,
        "thumb_width": req.thumb_width,
        "thumb_height": req.thumb_height,
        "show_timestamps": req.show_timestamps,
        "process": None,
        "start_time": time.time(),
    }

    asyncio.create_task(_run_task(task_id))
    return {"task_id": task_id}


@app.get("/api/status/{task_id}")
async def get_status(task_id: str):
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return {
        "id": task["id"],
        "name": task.get("name", ""),
        "path": task.get("path", ""),
        "display_path": task.get("display_path", ""),
        "status": task["status"],
        "progress": task["progress"],
        "current_file": task["current_file"],
        "total_files": task["total_files"],
        "completed_files": task["completed_files"],
        "failed_files": task["failed_files"],
        "results": task["results"],
        "file_statuses": task.get("file_statuses", {}),
        "file_errors": task.get("file_errors", {}),
    }


@app.post("/api/tasks/{task_id}/delete")
async def delete_task(task_id: str):
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    if task["status"] == "running" or task["status"] == "cancelling":
        task["cancelled"] = True
        if task.get("process"):
            try:
                task["process"].kill()
            except Exception:
                pass

    del tasks[task_id]
    logger.info(f"Deleted task {task_id}")
    return {"status": "ok"}


@app.post("/api/cancel/{task_id}")
async def cancel_task(task_id: str):
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task["status"] == "running":
        task["cancelled"] = True
        task["status"] = "cancelling"
        if task.get("process"):
            try:
                task["process"].kill()
            except Exception:
                pass
    return {"status": "ok"}


@app.post("/api/tasks/{task_id}/retry")
async def retry_task(task_id: str):
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task["status"] not in ("completed", "cancelled"):
        raise HTTPException(400, "Task is still running")
    if not task["failed_files"]:
        raise HTTPException(400, "No failed files to retry")

    failed = task["failed_files"].copy()
    task["failed_files"] = []
    task["cancelled"] = False
    task["status"] = "running"
    task["current_file"] = ""

    asyncio.create_task(_run_task(task_id, retry_files=failed))
    return {"status": "ok", "retry_count": len(failed)}


@app.get("/api/download/{task_id}")
async def download_results(task_id: str):
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task["status"] not in ("completed", "cancelled"):
        raise HTTPException(400, "Task not finished")
    if not task["results"]:
        raise HTTPException(400, "No previews generated")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in task["results"]:
            if os.path.exists(file_path):
                zf.write(file_path, os.path.basename(file_path))
    tmp_path = tmp.name
    tmp.close()

    def cleanup():
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    return FileResponse(
        tmp_path,
        media_type="application/zip",
        filename=f"previews_{task_id[:8]}.zip",
        background=BackgroundTask(cleanup),
    )


@app.get("/api/tasks")
async def list_tasks():
    result = []
    for tid, task in tasks.items():
        result.append({
            "id": tid,
            "name": task.get("name", "Unknown"),
            "path": task.get("path", ""),
            "display_path": task.get("display_path", ""),
            "status": task["status"],
            "progress": task["progress"],
            "total_files": task["total_files"],
            "completed_files": task["completed_files"],
            "failed_count": len(task["failed_files"]),
            "results_count": len(task["results"]),
            "start_time": task.get("start_time", 0),
        })
    result.sort(key=lambda t: t.get("start_time", 0), reverse=True)
    return result


@app.get("/api/health")
async def health():
    return {"status": "ok"}


async def _run_task(task_id: str, retry_files: Optional[list] = None):
    task = tasks[task_id]
    files = retry_files if retry_files is not None else task["files"]
    cols, rows = task["grid_cols"], task["grid_rows"]
    tw, th = task["thumb_width"], task["thumb_height"]
    sem = get_semaphore()
    hw_info = get_hwaccel()

    # Initialize per-file status tracking
    if "file_statuses" not in task:
        task["file_statuses"] = {}
    if "file_errors" not in task:
        task["file_errors"] = {}

    if retry_files is None:
        # First run: init all files as pending
        for f in task["files"]:
            task["file_statuses"][f] = "pending"
        task["file_errors"].clear()
    else:
        # Retry: reset failed files back to pending
        for f in retry_files:
            task["file_statuses"][f] = "pending"
            task["file_errors"].pop(f, None)

    async def process_one(video_path: str):
        if task["cancelled"]:
            return
        task["current_file"] = video_path
        task["file_statuses"][video_path] = "processing"
        try:
            async with sem:
                output, error = await _generate_preview(
                    video_path, cols, rows, tw, th, task, hw_info
                )
            if output:
                task["file_statuses"][video_path] = "success"
                task["results"].append(output)
                task["completed_files"] += 1
            else:
                task["file_statuses"][video_path] = "failed"
                task["file_errors"][video_path] = error or "Unknown error"
                task["failed_files"].append(video_path)
        except Exception as e:
            err_msg = str(e)[:500]
            logger.error(f"Error processing {video_path}: {e}")
            task["file_statuses"][video_path] = "failed"
            task["file_errors"][video_path] = err_msg
            task["failed_files"].append(video_path)

        done = task["completed_files"] + len(task["failed_files"])
        task["progress"] = int(done / task["total_files"] * 100)

    pending = []
    for video_path in files:
        if task["cancelled"]:
            break
        pending.append(asyncio.create_task(process_one(video_path)))

    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    task["status"] = "completed" if not task["cancelled"] else "cancelled"
    task["current_file"] = ""
    task["process"] = None


async def _generate_preview(
    video_path: str, cols: int, rows: int,
    tw: int, th: int, task: dict, hw_info: Optional[dict] = None
) -> tuple[Optional[str], str]:
    video = Path(video_path)
    output_path = video.parent / f"{video.stem}.jpg"

    duration = await _get_duration(video_path)
    if duration is None or duration <= 0:
        logger.warning(f"Cannot get duration for {video_path}")
        return None, "Cannot get video duration"

    total_frames = cols * rows
    interval = max(0.5, duration / total_frames)

    cmd = ["ffmpeg", "-y"]

    # 对 HW 路径：只解码关键帧（大幅加速），hwdownload 在 fps 之前（fps 不接受 VAAPI 帧）
    if hw_info and hw_info["type"] in ("vaapi", "cuda", "d3d11va"):
        cmd += ["-skip_frame", "nokey"]
        cmd += hw_info["args"]
        cmd += ["-i", video_path]
        vf_parts = ["hwdownload,format=nv12", f"fps=1/{interval}",
                     f"scale={tw}:{th}"]
    else:
        if hw_info and hw_info["args"]:
            cmd += hw_info["args"]
        cmd += ["-i", video_path]
        vf_parts = [f"fps=1/{interval}", f"scale={tw}:{th}"]

    if task.get("show_timestamps"):
        font = get_font()
        if font:
            vf_parts.append(
                f"drawtext=text='%{{pts\\:hms}}':"
                f"fontfile={font}:"
                f"fontsize=10:fontcolor=white:"
                f"box=1:boxcolor=black@0.5:"
                f"x=4:y=H-th-4"
            )
        else:
            logger.warning("No font found for drawtext, skipping timestamps")
    vf_parts += [f"tile={cols}x{rows}"]
    cmd += ["-vf", ",".join(vf_parts)]

    cmd += ["-frames:v", "1", "-update", "1", "-q:v", "3", str(output_path)]

    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    task["process"] = process

    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=3600)
        if process.returncode == 0 and output_path.exists():
            logger.info(f"Generated preview: {output_path}")
            return str(output_path), ""
        else:
            err = (stderr.decode()[:500] if stderr else "unknown error")
            logger.error(f"ffmpeg error for {video_path}: {err}")
            return None, err
    except asyncio.TimeoutError:
        msg = "ffmpeg timeout after 3600s"
        logger.error(f"{msg} for {video_path}")
        try:
            process.kill()
        except Exception:
            pass
        return None, msg
    finally:
        task["process"] = None


async def _get_duration(video_path: str) -> Optional[float]:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, _ = await proc.communicate()
        if out:
            return float(out.decode().strip())
    except Exception:
        pass
    return None


STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
