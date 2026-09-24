"""Job store and worker.

WHY ASYNCHRONOUS
----------------
Measured on the real pipeline: the hosted vision pass is 72-240 s PER VIDEO,
the ASR model takes ~50 s to load, and a cold three-video run is 5-12 minutes.
There is no proxy in common use that will hold an HTTP request open that long.
So POST /analyze returns a job_id and the work happens here.

WHY ONE JOB AT A TIME BY DEFAULT
--------------------------------
Phase 2 loads Whisper once, frees it, then loads the OCR engine once; Phase 3
loads the vision backend once. Running two jobs concurrently multiplies those
loads and, on a GPU box, races for VRAM -- which the notebook spent a long time
learning to avoid. AUDITOR_MAX_CONCURRENT_JOBS raises it deliberately.

Jobs live on disk (jobs/<id>/job.json) as well as in memory, so a restart does
not lose the record of what ran.
"""
from __future__ import annotations

import json
import logging
import shutil
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.config import get_settings
from auditor import runtime

log = logging.getLogger('audit.jobs')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class Job:
    def __init__(self, job_id: str, payload: dict):
        self.id = job_id
        self.payload = payload
        self.status = 'queued'
        self.phase = 'queued'
        self.label = payload.get('label')
        self.created_at = _now()
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.t0: Optional[float] = None
        self._t_end: Optional[float] = None
        self.deadline: Optional[float] = None
        # Either links to fetch or files already staged in this job's inbox.
        # The upload route rewrites this after streaming, because it cannot
        # know how many files survived validation until they are written.
        self.requested_videos = len(payload.get('video_urls')
                                    or payload.get('uploads') or [])
        self.downloaded_videos = 0
        self.completed_videos = 0
        self.brief: Optional[dict] = None
        self.compiled_brief: Optional[dict] = None
        self.results: list[dict] = []
        self.angle_distribution: list[dict] = []
        self.timings: list[dict] = []
        self.warnings: list[str] = []
        self.error: Optional[str] = None
        self._lock = threading.Lock()

    # -- progress ---------------------------------------------------------
    def set_phase(self, phase: str, detail: str = '') -> None:
        with self._lock:
            self.phase = phase
        log.info('[%s] phase=%s %s', self.id, phase, detail)

    def time_phase(self, phase: str, seconds: float, detail: str = '') -> None:
        with self._lock:
            self.timings.append({'phase': phase, 'seconds': round(seconds, 2),
                                 'detail': detail or None})

    def warn(self, msg: str) -> None:
        with self._lock:
            self.warnings.append(msg)
        log.warning('[%s] %s', self.id, msg)

    @property
    def elapsed_s(self) -> Optional[float]:
        """Wall clock, which is not the sum of the phase timings.

        An earlier version reconstructed the end as t0 + sum(timings), which
        silently omits every gap between phases -- queueing, the brief fetch
        before the first timed phase, teardown -- and so under-reported a job
        that spent ten minutes waiting. `_t_end` is stamped once, when the
        worker finishes.
        """
        if self.t0 is None:
            return None
        return round((self._t_end or time.time()) - self.t0, 2)

    def to_dict(self) -> dict:
        return {
            'job_id': self.id, 'status': self.status, 'phase': self.phase,
            'label': self.label, 'created_at': self.created_at,
            'started_at': self.started_at, 'finished_at': self.finished_at,
            'elapsed_s': self.elapsed_s,
            'requested_videos': self.requested_videos,
            'downloaded_videos': self.downloaded_videos,
            'completed_videos': self.completed_videos,
            'brief': self.brief, 'compiled_brief': self.compiled_brief,
            'results': self.results,
            'angle_distribution': self.angle_distribution,
            'timings': self.timings, 'warnings': self.warnings,
            'error': self.error,
        }

    def persist(self) -> None:
        s = get_settings()
        d = s.jobs / self.id
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / 'job.json.tmp'
        # Atomic: a poller must never read a half-written job record.
        tmp.write_text(json.dumps(self.to_dict(), indent=1, default=str),
                       encoding='utf-8')
        tmp.replace(d / 'job.json')


# Fields a restored record may set. An EXPLICIT list, because the previous
# version looped over the JSON and setattr'd anything the object had an
# attribute for -- which includes `elapsed_s`, a read-only property, so
# restoring any finished job raised AttributeError and GET /jobs/{id} returned
# 500 for every job that survived a restart. hasattr() is True for a property;
# it says nothing about whether you may assign to it.
_RESTORABLE = ('status', 'phase', 'label', 'created_at', 'started_at',
               'finished_at', 'requested_videos', 'downloaded_videos',
               'completed_videos', 'brief', 'results', 'angle_distribution',
               'timings', 'warnings', 'error')


def _restore(job_id: str) -> Optional[Job]:
    """Rebuild a Job from jobs/<id>/job.json. Read-only: never resubmitted."""
    p = get_settings().jobs / job_id / 'job.json'
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding='utf-8'))
    except Exception as exc:
        log.warning('job %s: unreadable record (%s)', job_id, exc)
        return None
    job = Job(job_id, {'video_urls': [], 'label': raw.get('label')})
    for k in _RESTORABLE:
        if k in raw:
            setattr(job, k, raw[k])
    # elapsed_s is a property; carry the NUMBER rather than trying to assign.
    if raw.get('elapsed_s') is not None:
        job.t0 = 0.0
        job._t_end = float(raw['elapsed_s'])
    # A job still marked running after a restart is not running. Say so.
    if job.status in ('queued', 'running'):
        job.status = 'failed'
        job.error = (job.error or 'the server restarted while this job was '
                                  'in progress; it did not resume')
    return job


class JobStore:
    def __init__(self) -> None:
        s = get_settings()
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, s.max_concurrent_jobs),
            thread_name_prefix='audit-job')

    def create(self, payload: dict) -> Job:
        job = Job(uuid.uuid4().hex[:16], payload)
        with self._lock:
            self._jobs[job.id] = job
        job.persist()
        return job

    def discard(self, job: Job) -> None:
        """Forget a job that was created but never submitted.

        The upload route has to create the job BEFORE it can stream files,
        because the destination is jobs/<id>/inbox -- the id is the path. If
        staging then fails (an oversized file, a client that hung up), the
        record and its half-written bytes must not survive: a queued-looking
        job that no worker will ever pick up is worse than no job at all.
        """
        with self._lock:
            self._jobs.pop(job.id, None)
        d = get_settings().jobs / job.id
        try:
            shutil.rmtree(d, ignore_errors=True)
        except OSError:
            log.warning('could not remove discarded job dir %s', d)

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is not None:
            return job
        return _restore(job_id)

    def list(self, limit: int = 50) -> list[Job]:
        """In-memory jobs PLUS whatever survived a restart.

        Listing only `self._jobs` meant that after a restart `GET /jobs`
        returned [] while every job.json still sat on disk -- the records
        existed and the API denied they did.
        """
        with self._lock:
            jobs = {j.id: j for j in self._jobs.values()}
        root = get_settings().jobs
        if root.is_dir():
            for d in root.iterdir():
                if d.name in jobs or not (d / 'job.json').is_file():
                    continue
                r = _restore(d.name)
                if r is not None:
                    jobs[d.name] = r
        return sorted(jobs.values(), key=lambda j: j.created_at,
                      reverse=True)[:limit]

    def submit(self, job: Job) -> None:
        self._pool.submit(self._run, job)

    def queue_depth(self) -> int:
        """Jobs queued or running. Backpressure reads this."""
        with self._lock:
            return sum(1 for j in self._jobs.values()
                       if j.status in ('queued', 'running'))

    def shutdown(self, grace_s: int = 20) -> None:
        """Stop accepting, then give running work a bounded chance to finish.

        A job killed mid-stage leaves half-written artifacts that a
        content-addressed cache cannot distinguish from complete ones -- so a
        clean stop is worth waiting for, and an unbounded wait is not (the
        platform will SIGKILL long before a 12-minute job ends). Anything
        still running is marked interrupted on disk so it does not come back
        claiming to be in progress.
        """
        log.info('shutdown: waiting up to %ds for running jobs', grace_s)
        deadline = time.time() + max(0, grace_s)
        self._pool.shutdown(wait=False, cancel_futures=True)
        while time.time() < deadline:
            if self.queue_depth() == 0:
                log.info('shutdown: all jobs settled')
                return
            time.sleep(0.5)
        with self._lock:
            stuck = [j for j in self._jobs.values()
                     if j.status in ('queued', 'running')]
        for j in stuck:
            j.status = 'failed'
            j.error = ('the server shut down while this job was in progress. '
                       'Phase 1-3 artifacts are content-addressed and were '
                       'kept, so re-submitting resumes rather than repeats.')
            j.finished_at = _now()
            j._t_end = time.time()
            j.persist()
        if stuck:
            log.warning('shutdown: %d job(s) interrupted and marked failed',
                        len(stuck))

    # -- the worker -------------------------------------------------------
    def _run(self, job: Job) -> None:
        from app.services import ingest, pipeline

        s = get_settings()
        job.status, job.started_at, job.t0 = 'running', _now(), time.time()
        job.deadline = job.t0 + s.job_timeout_s
        job.persist()
        _sweep_old_jobs(s)
        log.info('[%s] start: %d video(s), label=%r',
                 job.id, job.requested_videos, job.label)

        # EVERY path below runs inside this context, so DIRS['inbox'] and
        # DIRS['reports'] belong to this job while artifacts/ and briefs/
        # stay shared. That is what makes two concurrent jobs safe without
        # throwing away the content-addressed cache.
        with runtime.use_job_dirs(job.id, ephemeral=s.ephemeral):
            try:
                self._pipeline(job, s, ingest, pipeline)
                failed = [r for r in job.results
                          if r.get('status') not in ('ok', 'module_failed')]
                job.status = ('succeeded' if not failed
                              else 'partial' if len(failed) < len(job.results)
                              else 'failed')
            except Exception as exc:
                job.status = 'failed'
                job.error = f'{type(exc).__name__}: {exc}'
                job.phase = getattr(exc, 'phase', job.phase)
                log.error('[%s] FAILED in phase=%s: %s\n%s', job.id,
                          job.phase, job.error, traceback.format_exc())
            finally:
                job._t_end = time.time()
                job.finished_at = _now()
                job.phase = 'done'
                if s.ephemeral:
                    _drop_bulk(job.id)
                job.persist()
                log.info('[%s] %s in %.0fs (%d/%d videos)', job.id,
                         job.status.upper(), (job.elapsed_s or 0),
                         job.completed_videos, job.requested_videos)

    @staticmethod
    def _check_deadline(job: Job) -> None:
        """Stop between phases when the budget is gone.

        A COOPERATIVE check, deliberately. Killing a worker mid-ffmpeg or
        mid-HTTP leaves half-written artifacts that are indistinguishable from
        good ones to a content-addressed cache -- which is a far worse failure
        than a job that overran. So the deadline is honoured at phase
        boundaries, where everything on disk is complete.
        """
        if job.deadline and time.time() > job.deadline:
            raise TimeoutError(
                f'job exceeded AUDITOR_JOB_TIMEOUT_S '
                f'({get_settings().job_timeout_s}s) during phase '
                f'{job.phase!r}. Artifacts already written are kept and a '
                f're-run will reuse them.')

    def _pipeline(self, job: Job, s, ingest, pipeline) -> None:
        p = job.payload
        force = bool(p.get('force_reaudit'))

        # ---- 1. brief ----------------------------------------------------
        job.set_phase('brief', 'retrieving')
        t = time.time()
        precompiled = p.get('compiled_brief')

        if precompiled and not p.get('brief_url') and not p.get('brief_text'):
            # The caller holds the contract and named no document. Nothing to
            # fetch, nothing to compile, three model calls saved.
            compiled = ingest.use_precompiled(precompiled)
            origin = str(compiled.get('origin')
                         or f'client:{str(compiled.get("brief_hash"))[:12]}')
        else:
            loaded = ingest.load_brief(brief_url=p.get('brief_url'),
                                       brief_text=p.get('brief_text'))
            origin = loaded['origin']
            log.info('[%s] brief: %s (%d chars, hash %s)', job.id,
                     origin, loaded['chars'], loaded['hash'][:12])
            if precompiled:
                # Both given: the contract must describe THAT document, or
                # the report claims to have audited a brief it did not.
                compiled = ingest.use_precompiled(precompiled,
                                                  expect_text=loaded['text'])
            else:
                compiled = ingest.compile_brief(
                    loaded['text'], runs=s.brief_compile_runs,
                    keep_threshold=s.brief_keep_threshold,
                    recompile=bool(p.get('recompile')))
        compiled.setdefault('origin', origin)
        job.brief = ingest.brief_summary(compiled, origin)
        # HAND THE CONTRACT BACK when there is no durable place to keep it.
        # Without this the caller has no way to get identical scoring on the
        # next job, and the compiler is non-deterministic enough that the
        # difference is real.
        if s.ephemeral:
            job.compiled_brief = {k: v for k, v in compiled.items()
                                  if not k.startswith('_')}
        job.time_phase('brief', time.time() - t,
                       'client-supplied' if precompiled
                       else 'reused' if compiled.get('_reused') else 'compiled')
        if job.brief.get('unstable'):
            job.warn('the consensus compile disagreed across runs '
                     '(COMPILE_UNSTABLE); the requirement set is the '
                     'majority and the disagreement is in brief.flags')
        job.persist()

        # ---- 2. videos ---------------------------------------------------
        # Two ways in, one shape out. Uploaded files are ALREADY in this job's
        # inbox -- the request that accepted them wrote them there and checked
        # their container bytes -- so there is nothing to fetch and no reason
        # to involve yt-dlp, cookies or the network at all.
        self._check_deadline(job)
        uploads = p.get('uploads') or []
        t = time.time()
        if uploads:
            job.set_phase('ingest', f'{len(uploads)} uploaded file(s)')
            dl = ingest.adopt_uploads()
            detail = f'{len(dl["downloaded"])} uploaded'
        else:
            job.set_phase('ingest', f'{job.requested_videos} link(s)')
            dl = ingest.download_videos(p['video_urls'],
                                        cookies_file=s.cookies_file,
                                        workers=s.download_workers)
            detail = (f'{len(dl["downloaded"])} downloaded '
                      f'({s.download_workers} worker(s))')
        job.downloaded_videos = len(dl['downloaded'])
        job.time_phase('ingest', time.time() - t, detail)
        for u in dl['failed_urls']:
            job.warn(f'could not download: {u}')
        job.persist()

        # ---- 3. Phases 1-3 (multi-video, models load once) ---------------
        # Only Phase 1 takes a worker count. Phase 2 loads Whisper once and
        # frees it before loading OCR, and Phase 3 is rate-limited per model
        # per minute -- neither gets faster by being asked to do more at once.
        for name, fn, kw in (
                ('phase1', pipeline.run_preprocess,
                 {'workers': s.decode_workers}),
                ('phase2', pipeline.run_text_stages, {}),
                ('phase3', pipeline.run_vision, {})):
            self._check_deadline(job)
            t = time.time()
            out = fn(force=force, progress=job.set_phase, **kw)
            job.time_phase(name, time.time() - t)
            if name == 'phase1' and out.get('lost'):
                job.warn(f'{len(out["lost"])} video(s) failed Phase 1 and are '
                         f'absent downstream: {out["lost"]}')
            if name == 'phase3' and out.get('without_vision'):
                job.warn(f'{out["without_vision"]} video(s) have no visual '
                         f'evidence; their visual requirements read '
                         f'UNCERTAIN rather than FAIL')
            job.persist()

        # ---- 4. Phases 5-7, per video ------------------------------------
        self._check_deadline(job)
        t = time.time()
        rows = pipeline.audit_all(compiled, max_videos=s.max_videos_per_job,
                                  force=force, progress=job.set_phase,
                                  deadline=job.deadline)
        job.time_phase('phase5-7', time.time() - t)

        # For an upload job `source_urls` carries the links the files came
        # from, purely so a result row can still name its origin. Nothing
        # fetches them.
        urls = p.get('video_urls') or p.get('source_urls') or []
        for r in rows:
            r['url'] = ingest.url_for_source(r.get('source') or '', urls)
            for key, ext in (('report_html', 'html'), ('report_json', 'json')):
                if r.get(key):
                    r[f'{key}_url'] = (f'/jobs/{job.id}/report/'
                                       f'{r["video_id"]}.{ext}')
        job.results = rows
        job.completed_videos = sum(1 for r in rows if r.get('status') == 'ok')
        job.angle_distribution = pipeline.angle_distribution(rows)
        job.persist()


def _drop_bulk(job_id: str) -> None:
    """Ephemeral mode: delete the heavy inputs, keep the deliverable.

    `inbox/` is the downloaded videos (~7 MB each) and `artifacts/` is the
    frames, audio and per-stage JSON (~5-20 MB each). Together they are ~90%
    of a job's footprint and none of it is wanted once the reports exist.

    `reports/` and `job.json` SURVIVE, because deleting them would break
    GET /jobs/{id}/report/... the moment the job finished -- the caller has
    not fetched them yet. They age out on the normal retention sweep.
    """
    s = get_settings()
    freed = 0
    for sub in ('inbox', 'artifacts', 'exports'):
        d = s.jobs / job_id / sub
        if not d.is_dir():
            continue
        try:
            freed += sum(f.stat().st_size for f in d.rglob('*') if f.is_file())
            shutil.rmtree(d, ignore_errors=True)
        except OSError:
            continue
    if freed:
        log.info('[%s] ephemeral: freed %.1f MB (reports kept)',
                 job_id, freed / 1e6)


_LAST_SWEEP = 0.0


def _sweep_old_jobs(s) -> None:
    """Delete per-job inbox/reports older than the retention window.

    ONLY jobs/<id>/. artifacts/ and briefs/ are content-addressed and shared,
    and deleting those would throw away the cache that makes a re-run nearly
    free -- retention there is a separate decision with a separate answer.

    The job RECORD (job.json) is kept: it is a few KB, and "what did that run
    conclude" outliving "the 7 MB of video it concluded it from" is the right
    trade. Runs at most once an hour, on a job start, so there is no timer
    thread to supervise.
    """
    global _LAST_SWEEP
    if s.keep_job_files_hours <= 0:
        return
    now = time.time()
    if now - _LAST_SWEEP < 3600:
        return
    _LAST_SWEEP = now
    cutoff = now - s.keep_job_files_hours * 3600
    freed = 0
    for d in (s.jobs.iterdir() if s.jobs.is_dir() else []):
        if not d.is_dir():
            continue
        try:
            rec = d / 'job.json'
            if rec.is_file() and rec.stat().st_mtime > cutoff:
                continue
            for sub in ('inbox', 'reports'):
                target = d / sub
                if target.is_dir():
                    freed += sum(f.stat().st_size
                                 for f in target.rglob('*') if f.is_file())
                    shutil.rmtree(target, ignore_errors=True)
        except OSError:
            continue
    if freed:
        log.info('cleanup: freed %.1f MB from job workspaces older than %dh',
                 freed / 1e6, s.keep_job_files_hours)
    _sweep_artifacts(s)


def _sweep_artifacts(s) -> None:
    """Retire whole per-video artifact directories that nothing has touched.

    SEPARATE from the job sweep, with a much longer window, because this IS
    the cache: deleting it re-pays a 72-240 s vision pass per video. But it is
    also the thing that grows without bound -- frames, audio and JSON per
    video, forever -- and an appliance that fills its disk in month four is
    not an appliance.

    Whole directories, keyed by video_hash, by mtime. Never partial: removing
    one stage's artifact while keeping another leaves a video that looks
    processed and is not.
    """
    if s.keep_artifacts_days <= 0 or not s.artifacts.is_dir():
        return
    cutoff = time.time() - s.keep_artifacts_days * 86400
    freed = removed = 0
    for d in s.artifacts.iterdir():
        if not d.is_dir():
            continue
        try:
            newest = max((f.stat().st_mtime for f in d.rglob('*')
                          if f.is_file()), default=0)
            if newest > cutoff:
                continue
            freed += sum(f.stat().st_size for f in d.rglob('*') if f.is_file())
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
        except OSError:
            continue
    if removed:
        log.info('cleanup: retired %d artifact set(s) untouched for %dd '
                 '(%.1f MB)', removed, s.keep_artifacts_days, freed / 1e6)

    free_mb = s.disk_free_mb()
    if free_mb < s.min_free_disk_mb:
        # Say it before a job fails on a short write, which surfaces as a
        # corrupt artifact rather than as "the disk is full".
        log.error('DISK: %.0f MB free, below AUDITOR_MIN_FREE_DISK_MB=%d. '
                  'Decoding a video needs room for frames and audio; a short '
                  'write becomes a corrupt artifact, not a clean error.',
                  free_mb, s.min_free_disk_mb)


_STORE: Optional[JobStore] = None


def get_store() -> JobStore:
    global _STORE
    if _STORE is None:
        _STORE = JobStore()
    return _STORE
