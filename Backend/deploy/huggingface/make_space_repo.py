"""Assemble a Hugging Face Space repo from Backend/.

A Space is a git repo whose ROOT is the application: the Dockerfile must be at
the top level, and its README.md carries the YAML front-matter Spaces reads its
configuration from. Backend/ is nearly that already -- this copies it into a
staging directory with the two differences applied, then checks the result
rather than assuming it.

    python deploy/huggingface/make_space_repo.py --out ../hf-space
    python deploy/huggingface/make_space_repo.py --out ../hf-space --push \\
        --space umar551869/creative-angle-review-agent

--push needs a WRITE-scoped token. It is read from HF_WRITE_TOKEN or HF_TOKEN
in the environment or in Backend/.env -- never from the command line, where it
would land in shell history, and never printed.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BACKEND = Path(__file__).resolve().parents[2]

# Never copied. data/ and .venv/ are gigabytes; .env holds live credentials.
EXCLUDE_DIRS = {'.venv', 'data', '__pycache__', '.pytest_cache', '.git',
                '.ruff_cache', '.mypy_cache', 'node_modules'}
EXCLUDE_FILES = {'.env'}
EXCLUDE_SUFFIX = {'.pyc', '.pyo', '.mp4', '.mov', '.webm', '.mkv', '.wav',
                  '.tar.gz', '.zip'}

SPACE_GITIGNORE = """\
# A Space is a git repo, and these are either secret or regenerable.
.env
.env.*
!.env.example
data/
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
*.mp4
*.mov
*.wav
*.zip
*.tar.gz
"""


def log(msg: str) -> None:
    print(f'  {msg}')


def token() -> str:
    """A write token, from the environment or Backend/.env. Never printed."""
    for name in ('HF_WRITE_TOKEN', 'HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN'):
        v = os.environ.get(name, '').strip()
        if v:
            return v
    envf = BACKEND / '.env'
    if envf.is_file():
        for line in envf.read_text(encoding='utf-8').splitlines():
            m = re.match(r'^(HF_WRITE_TOKEN|HF_TOKEN)=(.+)$', line.strip())
            if m and m.group(2).strip():
                return m.group(2).strip().strip('"\'')
    return ''


def copy_tree(out: Path) -> int:
    if out.exists():
        # Keep .git so a second run updates the same Space instead of
        # orphaning it.
        for child in out.iterdir():
            if child.name == '.git':
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    out.mkdir(parents=True, exist_ok=True)

    n = 0
    for src in BACKEND.rglob('*'):
        rel = src.relative_to(BACKEND)
        if EXCLUDE_DIRS & set(rel.parts):
            continue
        if src.is_dir():
            continue
        if src.name in EXCLUDE_FILES or src.suffix.lower() in EXCLUDE_SUFFIX:
            continue
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        n += 1
    return n


def verify(out: Path) -> list[str]:
    """Check the assembled repo. A Space that is wrong fails opaquely --
    'Configuration error' with no mention of what it could not read."""
    problems = []

    if not (out / 'Dockerfile').is_file():
        problems.append('Dockerfile is not at the repo root')

    readme = out / 'README.md'
    if not readme.is_file():
        problems.append('README.md missing')
    else:
        s = readme.read_text(encoding='utf-8')
        m = re.match(r'^---\n(.*?)\n---\n', s, re.S)
        if not m:
            problems.append('README.md has no YAML front-matter -- Spaces '
                            'cannot read its configuration')
        else:
            try:
                import yaml
                fm = yaml.safe_load(m.group(1))
            except Exception as exc:
                problems.append(f'front-matter is not valid YAML: {exc}')
                fm = {}
            if fm.get('sdk') != 'docker':
                problems.append(f"front-matter sdk is {fm.get('sdk')!r}, "
                                f"expected 'docker'")
            if fm.get('app_port') != 8000:
                problems.append(f"front-matter app_port is "
                                f"{fm.get('app_port')!r}, expected 8000 -- "
                                f"Spaces would probe 7860 and find nothing")

    # Secrets. The one thing that must never be here.
    KEY = re.compile(r'AIza[0-9A-Za-z_\-]{30,}|sk-[A-Za-z0-9_\-]{20,}'
                     r'|hf_[A-Za-z0-9]{30,}|AQ\.[A-Za-z0-9_\-]{20,}')
    SYN = re.compile(r'abcdef|123456|qrstuv|wxyz|(.)\1{5,}', re.I)
    for p in out.rglob('*'):
        if not p.is_file() or '.git' in p.parts:
            continue
        if p.suffix.lower() not in {'.py', '.md', '.txt', '.yml', '.yaml',
                                    '.json', '.example', '.sh', ''}:
            continue
        try:
            t = p.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        for mm in KEY.finditer(t):
            if not SYN.search(mm.group(0)):
                problems.append(f'CREDENTIAL in {p.relative_to(out)}: '
                                f'{mm.group(0)[:10]}...')
    if (out / '.env').exists():
        problems.append('.env was copied -- it holds live credentials')
    if (out / 'data').exists():
        problems.append('data/ was copied -- it is ~1.7 GB of model weights')
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(BACKEND.parent / 'hf-space'))
    ap.add_argument('--space', help='owner/name, e.g. umar551869/my-space')
    ap.add_argument('--push', action='store_true')
    a = ap.parse_args()
    out = Path(a.out).resolve()

    print('=' * 74)
    print('  ASSEMBLE HUGGING FACE SPACE REPO')
    print('=' * 74)
    log(f'source: {BACKEND}')
    log(f'target: {out}')

    n = copy_tree(out)
    log(f'copied {n} file(s)')

    # The two differences from Backend/.
    src_readme = BACKEND / 'deploy' / 'huggingface' / 'README.md'
    shutil.copy2(src_readme, out / 'README.md')
    log('README.md <- deploy/huggingface/README.md (carries the front-matter)')
    (out / '.gitignore').write_bytes(SPACE_GITIGNORE.encode('utf-8'))
    log('.gitignore written')

    print('\n  VERIFY')
    problems = verify(out)
    for p in problems:
        log(f'FAIL  {p}')
    if problems:
        print('\n' + '=' * 74)
        print(f'  {len(problems)} problem(s). Nothing pushed.')
        print('=' * 74)
        return 1
    size = sum(f.stat().st_size for f in out.rglob('*')
               if f.is_file() and '.git' not in f.parts)
    log(f'PASS  Dockerfile at root, front-matter valid, no credentials')
    log(f'PASS  {size / 1e6:.1f} MB, ready to push')

    if not a.push:
        print('\n' + '=' * 74)
        print('  Staged only. To push:')
        print(f'    python {Path(__file__).name} --out {out} \\')
        print('      --space <owner>/<name> --push')
        print('=' * 74)
        return 0

    if not a.space:
        log('FAIL  --push needs --space <owner>/<name>')
        return 1
    tok = token()
    if not tok:
        log('FAIL  no write token. Put a WRITE-scoped token in Backend/.env '
            'as HF_WRITE_TOKEN=..., or export it.')
        return 1
    log(f'token: {len(tok)} chars, ending {tok[-4:]}')   # never the whole one

    url = f'https://user:{tok}@huggingface.co/spaces/{a.space}'
    safe = f'https://huggingface.co/spaces/{a.space}'

    def git(*args, **kw):
        return subprocess.run(['git', '-C', str(out), *args],
                              capture_output=True, text=True,
                              encoding='utf-8', errors='replace', **kw)

    if not (out / '.git').exists():
        git('init', '-q')
    git('config', 'user.name', os.environ.get('GIT_AUTHOR_NAME', 'umar551869'))
    git('config', 'user.email',
        os.environ.get('GIT_AUTHOR_EMAIL', 'umar632708@gmail.com'))
    git('remote', 'remove', 'origin')
    git('remote', 'add', 'origin', url)
    git('add', '-A')
    git('commit', '-q', '-m', 'Creative Audit API -- FastAPI backend')
    log('committed')

    r = git('push', '-u', 'origin', 'HEAD:main', '--force')
    combined = (r.stdout or '') + (r.stderr or '')
    # The URL carries the token. Never let it reach a log.
    combined = combined.replace(tok, '***')
    print()
    for line in combined.splitlines()[:12]:
        log(line)
    if r.returncode != 0:
        log('push FAILED (see above)')
        return 1
    print('\n' + '=' * 74)
    print(f'  Pushed. Build progress: {safe}  ->  Logs tab')
    print('=' * 74)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
