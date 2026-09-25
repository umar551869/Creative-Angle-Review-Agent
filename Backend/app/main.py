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

from typing import Optional

from fastapi import (Depends, FastAPI, File as FileParam, Form, HTTPException,
                     Path as PathParam, Request, UploadFile)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from app import media
from app.config import get_settings
from app.jobs import get_store
from app.logging_setup import setup_logging
from app.middleware import (BodySizeLimitMiddleware, RequestContextMiddleware)
from app.schemas import (AnalyzeRequest, BriefCompileRequest, BriefOut,
                         JobAccepted, JobOut)
from app.security import auth_mode, configured_keys, require_key
from app.services import pipeline
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
    # BEFORE anything else looks for it. This both reports ffmpeg and, when it
    # is installed somewhere this process's PATH does not cover, makes it
    # runnable for the subprocesses Phase 1 spawns.
    _media = media.status()
    log.info('ffmpeg: %s | ffprobe: %s',
             _media['ffmpeg'] or 'NOT FOUND', _media['ffprobe'] or 'NOT FOUND')
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
                   max_bytes=settings.max_body_bytes,
                   upload_paths=('/analyze/upload',),
                   upload_max_bytes=settings.max_upload_bytes)
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
    _media = media.status()
    body = {
        'ready': bool(ns_ready and not problems and _STATE['accepting']),
        'namespace': _STATE['namespace'],
        'model_probe': _STATE['probe'],
        'vision_models': _STATE['probe_detail'] or None,
        # Named explicitly: "ready: false" with a paragraph of prose is a
        # worse diagnostic than one line saying which binary is missing.
        'ffmpeg': _media['ffmpeg'],
        'ffprobe': _media['ffprobe'],
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
def _guard_new_job(*, n_videos: int, brief_url, brief_text,
                   compiled_brief) -> None:
    """Everything that must hold before a job is created, for EITHER entry.

    Shared between /analyze and /analyze/upload deliberately. When these lived
    only in /analyze, a second entry point was one forgotten check away from
    accepting work with no brief, past the queue ceiling, or with no API key --
    and each of those fails deep inside a worker minutes later instead of at
    the request.
    """
    if not _STATE['accepting']:
        raise HTTPException(503, 'this instance is shutting down')
    if _STATE['namespace'] != 'ready':
        raise HTTPException(503, 'still starting up -- poll /ready')
    if not brief_url and not brief_text and not compiled_brief:
        raise HTTPException(
            422, 'give brief_url (a Google Docs link shared "anyone with the '
                 'link can view"), brief_text, or compiled_brief (the '
                 '`compiled_brief` a previous job returned).')
    if brief_url and brief_text:
        raise HTTPException(
            422, 'brief_url and brief_text are mutually exclusive.')
    if n_videos > settings.max_videos_per_job:
        raise HTTPException(
            422, f'{n_videos} videos exceeds the per-job ceiling '
                 f'of {settings.max_videos_per_job}. Raise '
                 f'AUDITOR_MAX_VIDEOS deliberately, or split the request.')
    if not settings.gemini_api_key:
        raise HTTPException(
            503, 'GEMINI_API_KEY is not set. Vision, brief compilation and '
                 'L3 adjudication all need it and there is no local '
                 'fallback in this deployment.')
    depth = get_store().queue_depth()
    if depth >= settings.max_queued_jobs:
        raise HTTPException(
            429, f'{depth} job(s) already queued or running, at the ceiling '
                 f'of {settings.max_queued_jobs}. Each job takes minutes; '
                 f'poll your existing jobs before adding more.')


@app.post('/analyze', response_model=JobAccepted, status_code=202,
          tags=['audit'], dependencies=[Depends(require_key)])
def analyze(req: AnalyzeRequest) -> JobAccepted:
    """Queue an audit of one or more videos against one brief.

    The server downloads each URL. If your videos are already on disk -- or
    TikTok refuses this server's IP, which is common from a datacentre -- post
    the files to `/analyze/upload` instead.
    """
    _guard_new_job(n_videos=len(req.video_urls), brief_url=req.brief_url,
                   brief_text=req.brief_text,
                   compiled_brief=req.compiled_brief)
    store = get_store()
    job = store.create(req.model_dump())
    store.submit(job)
    log.info('[%s] accepted: %d video(s) by URL', job.id, len(req.video_urls))
    return JobAccepted(job_id=job.id, status='queued',
                       poll=f'/jobs/{job.id}')


@app.post('/analyze/upload', response_model=JobAccepted, status_code=202,
          tags=['audit'], dependencies=[Depends(require_key)])
async def analyze_upload(
    files: list[UploadFile] = FileParam(
        ..., description='The video files themselves. Name each one after its '
                         'video id (e.g. 7671762950687919390.mp4) and the '
                         'report can still show which link it came from.'),
    brief_url: Optional[str] = Form(None),
    brief_text: Optional[str] = Form(None),
    compiled_brief: Optional[str] = Form(
        None, description='A previous job\'s `compiled_brief`, as a JSON '
                          'string. Multipart cannot nest an object.'),
    source_urls: Optional[str] = Form(
        None, description='JSON array of the original links, for provenance '
                          'only. Nothing is fetched from them.'),
    force_reaudit: bool = Form(False),
    recompile: bool = Form(False),
    label: Optional[str] = Form(None, max_length=120),
) -> JobAccepted:
    """Queue an audit of UPLOADED videos against one brief.

    The same pipeline as `/analyze`; only the way the bytes arrive differs. Use
    this when the client already has the video -- it removes the single least
    reliable stage of a deployed run, since TikTok refuses anonymous downloads
    from datacentre IPs far more readily than from residential ones.

    Everything else is identical: `brief_url`, `brief_text` or
    `compiled_brief`, then poll `GET /jobs/{id}`.
    """
    # Parse the JSON-in-multipart fields BEFORE creating anything, so a
    # malformed body never leaves a job directory behind.
    parsed_brief = _form_json(compiled_brief, 'compiled_brief', dict)
    # Strings only. These reach `url_for_source`, which regexes each entry;
    # a JSON array containing a number would TypeError there -- in the worker,
    # minutes later, instead of here.
    parsed_urls = [str(u) for u in (_form_json(source_urls, 'source_urls',
                                               list) or []) if u]

    _guard_new_job(n_videos=len(files), brief_url=brief_url,
                   brief_text=brief_text, compiled_brief=parsed_brief)
    if not files:
        raise HTTPException(422, 'attach at least one video file as `files`.')

    store = get_store()
    job = store.create({
        'video_urls': [], 'uploads': [], 'source_urls': parsed_urls,
        'brief_url': brief_url, 'brief_text': brief_text,
        'compiled_brief': parsed_brief, 'force_reaudit': force_reaudit,
        'recompile': recompile, 'label': label,
    })
    # job_dirs() is the SAME function the worker binds DIRS from, so the
    # staging path and the path Phase 1 reads cannot drift apart.
    inbox = runtime.job_dirs(job.id, ephemeral=settings.ephemeral)['inbox']
    try:
        saved = await _stage_uploads(files, inbox)
    except HTTPException:
        store.discard(job)
        raise
    except Exception as exc:
        store.discard(job)
        log.exception('[%s] upload staging failed', job.id)
        raise HTTPException(400, f'could not stage the upload: {exc}') from exc

    job.payload['uploads'] = saved
    job.requested_videos = len(saved)
    job.persist()
    store.submit(job)
    log.info('[%s] accepted: %d uploaded video(s)', job.id, len(saved))
    return JobAccepted(job_id=job.id, status='queued',
                       poll=f'/jobs/{job.id}')


def _form_json(raw: Optional[str], field: str, want: type):
    """Decode a JSON object smuggled through a multipart form field."""
    if raw is None or not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(
            422, f'{field} is not valid JSON: {exc}') from exc
    if not isinstance(value, want):
        raise HTTPException(
            422, f'{field} must be a JSON {want.__name__}, got '
                 f'{type(value).__name__}.')
    return value


async def _stage_uploads(files: list, inbox: Path) -> list[str]:
    """Stream each upload to the job's inbox, enforcing the real size limit.

    STREAMED IN CHUNKS, never read whole. `await file.read()` with no argument
    buffers the entire video in memory, and on a container sized for this
    pipeline a handful of concurrent uploads would be the whole RAM budget.

    The size limit is enforced HERE, on bytes actually written, not only by the
    middleware: the middleware checks a declared content-length, and a chunked
    request declares nothing. A partial write is deleted rather than left for
    Phase 1 to trip over -- a truncated mp4 decodes as a corrupt artifact, not
    as a clean error.
    """
    from app.services import ingest

    inbox.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    total = 0
    for upload in files:
        try:
            name = ingest.safe_upload_name(upload.filename, set(saved))
        except ingest.IngestError as exc:
            raise HTTPException(422, str(exc)) from exc

        dest = inbox / name
        written = 0
        try:
            with dest.open('wb') as out:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    total += len(chunk)
                    if written > settings.max_video_bytes:
                        raise HTTPException(
                            413,
                            f'{name} exceeds AUDITOR_MAX_VIDEO_BYTES '
                            f'({settings.max_video_bytes / 1048576:.0f} MB). '
                            f'Short-form video is 5-30 MB; this is either the '
                            f'wrong file or needs the limit raised '
                            f'deliberately.')
                    if total > settings.max_upload_bytes:
                        raise HTTPException(
                            413,
                            f'this request exceeds AUDITOR_MAX_UPLOAD_BYTES '
                            f'({settings.max_upload_bytes / 1048576:.0f} MB) '
                            f'in total. Send fewer files per request.')
                    out.write(chunk)
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()

        if not written:
            dest.unlink(missing_ok=True)
            raise HTTPException(422, f'{name} is empty (0 bytes).')
        try:
            kind = ingest.validate_video_file(dest)
        except ingest.IngestError as exc:
            dest.unlink(missing_ok=True)
            raise HTTPException(422, str(exc)) from exc
        log.info('staged %s (%.1f MB, %s)', name, written / 1e6, kind)
        saved.append(name)
    return saved


_REPORTS_STAY_LOCAL = ('reports are kept on the host and are not served '
                       'through the public URL; GET /jobs/{id} gives the '
                       'angle groups')


def _through_tunnel(request: Request) -> bool:
    """Did this request arrive through the public tunnel?

    ngrok and cloudflared both add X-Forwarded-For (cloudflared also
    Cf-Connecting-Ip); a caller on the far side cannot strip them. A request
    made on this machine carries neither.
    """
    h = request.headers
    return any(k in h for k in ('x-forwarded-for', 'cf-connecting-ip',
                                'forwarded'))


def _angles_only(request: Request) -> bool:
    return settings.public_view == 'angles' and _through_tunnel(request)


@app.get('/jobs/{job_id}', response_model=JobOut, tags=['audit'],
         dependencies=[Depends(require_key)])
def get_job(request: Request,
            job_id: str = PathParam(..., min_length=8, max_length=64,
                                    pattern=r'^[A-Za-z0-9_-]+$')) -> JobOut:
    job = get_store().get(job_id)
    if job is None:
        raise HTTPException(404, f'no job {job_id}')
    d = job.to_dict()
    # Only once the job is over: mid-run, a link with no row yet is not lost.
    done = job.status in ('succeeded', 'partial', 'failed')
    groups, unplaced = pipeline.angle_groups(
        job.results,
        submitted=d.get('video_urls') if done else None,
        failed=job.failed_urls, job_error=job.error)
    d.update(angles={g['angle']: g['videos'] for g in groups},
             angle_groups=groups, unplaced=unplaced)
    if _angles_only(request):
        # The answer is which video is which angle. Scores, verdicts, the
        # brief as compiled and the reports stay on this machine.
        d.update(view='angles', results=[], brief=None, compiled_brief=None,
                 angle_distribution=[], timings=[])
    return JobOut(**d)


@app.get('/jobs', tags=['audit'], dependencies=[Depends(require_key)])
def list_jobs(limit: int = 25) -> list[dict]:
    return [{'job_id': j.id, 'status': j.status, 'phase': j.phase,
             'label': j.label, 'created_at': j.created_at,
             'videos': j.requested_videos}
            for j in get_store().list(max(1, min(limit, 200)))]


@app.get('/jobs/{job_id}/report/{filename}', tags=['audit'],
         dependencies=[Depends(require_key)])
def get_report(request: Request,
               job_id: str = PathParam(..., min_length=8, max_length=64,
                                       pattern=r'^[A-Za-z0-9_-]+$'),
               filename: str = PathParam(..., max_length=128,
                                         pattern=r'^[A-Za-z0-9._-]+$')):
    """The HTML report, served as the self-contained file it already is.

    `job_id` is PATTERNED, like it is on GET /jobs/{id}. Without that, a
    percent-encoded `..%2f..%2f` decodes into the path used to locate
    jobs/<id>/job.json and reads outside the data root. The report path itself
    comes from our own result row and is re-checked below, so this closes the
    one parameter that reached the filesystem unvalidated.
    """
    if _angles_only(request):
        raise HTTPException(403, _REPORTS_STAY_LOCAL)
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
def get_reports_zip(request: Request,
                    job_id: str = PathParam(..., min_length=8, max_length=64,
                                            pattern=r'^[A-Za-z0-9_-]+$')):
    """Every report from this job, in one archive.

    Each file is renamed after its VIDEO rather than its content hash -- a
    reviewer works from filenames, and `report__edb422f3.html` tells them
    nothing about which creator it belongs to.
    """
    import io
    import zipfile

    from fastapi.responses import StreamingResponse

    if _angles_only(request):
        raise HTTPException(403, _REPORTS_STAY_LOCAL)
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
