"""Import the app, list routes, and exercise every path that needs no key.

Not a substitute for the integration test -- this only proves the API layer is
wired. The pipeline parity test is tests/test_parity.py.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
os.environ.setdefault('AUDITOR_DATA_ROOT', str(HERE / 'data'))
os.environ.setdefault('AUDITOR_PROBE_ON_STARTUP', 'false')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def main() -> int:
    print('  routes:')
    for r in app.routes:
        methods = sorted(getattr(r, 'methods', None) or [])
        if methods:
            print(f'      {",".join(methods):<10} {r.path}')

    failures = []
    with TestClient(app, raise_server_exceptions=False) as c:
        # LIVENESS: cheap, no model, no key. It must be 200 even when the
        # deployment is misconfigured, or a restart policy loops forever.
        r = c.get('/health')
        print(f'\n  GET /health -> {r.status_code}  {r.json().get("status")}')
        if r.status_code != 200:
            failures.append('health')

        # READINESS: 503 until this instance can actually serve a job.
        r = c.get('/ready')
        b = r.json()
        print(f'  GET /ready  -> {r.status_code}  ready={b.get("ready")}  '
              f'namespace={b.get("namespace")}  auth={b.get("auth")}')
        for p in b.get('problems') or []:
            print(f'      problem: {p[:88]}')
        if b.get('namespace') != 'ready':
            failures.append('namespace did not load')

        r = c.get('/metrics')
        print(f'  GET /metrics-> {r.status_code}  '
              f'{len(r.text.splitlines())} lines')
        if r.status_code != 200 or 'audit_up' not in r.text:
            failures.append('metrics')

        r = c.get('/config')
        cfg = r.json()
        print(f'  GET /config -> {r.status_code}  '
              f'gemini={cfg["gemini_api_key"]}  openai={cfg["openai_api_key"]}')
        # The single most important assertion in this file.
        blob = r.text
        if 'AIza' in blob or 'sk-' in blob:
            failures.append('A KEY LEAKED INTO /config')

        # ---- validation, which must be specific and not generic ----------
        cases = [
            ('no brief', {'video_urls': ['https://x.com/v/1']}, 422),
            ('both briefs', {'video_urls': ['https://x.com/v/1'],
                             'brief_url': 'https://docs.google.com/document/'
                                          'd/abcdefghijklmnop/edit',
                             'brief_text': 'hi'}, 422),
            ('empty urls', {'video_urls': [], 'brief_text': 'hi'}, 422),
            ('not a url', {'video_urls': ['tiktok.com/@a/video/1'],
                           'brief_text': 'hi'}, 422),
            ('too many', {'video_urls': [f'https://x.com/v/{i}'
                                         for i in range(200)],
                          'brief_text': 'hi'}, 422),
        ]
        print()
        for label, payload, want in cases:
            r = c.post('/analyze', json=payload)
            ok = r.status_code == want
            failures.append(label) if not ok else None
            detail = r.json()
            msg = (detail.get('detail') if isinstance(detail.get('detail'), str)
                   else str(detail.get('detail'))[:90])
            print(f'      {"PASS" if ok else "FAIL"}  {label:<12} '
                  f'-> {r.status_code}  {msg[:78]}')

        r = c.get('/jobs/doesnotexist123')
        print(f'      {"PASS" if r.status_code == 404 else "FAIL"}  '
              f'unknown job -> {r.status_code}')
        if r.status_code != 404:
            failures.append('unknown job')

        r = c.get('/jobs')
        print(f'      {"PASS" if r.status_code == 200 else "FAIL"}  '
              f'list jobs  -> {r.status_code} {r.json()}')

    print()
    if failures:
        print(f'  {len(failures)} FAILURE(S): {failures}')
        return 1
    print('  API layer wired correctly.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
