"""Logging that names the run, the video and the phase -- and never a key.

The notebook's own discipline applies here: cell 67 is explicit that a key must
never be printed, because notebook output is saved with the file and outlives
the session. The same is true of a log line, which outlives it further.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys

# Anything shaped like a credential, wherever it appears in a message.
_SECRET_PATTERNS = [
    # Google issues several shapes and this project has seen more than one.
    # AIza... is the AI Studio form; AQ.... is the newer one and was the key
    # actually in use here -- it leaked past a redactor that only knew AIza.
    # A credential scrubber that covers one vendor format is a scrubber that
    # gives false confidence.
    re.compile(r'\bAIza[0-9A-Za-z_\-]{30,}'),          # Google AI Studio
    re.compile(r'\bAQ\.[A-Za-z0-9_\-]{20,}'),          # Google, newer form
    re.compile(r'\bya29\.[A-Za-z0-9_\-]{20,}'),        # Google OAuth access
    re.compile(r'\bsk-[A-Za-z0-9_\-]{20,}'),           # OpenAI
    re.compile(r'\bhf_[A-Za-z0-9]{20,}'),              # Hugging Face
    re.compile(r'\bBearer\s+[A-Za-z0-9._\-]{20,}', re.I),
    # Bare `key=` too, not just `api_key=`. The catch-all existed and still
    # missed `key=AQ...` because the alternation required the word "api".
    re.compile(r'(?i)\b(api[_-]?key|key|token|secret|passwo?rd|credential)'
               r'\s*[=:]\s*[\'"]?([^\s\'",}]{12,})'),
]


class RedactingFilter(logging.Filter):
    """A key that reaches a log file has left the process. Scrub first."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        clean = msg
        for pat in _SECRET_PATTERNS:
            clean = pat.sub(lambda m: (m.group(0)[:6] + '...REDACTED')
                            if m.lastindex is None
                            else f'{m.group(1)}=...REDACTED', clean)
        if clean != msg:
            record.msg, record.args = clean, ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            'ts': self.formatTime(record, '%Y-%m-%dT%H:%M:%S'),
            'level': record.levelname,
            'logger': record.name,
            'request_id': getattr(record, 'request_id', '-'),
            'message': record.getMessage(),
        }
        if record.exc_info:
            out['exception'] = self.formatException(record.exc_info)
        return json.dumps(out)


def setup_logging(settings) -> None:
    root = logging.getLogger()
    if getattr(root, '_audit_configured', False):
        return
    root.setLevel(settings.log_level)
    for h in list(root.handlers):
        root.removeHandler(h)

    from app.middleware import RequestIdFilter

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RedactingFilter())
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        JsonFormatter() if settings.log_json else logging.Formatter(
            '%(asctime)s  %(levelname)-7s [%(request_id)s] %(name)-16s '
            '%(message)s', datefmt='%H:%M:%S'))
    root.addHandler(handler)

    # A file per deployment, alongside the data, so a job that failed
    # yesterday can still be explained.
    try:
        logdir = settings.data_root / 'runs'
        logdir.mkdir(parents=True, exist_ok=True)
        # ROTATING. A file handler that never rotates is a disk-full incident
        # with a long fuse -- and this pipeline logs per stage, per video.
        from logging.handlers import RotatingFileHandler

        fh = RotatingFileHandler(logdir / 'api.log', maxBytes=20 * 1024 * 1024,
                                 backupCount=5, encoding='utf-8')
        fh.addFilter(RedactingFilter())
        fh.addFilter(RequestIdFilter())
        fh.setFormatter(logging.Formatter(
            '%(asctime)s  %(levelname)-7s [%(request_id)s] %(name)-16s '
            '%(message)s'))
        root.addHandler(fh)
    except OSError:
        pass

    # The pipeline prints a great deal to stdout by design (it was a
    # notebook). Keep it -- it is the per-stage narration, and losing it would
    # make a slow job opaque -- but stop third-party libraries being chatty.
    for noisy in ('urllib3', 'httpx', 'httpcore', 'PIL', 'matplotlib',
                  'google', 'asyncio', 'multipart'):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    root._audit_configured = True  # type: ignore[attr-defined]
