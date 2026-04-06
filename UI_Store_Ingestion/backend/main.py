import asyncio
import queue as queue_module

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from pathlib import Path
import uvicorn
import shutil
import cv2

from homography import compute_homography
from tracker import start_tracking_job, get_job
from heatmap import generate_heatmap
from project_io import save_project, load_project
from pdf_utils import pdf_to_png

app = FastAPI(title='RetailVision Onboarding API')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:5173'],
    allow_methods=['*'],
    allow_headers=['*'],
)

UPLOAD_DIR = Path('uploads')
UPLOAD_DIR.mkdir(exist_ok=True)
(UPLOAD_DIR / 'floorplan').mkdir(exist_ok=True)
(UPLOAD_DIR / 'videos').mkdir(exist_ok=True)
(UPLOAD_DIR / 'heatmaps').mkdir(exist_ok=True)

app.mount('/uploads', StaticFiles(directory='uploads'), name='uploads')


# ── Utility ──────────────────────────────────────────────────────────────────

def _find_video(camera_id: str) -> Path:
    for ext in ['.mp4', '.avi', '.mov', '.mkv']:
        vp = UPLOAD_DIR / 'videos' / f'{camera_id}{ext}'
        if vp.exists():
            return vp
    raise HTTPException(404, f'Video not found for camera {camera_id}')


# ── Health ────────────────────────────────────────────────────────────────────

@app.get('/health')
def health():
    return {'status': 'ok'}


# ── Floor plan ────────────────────────────────────────────────────────────────

@app.post('/api/floorplan/upload')
async def upload_floorplan(file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ['.png', '.jpg', '.jpeg', '.pdf']:
        raise HTTPException(400, 'Only PNG, JPG, or PDF accepted')

    raw_path = UPLOAD_DIR / 'floorplan' / ('raw' + suffix)
    out_path = UPLOAD_DIR / 'floorplan' / 'floorplan.png'

    with open(raw_path, 'wb') as f:
        f.write(await file.read())

    extra = {}
    if suffix == '.pdf':
        w, h, num_pages = pdf_to_png(raw_path, out_path, dpi=150)
        if num_pages > 1:
            extra['notice'] = f'PDF has {num_pages} pages; only page 1 is used.'
    else:
        shutil.copy(raw_path, out_path)
        img = cv2.imread(str(out_path))
        h, w = img.shape[:2]

    return {'url': '/uploads/floorplan/floorplan.png', 'width': w, 'height': h, **extra}


# ── Video ─────────────────────────────────────────────────────────────────────

@app.post('/api/video/upload/{camera_id}')
async def upload_video(camera_id: str, file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ['.mp4', '.avi', '.mov', '.mkv']:
        raise HTTPException(400, 'Unsupported video format')

    out_path = UPLOAD_DIR / 'videos' / f'{camera_id}{suffix}'
    with open(out_path, 'wb') as f:
        f.write(await file.read())

    cap = cv2.VideoCapture(str(out_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if fps > 0 else 0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    return {
        'videoPath': str(out_path),
        'duration': round(duration, 2),
        'fps': round(fps, 2),
        'frameCount': frame_count,
        'width': width,
        'height': height,
    }


@app.get('/api/video/frame/{camera_id}')
def get_video_frame(camera_id: str, timestamp_sec: float = 0.0):
    video_path = _find_video(camera_id)
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(timestamp_sec * fps))
    ret, frame = cap.read()
    cap.release()
    if not ret:
        raise HTTPException(400, 'Could not read frame at given timestamp')
    _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return Response(content=buf.tobytes(), media_type='image/jpeg')


# ── Homography ────────────────────────────────────────────────────────────────

class CorrespondenceRequest(BaseModel):
    camera_id: str
    cam_points: list
    floor_points: list


@app.post('/api/homography/compute')
def api_compute_homography(req: CorrespondenceRequest):
    return compute_homography(req.cam_points, req.floor_points)


# ── Tracking — streaming pipeline ─────────────────────────────────────────────

class TrackingStartRequest(BaseModel):
    homography_matrix: list   # 3×3 nested list
    zones: list
    model_size: str = 'n'
    pixels_per_meter: float
    origin_px: dict           # {x, y}


@app.post('/api/tracking/start/{camera_id}')
def api_start_tracking(camera_id: str, req: TrackingStartRequest):
    """
    Start a background tracking job and return immediately.
    The client then opens the MJPEG stream and polls /progress.
    """
    video_path = _find_video(camera_id)
    heatmap_path = UPLOAD_DIR / 'heatmaps' / f'{camera_id}.png'
    floor_plan_path = UPLOAD_DIR / 'floorplan' / 'floorplan.png'

    job = start_tracking_job(
        camera_id=camera_id,
        video_path=video_path,
        homography_matrix=req.homography_matrix,
        zones=req.zones,
        model_size=req.model_size,
        pixels_per_meter=req.pixels_per_meter,
        origin_px=req.origin_px,
        floor_plan_path=floor_plan_path,
        heatmap_output_path=heatmap_path,
    )
    return {
        'status': 'started',
        'cameraId': camera_id,
        'totalFrames': job['total_frames'],
        'fps': job['fps'],
    }


@app.get('/api/tracking/stream/{camera_id}')
async def api_stream_tracking(camera_id: str):
    """
    MJPEG stream of annotated video frames produced by the background tracking job.
    Connect an <img> tag directly to this URL; the browser handles the stream natively.
    """
    job = get_job(camera_id)
    if not job:
        raise HTTPException(404, 'No tracking job for this camera. Call /start first.')

    async def mjpeg_generator():
        loop = asyncio.get_event_loop()
        q = job['frame_queue']

        while True:
            # Blocking queue.get in a thread-pool so we don't block the event loop
            try:
                msg_type, data = await loop.run_in_executor(
                    None, lambda: q.get(timeout=5.0)
                )
            except Exception:
                # Timeout — check if job finished
                if job['status'] in ('done', 'error'):
                    break
                continue

            if msg_type in ('done', 'error'):
                break

            # Encode annotated frame as JPEG
            _, buf = cv2.imencode('.jpg', data, [cv2.IMWRITE_JPEG_QUALITY, 80])
            frame_bytes = buf.tobytes()
            yield (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n'
                b'Content-Length: ' + str(len(frame_bytes)).encode() + b'\r\n'
                b'\r\n' + frame_bytes + b'\r\n'
            )

    return StreamingResponse(
        mjpeg_generator(),
        media_type='multipart/x-mixed-replace; boundary=frame',
        headers={
            'Cache-Control': 'no-cache, no-store',
            'X-Accel-Buffering': 'no',   # disable nginx buffering if behind a proxy
        },
    )


@app.get('/api/tracking/progress/{camera_id}')
def api_tracking_progress(camera_id: str):
    """
    Poll this endpoint while streaming to get live status, progress, and
    zone occupancy.  When status == 'done', also returns full trajectory and
    the heatmap URL.
    """
    job = get_job(camera_id)
    if not job:
        raise HTTPException(404, 'No tracking job for this camera')

    total = job['total_frames']
    processed = job['processed_frames']
    progress = round(processed / total, 4) if total > 0 else 0.0

    payload = {
        'status': job['status'],
        'progress': progress,
        'processedFrames': processed,
        'totalFrames': total,
        'zoneOccupancy': job['zone_occupancy'],
        'error': job.get('error'),
        'heatmapUrl': job.get('heatmap_url'),
        # Only send heavy trajectory data once tracking is complete
        'trajectoryMeters': job['trajectory_meters'] if job['status'] == 'done' else None,
        'trajectoryPixels': job['trajectory_pixels'] if job['status'] == 'done' else None,
    }
    return payload


# ── Project persistence ───────────────────────────────────────────────────────

@app.post('/api/project/save')
async def api_save_project(request: Request):
    data = await request.json()
    save_project(data)
    return {'status': 'saved'}


@app.get('/api/project/load')
def api_load_project():
    data = load_project()
    if data is None:
        raise HTTPException(404, 'No project file found')
    return data


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    uvicorn.run('main:app', host='127.0.0.1', port=8000, reload=True)
