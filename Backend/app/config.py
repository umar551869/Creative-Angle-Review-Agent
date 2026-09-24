"""Settings, from the environment. No secret has a default.

Every threshold here exists in the notebook too; the value is carried over
unchanged and only the SOURCE moves (hardcoded -> env var). Where a notebook
constant is a genuine pipeline threshold rather than an operational knob, it
stays in auditor/ and is NOT duplicated here -- two homes for one number is how
they drift apart.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def _flag(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ('1', 'true', 'yes', 'on')


def _load_dotenv_once() -> str:
    """Read Backend/.env into the environment, if it is there.

    WITHOUT THIS, `.env` DOES NOTHING OUTSIDE DOCKER. Every setting is read
    from os.environ, and docker-compose's `env_file:` populates that for the
    container -- but `cp .env.example .env && uvicorn app.main:app` populates
    nothing, so the README's own quickstart came up with no GEMINI_API_KEY and
    no explanation.

    Real environment variables WIN. A value exported in the shell, or injected
    by the platform, must not be silently overridden by a stale file checked
    out beside the code.

    Note on quoting: python-dotenv strips matching surrounding quotes, but
    docker-compose's env_file parser does NOT -- it takes them literally, and
    a quoted key becomes a key with quotes in it, which fails as a 401 that
    looks like a bad key. So: no quotes, in either.
    """
    path = Path(__file__).resolve().parents[1] / '.env'
    if not path.is_file():
        return 'no .env file (using the ambient environment)'
    try:
        from dotenv import load_dotenv
    except ImportError:
        return (f'{path.name} found but python-dotenv is not installed -- it '
                f'was NOT read. pip install python-dotenv')
    load_dotenv(path, override=False)
    return f'loaded {path}'


DOTENV_STATUS = _load_dotenv_once()


def _auth_mode() -> str:
    """Live, from the environment -- see the note in redacted()."""
    from app.security import auth_mode
    return auth_mode()


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, '').strip() or default)
    except ValueError:
        return default


class Settings:
    """Read once at startup. Immutable in practice."""

    def __init__(self) -> None:
        # ---- paths --------------------------------------------------------
        self.data_root = Path(
            os.environ.get('AUDITOR_DATA_ROOT') or (Path.cwd() / 'data')
        ).resolve()

        # ---- secrets (never logged, never defaulted) ----------------------
        self.gemini_api_key = os.environ.get('GEMINI_API_KEY', '').strip()
        self.openai_api_key = os.environ.get('OPENAI_API_KEY', '').strip()

        # OPTIONAL. Nothing in the pipeline asks for a Hugging Face token, and
        # every model it downloads is public -- but anonymous downloads are
        # rate-limited per IP, and a datacentre IP is throttled far harder
        # than a home connection. On a cold container pulling Whisper
        # (~1.6 GB) and BGE (~130 MB), that is the difference between a slow
        # first request and a 429. Accepts either spelling of the variable,
        # because huggingface_hub has used both.
        self.hf_token = (os.environ.get('HF_TOKEN', '').strip()
                         or os.environ.get('HUGGING_FACE_HUB_TOKEN',
                                           '').strip())
        # Where model weights land. Point it at a persistent volume -- or bake
        # the weights into the image -- so a cold boot is not 2.5 GB of
        # downloading before the first frame is read.
        self.hf_home = os.environ.get('HF_HOME', '').strip()

        # ---- pipeline knobs, notebook defaults preserved ------------------
        # §90: MAX_VIDEOS = 25 -- "a ceiling, so a mis-clicked 50-video zip
        # cannot spend the afternoon".
        self.max_videos_per_job = _int('AUDITOR_MAX_VIDEOS', 25)
        # §48: BRIEF_COMPILE_RUNS = 3, BRIEF_KEEP_THRESHOLD = 0.5. Consensus
        # does not make the compiler deterministic; it keeps what a majority
        # of runs agreed on and reports the rest as COMPILE_UNSTABLE.
        self.brief_compile_runs = _int('AUDITOR_BRIEF_COMPILE_RUNS', 3)
        self.brief_keep_threshold = float(
            os.environ.get('AUDITOR_BRIEF_KEEP_THRESHOLD', '0.5'))
        # §0.3: VISION_PROVIDER = 'gemini'. 'local' needs a GPU and the Qwen
        # weights; the code is extracted but unwired.
        self.vision_provider = os.environ.get(
            'AUDITOR_VISION_PROVIDER', 'gemini').strip().lower()

        # PIN THE VISION MODEL, and in production you want to.
        #
        # gemini_models[0] IS the visual cache key. The startup probe ranks
        # candidates by MEASURED SPEED, and those measurements move: two runs
        # minutes apart ranked 'gemini-3.1-flash-lite-preview' and
        # 'gemini-3.1-flash-lite' first. A different leader is a different
        # key, so every run re-pays a 72-240 s vision pass AND falls back to
        # an artifact that no longer matches its config -- which downgrades
        # modality health and turns decided verdicts into UNCERTAIN.
        #
        # Pinning makes the key stable. The other probed models stay as
        # fallbacks (fix 67), so one 503 still does not kill a video.
        # Prefer a CONCRETE version over a '-latest' alias: an alias keeps the
        # cache key stable while the model behind it changes, which is the
        # opposite failure and a worse one.
        self.vision_model = os.environ.get('AUDITOR_VISION_MODEL', '').strip()

        # ---- ephemeral mode (no persistent volume) ------------------------
        # For Hugging Face Spaces, Cloud Run without GCS, and anywhere else
        # the disk resets. The job's videos, frames, audio and per-stage
        # artifacts go under jobs/<id>/ and are DELETED when it finishes;
        # only the reports and the job record are kept for the retention
        # window.
        #
        # `briefs/` is kept regardless, and that asymmetry is deliberate: the
        # frozen compile is ~30 KB and is the only stored thing whose loss
        # changes what a score MEANS, because the compiler is
        # non-deterministic. Artifacts are 5-20 MB per video and are pure
        # optimisation -- in production each video is audited once, so that
        # cache rarely hits anyway.
        #
        # On a platform where even briefs/ does not survive, pass the
        # `compiled_brief` back on the next request instead (see /analyze).
        self.ephemeral = _flag('AUDITOR_EPHEMERAL', False)

        # ---- job execution ------------------------------------------------
        # ONE by default. Videos are sequential within a job because
        # process_all() loads ASR once and frees it before loading OCR;
        # concurrent jobs would multiply model loads and, on GPU, race VRAM.
        self.max_concurrent_jobs = _int('AUDITOR_MAX_CONCURRENT_JOBS', 1)
        self.job_timeout_s = _int('AUDITOR_JOB_TIMEOUT_S', 3 * 3600)
        self.keep_job_files_hours = _int('AUDITOR_KEEP_JOB_FILES_HOURS', 72)

        # ---- parallelism, stage by stage ----------------------------------
        # NOT a single global knob, because the stages fail differently.
        #
        # DOWNLOADS: pure network wait, independent per URL, results are files
        # on disk. Parallel is free and obviously right.
        self.download_workers = _int('AUDITOR_DOWNLOAD_WORKERS', 4)
        # PHASE 1: ffmpeg/PyAV decode, the CPU hot spot. Independent per
        # video, content-addressed, each writing its own artifact directory.
        # Capped because each worker holds decoded frames -- 8 workers on
        # 1080p is gigabytes. 1 restores exact notebook behaviour.
        self.decode_workers = _int('AUDITOR_DECODE_WORKERS',
                                   max(1, min(4, (os.cpu_count() or 2))))
        # PHASE 3 VISION and PHASE 6 AUDIT: network-bound, so parallelism
        # LOOKS like the biggest win here -- 72-240 s per video, nearly all of
        # it waiting on Gemini. It is deliberately 1 anyway.
        #
        # Those calls are rate-limited per model per minute, and a run against
        # a real free-tier key returned 503 "high demand" on seven of eight
        # models and a 429 on the eighth. Issuing them N-at-once converts a
        # slow job into a failed one, and the retry ladder then spends its
        # budget on self-inflicted congestion. Raise this only on a paid tier,
        # and raise it slowly.
        self.vision_workers = _int('AUDITOR_VISION_WORKERS', 1)
        self.audit_workers = _int('AUDITOR_AUDIT_WORKERS', 1)

        # ---- ingestion ----------------------------------------------------
        # TikTok increasingly refuses anonymous downloads, and a datacentre IP
        # is refused harder than a residential one. cookies.txt is the
        # documented escape hatch.
        self.cookies_file = os.environ.get('AUDITOR_COOKIES_FILE', '').strip()
        self.download_timeout_s = _int('AUDITOR_DOWNLOAD_TIMEOUT_S', 300)

        # ---- serving ------------------------------------------------------
        # Comma-separated. Empty = the API is OPEN. /ready says which, and
        # startup logs a warning, so an unprotected deployment is visible
        # rather than assumed.
        self.api_keys = [k.strip() for k
                         in os.environ.get('AUDITOR_API_KEYS', '').split(',')
                         if k.strip()]
        # Empty = no CORS headers at all, which is correct for a server-to-
        # server API. Set only for a browser front end.
        self.cors_origins = [o.strip() for o
                             in os.environ.get('AUDITOR_CORS_ORIGINS',
                                               '').split(',') if o.strip()]
        # Every endpoint takes a small JSON document. Without a ceiling an
        # unauthenticated caller can make the process buffer arbitrary bytes.
        self.max_body_bytes = _int('AUDITOR_MAX_BODY_BYTES', 2 * 1024 * 1024)
        # Backpressure. Each job takes minutes, so an unbounded queue just
        # converts "too much work" into "nothing finishes and memory grows".
        self.max_queued_jobs = _int('AUDITOR_MAX_QUEUED_JOBS', 20)
        # How long SIGTERM waits for a running job before giving up. Cloud
        # platforms typically allow 10-30 s before SIGKILL; a long grace here
        # is a promise the platform will not keep.
        self.shutdown_grace_s = _int('AUDITOR_SHUTDOWN_GRACE_S', 20)
        # Artifacts are the cache and are SHARED, so retention is a separate,
        # longer decision than job workspaces. 0 = never sweep.
        self.keep_artifacts_days = _int('AUDITOR_KEEP_ARTIFACTS_DAYS', 30)
        self.min_free_disk_mb = _int('AUDITOR_MIN_FREE_DISK_MB', 2048)

        # ---- api ----------------------------------------------------------
        self.api_title = 'Creative Audit API'
        self.log_level = os.environ.get('AUDITOR_LOG_LEVEL', 'INFO').upper()
        self.log_json = _flag('AUDITOR_LOG_JSON', False)
        self.probe_models_on_startup = _flag('AUDITOR_PROBE_ON_STARTUP', True)

    # -- derived -----------------------------------------------------------
    @property
    def artifacts(self) -> Path:
        return self.data_root / 'artifacts'

    @property
    def briefs(self) -> Path:
        return self.data_root / 'briefs'

    @property
    def jobs(self) -> Path:
        return self.data_root / 'jobs'

    def ensure_dirs(self) -> None:
        for p in (self.data_root, self.artifacts, self.briefs, self.jobs,
                  self.data_root / 'runs', self.data_root / 'exports'):
            p.mkdir(parents=True, exist_ok=True)

    def missing_requirements(self) -> list[str]:
        """What would make a request fail, checked at startup instead."""
        problems = []
        if not self.gemini_api_key:
            problems.append(
                'GEMINI_API_KEY is not set. Phase 3 (vision) and Phases 4/6 '
                '(brief compile, L3 adjudication) all need it, and this '
                'pipeline is hosted-only -- it will not silently fall back '
                'to a local model.')
        if self.vision_provider not in ('gemini', 'local'):
            problems.append(
                f'AUDITOR_VISION_PROVIDER={self.vision_provider!r} is neither '
                f'"gemini" nor "local".')
        return problems

    def apply_to_environment(self) -> list[str]:
        """Push optional settings into the env the LIBRARIES read.

        faster-whisper, transformers and sentence-transformers all resolve
        their credentials through huggingface_hub, which reads the process
        environment -- none of them takes a token argument at the call sites
        this pipeline uses (`WhisperModel(name, ...)`,
        `SentenceTransformer(model_id, ...)`). Setting the variable here is
        therefore the whole integration, and it means ZERO pipeline code
        changes, which is what keeps parity intact.

        Both spellings are set: huggingface_hub reads HF_TOKEN, older versions
        and some downstream libraries still read HUGGING_FACE_HUB_TOKEN.
        """
        applied = []
        if self.hf_token:
            for name in ('HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN'):
                os.environ[name] = self.hf_token
            applied.append('HF_TOKEN')
        if self.hf_home:
            os.environ['HF_HOME'] = self.hf_home
            applied.append(f'HF_HOME={self.hf_home}')
        return applied

    def redacted(self) -> dict:
        """Safe to log. Keys become a length, never a value."""
        return {
            'data_root': str(self.data_root),
            'gemini_api_key': f'set ({len(self.gemini_api_key)} chars)'
                              if self.gemini_api_key else 'NOT SET',
            'openai_api_key': f'set ({len(self.openai_api_key)} chars)'
                              if self.openai_api_key else 'not set',
            'hf_token': f'set ({len(self.hf_token)} chars)'
                        if self.hf_token else 'not set (optional)',
            'hf_home': self.hf_home or '(default ~/.cache/huggingface)',
            'vision_provider': self.vision_provider,
            'max_videos_per_job': self.max_videos_per_job,
            'brief_compile_runs': self.brief_compile_runs,
            'brief_keep_threshold': self.brief_keep_threshold,
            'max_concurrent_jobs': self.max_concurrent_jobs,
            'cookies_file': self.cookies_file or '(none)',
            'workers': {'download': self.download_workers,
                        'decode': self.decode_workers,
                        'vision': self.vision_workers,
                        'audit': self.audit_workers},
            'job_timeout_s': self.job_timeout_s,
            'keep_job_files_hours': self.keep_job_files_hours,
            'keep_artifacts_days': self.keep_artifacts_days,
            'ephemeral': self.ephemeral,
            # Read LIVE, not from self.api_keys. Settings are cached for the
            # process; /ready reports auth from the environment. Two sources
            # that can disagree is how an operator ends up believing auth is
            # on when it is not.
            'auth': _auth_mode(),
            'cors_origins': self.cors_origins or '(none)',
            'max_queued_jobs': self.max_queued_jobs,
            'max_body_bytes': self.max_body_bytes,
        }

    def disk_free_mb(self) -> float:
        import shutil as _sh
        try:
            return _sh.disk_usage(self.data_root).free / 1e6
        except OSError:
            return float('inf')


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    os.environ.setdefault('AUDITOR_DATA_ROOT', str(s.data_root))
    # Before anything touches a model. huggingface_hub reads the environment
    # when it resolves a download, so this has to land ahead of the first
    # WhisperModel() or SentenceTransformer() call -- which it does, because
    # app.main calls get_settings() at import time, above runtime.load().
    s.apply_to_environment()
    s.ensure_dirs()
    return s
