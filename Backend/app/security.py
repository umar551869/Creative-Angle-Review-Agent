"""API-key authentication.

OPTIONAL BY DEFAULT, AND THAT IS A DELIBERATE, NARROW DEFAULT.
Without AUDITOR_API_KEYS set, the API is open -- which is right for a laptop
and wrong for anything with a public address. `/ready` reports `auth: open` so
an unprotected deployment is visible rather than assumed, and the startup log
says it in as many words.

Why not force it on: a required key with no way to set it turns first-run into
a support ticket, and people respond by disabling auth entirely rather than
configuring it. Loud and optional beats mandatory and circumvented.
"""
from __future__ import annotations

import hmac
import logging
import os

from fastapi import HTTPException, Request

log = logging.getLogger('audit.auth')

_HEADER = 'x-api-key'
# Paths that must answer without a key: a load balancer cannot hold one, and a
# health check that 401s reads as a dead container.
_OPEN_PATHS = {'/health', '/ready', '/metrics', '/docs', '/redoc',
               '/openapi.json', '/docs/oauth2-redirect'}


def configured_keys() -> list[str]:
    raw = os.environ.get('AUDITOR_API_KEYS', '')
    return [k.strip() for k in raw.split(',') if k.strip()]


def auth_mode() -> str:
    n = len(configured_keys())
    return f'{n} key(s)' if n else 'OPEN -- anyone who can reach this can use it'


def require_key(request: Request) -> None:
    """FastAPI dependency. No-op when no key is configured."""
    keys = configured_keys()
    if not keys:
        return
    if request.url.path in _OPEN_PATHS:
        return
    presented = (request.headers.get(_HEADER)
                 or _bearer(request.headers.get('authorization', '')))
    if not presented:
        raise HTTPException(
            401, f'missing {_HEADER} header (or Authorization: Bearer ...)')
    # compare_digest, not ==. String equality short-circuits on the first
    # differing byte, which leaks key length and prefix to anyone willing to
    # time the responses.
    if not any(hmac.compare_digest(presented, k) for k in keys):
        log.warning('rejected request to %s: bad api key (…%s)',
                    request.url.path, presented[-4:] if presented else '')
        raise HTTPException(401, 'invalid api key')


def _bearer(header: str) -> str:
    parts = (header or '').split(None, 1)
    return parts[1].strip() if len(parts) == 2 and parts[0].lower() == 'bearer' \
        else ''
