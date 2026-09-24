"""Create the Space, set its configuration, and push the Backend.

Everything a fully-working Space needs, except the code push itself, which is
delegated to make_space_repo.py so there is one assembler rather than two.

    python deploy/huggingface/deploy_space.py --name creative-angle-review-agent

PRIVATE BY DEFAULT. A public Space is reachable and indexable by anyone, and
making it public is one click while un-publishing something that has been
crawled is not. --public is therefore explicit.

No secret is ever printed. The generated API key is written to Backend/.env so
it can be read from a file rather than copied out of a terminal.
"""
from __future__ import annotations

import argparse
import re
import secrets
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
sys.path.insert(0, str(BACKEND))

from deploy.huggingface.check_token import read_token  # noqa: E402


def env_value(key: str) -> str:
    f = BACKEND / '.env'
    if not f.is_file():
        return ''
    for line in f.read_text(encoding='utf-8').splitlines():
        m = re.match(rf'^{key}=(.*)$', line.strip())
        if m:
            return m.group(1).strip().strip('"\'')
    return ''


def set_env_value(key: str, val: str) -> None:
    """Write it to .env so the caller reads it from a file, not from chat."""
    f = BACKEND / '.env'
    lines = f.read_text(encoding='utf-8').splitlines() if f.is_file() else []
    if any(l.startswith(f'{key}=') for l in lines):
        lines = [f'{key}={val}' if l.startswith(f'{key}=') else l
                 for l in lines]
    else:
        lines.append(f'{key}={val}')
    f.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    assert any(l == f'{key}={val}' for l in
               f.read_text(encoding='utf-8').splitlines()), \
        f'could not write {key} to .env'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--name', default='creative-angle-review-agent')
    ap.add_argument('--owner', default='')
    ap.add_argument('--public', action='store_true')
    ap.add_argument('--no-push', action='store_true')
    a = ap.parse_args()

    tok = read_token()
    if not tok:
        print('  no token in Backend/.env (HF_WRITE_TOKEN=)')
        return 1

    from huggingface_hub import HfApi
    api = HfApi(token=tok)
    owner = a.owner or api.whoami()['name']
    repo_id = f'{owner}/{a.name}'
    url = f'https://huggingface.co/spaces/{repo_id}'

    print('=' * 74)
    print('  DEPLOY TO HUGGING FACE SPACES')
    print('=' * 74)
    print(f'  space     : {repo_id}')
    print(f'  visibility: {"PUBLIC" if a.public else "private"}')
    print(f'  hardware  : cpu-basic (free, 2 vCPU / 16 GB)')

    # ---- 1. the Space -----------------------------------------------------
    print('\n  1. creating the Space')
    api.create_repo(repo_id=repo_id, repo_type='space', space_sdk='docker',
                    private=not a.public, exist_ok=True)
    print(f'     {url}')

    # ---- 2. secrets -------------------------------------------------------
    # Encrypted, injected as environment variables, and NOT in the repo -- a
    # Space is a git repo, and a key committed to one is a key in history.
    print('\n  2. secrets')
    gemini = env_value('GEMINI_API_KEY')
    if not gemini:
        print('     FAIL: GEMINI_API_KEY is not in Backend/.env. Without it '
              'the Space starts and every job fails.')
        return 1
    api.add_space_secret(repo_id, 'GEMINI_API_KEY', gemini)
    print(f'     GEMINI_API_KEY   set ({len(gemini)} chars)')

    key = env_value('AUDITOR_API_KEYS') or secrets.token_urlsafe(32)
    api.add_space_secret(repo_id, 'AUDITOR_API_KEYS', key)
    set_env_value('AUDITOR_API_KEYS', key)
    print(f'     AUDITOR_API_KEYS set ({len(key)} chars, ending {key[-4:]})')
    print('                      full value saved to Backend/.env')

    hf_read = env_value('HF_TOKEN')
    if hf_read:
        # Raises the model download rate limit, which matters most here --
        # HF's own IPs are shared and throttled.
        api.add_space_secret(repo_id, 'HF_TOKEN', hf_read)
        print(f'     HF_TOKEN         set ({len(hf_read)} chars)')

    # ---- 3. variables -----------------------------------------------------
    print('\n  3. variables')
    VARS = {
        # No persistent volume on the free tier: the job workspace is deleted
        # when it finishes and the contract comes back in the response.
        'AUDITOR_EPHEMERAL': 'true',
        'AUDITOR_DATA_ROOT': '/data',
        'HF_HOME': '/models',
        'AUDITOR_LOG_JSON': 'true',
        # 2 vCPU on the free tier, not 4.
        'AUDITOR_DECODE_WORKERS': '2',
        'AUDITOR_DOWNLOAD_WORKERS': '4',
        # Start small. A job is minutes; a mis-clicked 25 is an afternoon.
        'AUDITOR_MAX_VIDEOS': '5',
        'AUDITOR_MAX_QUEUED_JOBS': '5',
    }
    for k, v in VARS.items():
        api.add_space_variable(repo_id, k, v)
        print(f'     {k:<26} {v}')

    if a.no_push:
        print('\n  --no-push: configuration only.')
        return 0

    # ---- 4. the code ------------------------------------------------------
    print('\n  4. assembling and pushing the repo')
    staging = BACKEND.parent / 'hf-space'
    r = subprocess.run(
        [sys.executable, str(HERE / 'make_space_repo.py'),
         '--out', str(staging), '--space', repo_id, '--push'],
        capture_output=True, text=True, encoding='utf-8', errors='replace')
    out = (r.stdout or '') + (r.stderr or '')
    out = out.replace(tok, '***').replace(gemini, '***').replace(key, '***')
    for line in out.splitlines():
        if line.strip():
            print(f'   {line}')
    if r.returncode != 0:
        print('\n  push FAILED')
        return 1

    print('\n' + '=' * 74)
    print(f'  {url}')
    print('  Build takes 20-40 min on the free tier. Watch the Logs tab.')
    print('  Then:')
    print(f'    curl https://{owner.lower()}-{a.name}.hf.space/health')
    print('=' * 74)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
