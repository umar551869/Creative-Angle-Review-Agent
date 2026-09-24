"""FastAPI application.

    uvicorn app.main:app --host 0.0.0.0 --port 8000

RUN ONE WORKER PROCESS. The job store and the loaded pipeline namespace live
in this process; `--workers 4` gives you four independent stores, four model
loads, and four times the configured concurrency. Scale by running more
CONTAINERS behind a load balancer, with a shared AUDITOR_DATA_ROOT -- the
artifact store is content-addressed, so that works. Startup refuses to be
quiet about it.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Path as PathParam
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from app.config import get_settings
from app.jobs import get_store
from app.logging_setup import setup_logging
from app.middleware import (BodySizeLimitMiddleware, RequestContextMiddleware)
from app.schemas import (AnalyzeRequest, BriefCompileRequest, BriefOut,
                         JobAccepted, JobOut)
from app.security import auth_mode, configured_keys, require_key
from auditor import runtime

log = logging.getLogger('audit.api')
settings = get_settings()
setup_logging(settings)

# Readiness is not liveness. The process is ALIVE as soon as it can answer;
# it is READY only once the pipeline namespace is in memory and the model
# probe has finished. Conflating them makes a platform kill a container that
# is merely still starting.
_STATE: dict[str, object] = {
    'namespace': 'pending', 'probe': 'pending', 'started_at': time.time(),
    'probe_detail': '', 'accepting': True,
}


def _probe_models() -> None:
    """Notebook cells 68 and 88, once, off the startup path.

    Both send a LIVE request to pick a model that actually works, and the
    vision probe alone measured 25-30 s. Blocking startup on that fails the
    health check of every platform that has one, so it runs in a thread and
    `/ready` reports it.
    """
    ns = runtime.load()
    if settings.vision_model:
        # A PIN, so the visual cache key stops moving. autoselect honours it
        # and still appends the other candidates as fallbacks.
        ns['PIN_VISION_MODEL'] = settings.vision_model
        log.info('vision model PINNED to %s -- the visual cache key is stable '
                 'across runs', settings.vision_model)
    try:
        t = time.time()
        ns['P3'] = ns['replace'](
            ns['P3'], vision=ns['autoselect_vision_model'](
                ns['P3'].vision, verbose=False))
        models = list(ns['P3'].vision.gemini_models)
        log.info('vision ladder: %s (%.0fs)', models, time.time() - t)
        _STATE['probe_detail'] = ', '.join(models)
    except Exception as exc:
        log.warning('vision probe failed (%s) -- keeping the configured '
                    'model', type(exc).__name__)
        _STATE['probe_detail'] = f'probe failed: {type(exc).__name__}'
    try:
        ns['P4'] = ns['replace'](
            ns['P4'], brief=ns['autoselect_hosted_model'](
                ns['P4'].brief, verbose=False))
        log.info('text model: %s', ns['P4'].brief.hosted_model)
    except Exception as exc:
        log.warning('text probe failed (%s)', type(exc).__name__)
    _STATE['probe'] = 'done'


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # RESET. _STATE is module-level and the shutdown path sets accepting=False;
    # anything that starts the app a second time in one process -- a reload, a
    # test suite -- would otherwise come up permanently refusing work with a
    # 503 that looks like a dependency failure.
    _STATE.update(accepting=True, started_at=time.time())
    log.info('settings: %s', settings.redacted())
    log.info('auth: %s', auth_mode())
    if not configured_keys():
        log.warning('NO API KEY CONFIGURED. Anyone who can reach this port '
                    'can submit jobs and spend your model quota. Set '
                    'AUDITOR_API_KEYS before exposing it.')
    for p in settings.missing_requirements():
        log.error('STARTUP PROBLEM: %s', p)

    workers = os.environ.get('WEB_CONCURRENCY') or os.environ.get(
        'UVICORN_WORKERS')
    if workers and workers.isdigit() and int(workers) > 1:
        log.error('WEB_CONCURRENCY=%s. This app keeps its job store and its '
                  'model namespace IN PROCESS -- N workers means N stores and '
                  'N model loads. Run one worker per container and scale by '
                  'adding containers with a shared AUDITOR_DATA_ROOT.',
                  workers)

    t = time.time()
    ns = runtime.load()
    _STATE['namespace'] = 'ready'
    log.info('pipeline namespace loaded: %d names in %.1fs',
             len(ns), time.time() - t)

    if settings.probe_models_on_startup and settings.gemini_api_key:
        threading.Thread(target=_probe_models, name='model-probe',
                         daemon=True).start()
    else:
        _STATE['probe'] = 'skipped'

    yield

    # ---- shutdown --------------------------------------------------------
    # Stop taking work, then give what is running a bounded chance to finish.
    # A job killed mid-stage leaves half-written artifacts that a
    # content-addressed cache cannot tell from good ones.
    _STATE['accepting'] = False
    get_store().shutdown(grace_s=settings.shutdown_grace_s)
    log.info('shutdown complete')


app = FastAPI(
    title=settings.api_title,
    version='1.0.0',
    lifespan=lifespan,
    description=(
        'Audits short-form social video against a content brief.\n\n'
        'Phases 1-7 of the notebook pipeline, unchanged: decode and sample '
        'frames, transcribe, read on-screen text, describe the frames with a '
        'hosted vision model, compile the brief into requirements, assemble '
        'timestamped evidence, judge each requirement on a three-rung ladder, '
        'and score it **by arithmetic** -- no model ever writes a number.\n\n'
        'Runs are long (a cold three-video job is 5-12 minutes), so '
        '`POST /analyze` returns a job id and you poll `GET /jobs/{id}`.'),
)

app.add_middleware(RequestContextMiddleware)
app.add_middleware(BodySizeLimitMiddleware,
                   max_bytes=settings.max_body_bytes)
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=['GET', 'POST'],
        allow_headers=['content-type', 'x-api-key', 'authorization'],
    )


# ---------------------------------------------------------------------------
# ops -- no auth, because a load balancer cannot present a key
# ---------------------------------------------------------------------------
@app.get('/health', tags=['ops'])
def health() -> dict:
    """LIVENESS. Cheap, never touches a model. 200 = the process is alive."""
    return {'status': 'ok',
            'uptime_s': round(time.time() - float(_STATE['started_at']), 1)}


@app.get('/ready', tags=['ops'])
def ready():
    """READINESS. 503 until this instance can actually serve a job."""
    problems = settings.missing_requirements()
    ns_ready = _STATE['namespace'] == 'ready'
    body = {
        'ready': bool(ns_ready and not problems and _STATE['accepting']),
        'namespace': _STATE['namespace'],
        'model_probe': _STATE['probe'],
        'vision_models': _STATE['probe_detail'] or None,
        'accepting_work': _STATE['accepting'],
        'auth': auth_mode(),
        'problems': problems,
    }
    return JSONResponse(body, status_code=200 if body['ready'] else 503)


@app.get('/metrics', tags=['ops'], response_class=PlainTextResponse)
def metrics() -> str:
    """Prometheus text format. No dependency, no scrape library."""
    jobs = get_store().list(limit=1000)
    counts: dict[str, int] = {}
    for j in jobs:
        counts[j.status] = counts.get(j.status, 0) + 1
    lines = [
        '# HELP audit_up 1 when the pipeline namespace is loaded',
        '# TYPE audit_up gauge',
        f'audit_up {1 if _STATE["namespace"] == "ready" else 0}',
        '# HELP audit_uptime_seconds Seconds since process start',
        '# TYPE audit_uptime_seconds gauge',
        f'audit_uptime_seconds {time.time() - float(_STATE["started_at"]):.0f}',
        '# HELP audit_jobs_total Jobs by terminal status',
        '# TYPE audit_jobs_total gauge',
    ]
    for status in ('queued', 'running', 'succeeded', 'partial', 'failed'):
        lines.append(f'audit_jobs_total{{status="{status}"}} '
                     f'{counts.get(status, 0)}')
    videos = sum(j.completed_videos for j in jobs)
    lines += ['# HELP audit_videos_completed_total Videos audited',
              '# TYPE audit_videos_completed_total counter',
              f'audit_videos_completed_total {videos}']
    return '\n'.join(lines) + '\n'


@app.get('/config', tags=['ops'],
         dependencies=[Depends(require_key)])
def config() -> dict:
    """Effective settings. Keys appear as a length, never a value."""
    return settings.redacted()


# ---------------------------------------------------------------------------
@app.post('/analyze', response_model=JobAccepted, status_code=202,
          tags=['audit'], dependencies=[Depends(require_key)])
def analyze(req: AnalyzeRequest) -> JobAccepted:
    """Queue an audit of one or more videos against one brief."""
    if not _STATE['accepting']:
        raise HTTPException(503, 'this instance is shutting down')
    if _STATE['namespace'] != 'ready':
        raise HTTPException(503, 'still starting up -- poll /ready')
    if not req.brief_url and not req.brief_text and not req.compiled_brief:
        raise HTTPException(
            422, 'give brief_url (a Google Docs link shared "anyone with the '
                 'link can view"), brief_text, or compiled_brief (the '
                 '`compiled_brief` a previous job returned).')
    if req.brief_url and req.brief_text:
        raise HTTPException(
            422, 'brief_url and brief_text are mutually exclusive.')
    if len(req.video_urls) > settings.max_videos_per_job:
        raise HTTPException(
            422, f'{len(req.video_urls)} videos exceeds the per-job ceiling '
                 f'of {settings.max_videos_per_job}. Raise '
                 f'AUDITOR_MAX_VIDEOS deliberately, or split the request.')
    if not settings.gemini_api_key:
        raise HTTPException(
            503, 'GEMINI_API_KEY is not set. Vision, brief compilation and '
                 'L3 adjudication all need it and there is no local '
                 'fallback in this deployment.')

    store = get_store()
    depth = store.queue_depth()
    if depth >= settings.max_queued_jobs:
        raise HTTPException(
            429, f'{depth} job(s) already queued or running, at the ceiling '
                 f'of {settings.max_queued_jobs}. Each job takes minutes; '
                 f'poll your existing jobs before adding more.')
    job = store.create(req.model_dump())
    store.submit(job)
    log.info('[%s] accepted: %d video(s)', job.id, len(req.video_urls))
    return JobAccepted(job_id=job.id, status='queued',
                       poll=f'/jobs/{job.id}')


@app.get('/jobs/{job_id}', response_model=JobOut, tags=['audit'],
         dependencies=[Depends(require_key)])
def get_job(job_id: str = PathParam(..., min_length=8, max_length=64,
                                    pattern=r'^[A-Za-z0-9_-]+$')) -> JobOut:
    job = get_store().get(job_id)
    if job is None:
        raise HTTPException(404, f'no job {job_id}')
    return JobOut(**job.to_dict())


@app.get('/jobs', tags=['audit'], dependencies=[Depends(require_key)])
def list_jobs(limit: int = 25) -> list[dict]:
    return [{'job_id': j.id, 'status': j.status, 'phase': j.phase,
             'label': j.label, 'created_at': j.created_at,
             'videos': j.requested_videos}
            for j in get_store().list(max(1, min(limit, 200)))]


@app.get('/jobs/{job_id}/report/{filename}', tags=['audit'],
         dependencies=[Depends(require_key)])
def get_report(job_id: str, filename: str):
    """The HTML report, served as the self-contained file it already is."""
    job = get_store().get(job_id)
    if job is None:
        raise HTTPException(404, f'no job {job_id}')
    video_id, _, ext = filename.rpartition('.')
    if ext not in ('html', 'json'):
        raise HTTPException(400, 'expected .html or .json')
    row = next((r for r in job.results if r.get('video_id') == video_id), None)
    if row is None:
        raise HTTPException(404, f'job {job_id} has no video {video_id}')
    # The path comes from OUR OWN result row, never from the URL, so the
    # caller cannot steer this at an arbitrary file. Re-checked anyway.
    path = Path(row.get(f'report_{ext}') or '')
    try:
        path.resolve().relative_to(settings.data_root.resolve())
    except (ValueError, OSError):
        raise HTTPException(404, 'report is not inside the data root')
    if not path.is_file():
        raise HTTPException(
            404, f'the {ext} report was not produced for {video_id}. '
                 f'status={row.get("status")!r}')
    return FileResponse(
        path, media_type='text/html' if ext == 'html' else 'application/json',
        filename=f'{row.get("source", video_id)}.{ext}')


@app.get('/jobs/{job_id}/reports.zip', tags=['audit'],
         dependencies=[Depends(require_key)])
def get_reports_zip(job_id: str):
    """Every report from this job, in one archive.

    Each file is renamed after its VIDEO rather than its content hash -- a
    reviewer works from filenames, and `report__edb422f3.html` tells them
    nothing about which creator it belongs to.
    """
    import io
    import zipfile

    from fastapi.responses import StreamingResponse

    job = get_store().get(job_id)
    if job is None:
        raise HTTPException(404, f'no job {job_id}')
    reports = [(r, Path(r.get('report_html') or '')) for r in job.results]
    reports = [(r, p) for r, p in reports if p.is_file()]
    if not reports:
        raise HTTPException(
            404, f'job {job_id} produced no report yet (status={job.status})')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for row, path in reports:
            stem = Path(row.get('source') or row.get('video_id') or '')
            z.write(path, f'{stem.stem[:48] or "video"}__{path.name}')
        z.writestr('summary.json', json.dumps({
            'job_id': job.id, 'label': job.label,
            'brief': job.brief, 'results': job.results,
            'angle_distribution': job.angle_distribution}, indent=2,
            default=str))
    buf.seek(0)
    return StreamingResponse(
        buf, media_type='application/zip',
        headers={'content-disposition':
                 f'attachment; filename="reports_{job_id}.zip"'})


# ---------------------------------------------------------------------------
@app.post('/briefs/compile', response_model=BriefOut, tags=['brief'],
          dependencies=[Depends(require_key)])
def compile_brief_endpoint(req: BriefCompileRequest) -> BriefOut:
    """Compile a brief on its own, to inspect the requirements before running
    videos against them.

    The first compile of a given brief text is FROZEN: later /analyze calls
    reuse it, so two videos are always measured against the same contract.
    `recompile: true` replaces it deliberately -- after which scores are no
    longer comparable with earlier runs.
    """
    from app.services import ingest

    if not req.brief_url and not req.brief_text:
        raise HTTPException(422, 'give either brief_url or brief_text.')
    try:
        loaded = ingest.load_brief(brief_url=req.brief_url,
                                   brief_text=req.brief_text)
        compiled = ingest.compile_brief(
            loaded['text'], runs=settings.brief_compile_runs,
            keep_threshold=settings.brief_keep_threshold,
            recompile=req.recompile)
    except ingest.IngestError as exc:
        raise HTTPException(422, str(exc)) from exc
    return BriefOut(**ingest.brief_summary(compiled, loaded['origin']))


# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
def _unhandled(request, exc: Exception):
    """Never turn a specific failure into a generic one -- but never leak a
    stack trace to a caller either. The log has the trace; the caller gets the
    type, the message and the request id to quote."""
    from app.middleware import REQUEST_ID

    log.exception('unhandled error on %s', request.url.path)
    return JSONResponse(
        status_code=500,
        content={'error': type(exc).__name__, 'detail': str(exc)[:500],
                 'path': request.url.path, 'request_id': REQUEST_ID.get()})
