"""Is the token valid, and does it have WRITE scope?

Read scope is enough to download models and is what most people generate
first. Pushing a Space needs Write, and the failure without it is a 403 at
push time -- after the repo has been assembled and committed, which reads as
a problem with the code rather than with the credential.
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BACKEND = Path(__file__).resolve().parents[2]


def read_token() -> str:
    envf = BACKEND / '.env'
    if envf.is_file():
        for line in envf.read_text(encoding='utf-8').splitlines():
            m = re.match(r'^(HF_WRITE_TOKEN|HF_TOKEN)=(.+)$', line.strip())
            if m and m.group(2).strip():
                return m.group(2).strip().strip('"\'')
    import os
    return (os.environ.get('HF_WRITE_TOKEN')
            or os.environ.get('HF_TOKEN') or '').strip()


def main() -> int:
    tok = read_token()
    if not tok:
        print('  no token in Backend/.env (HF_WRITE_TOKEN=) or the '
              'environment')
        return 1
    # Length and last four only. A printed token outlives the terminal.
    print(f'  token     : {len(tok)} chars, ending {tok[-4:]}')

    from huggingface_hub import HfApi
    api = HfApi(token=tok)
    try:
        me = api.whoami()
    except Exception as exc:
        print(f'  INVALID   : {type(exc).__name__}: {str(exc)[:160]}')
        return 1

    name = me.get('name')
    auth = (me.get('auth') or {}).get('accessToken') or {}
    role = auth.get('role')
    print(f'  user      : {name}')
    print(f'  type      : {me.get("type")}')
    print(f'  token name: {auth.get("displayName")}')
    print(f'  role      : {role}')

    # A FINE-GRAINED TOKEN'S ROLE IS ALWAYS 'fineGrained'. The useful
    # information is in its scopes, so rejecting on the role name alone said
    # "not write" about a token that had repo.write.
    if role == 'fineGrained':
        fg = auth.get('fineGrained') or {}
        writable = []
        for s in fg.get('scoped') or []:
            ent = (s.get('entity') or {}).get('name')
            if 'repo.write' in (s.get('permissions') or []):
                writable.append(ent)
        print(f'  repo.write: {writable or "NONE"}')
        if not writable:
            print('\n  FAIL: fine-grained token without repo.write. Edit it '
                  'at huggingface.co/settings/tokens and tick "Write access '
                  'to contents/settings of all repos".')
            return 1
        if name not in writable:
            print(f'\n  WARN: repo.write covers {writable}, not {name!r}. The '
                  f'Space must be created under one of those.')
        print('\n  OK: fine-grained, with repo.write.')
        print(f'  SPACE_OWNER={writable[0]}')
        return 0

    if role and role not in ('write', 'admin'):
        print(f'\n  FAIL: role is {role!r}. Creating and pushing a Space '
              f'needs Write.')
        print('  huggingface.co/settings/tokens -> New token -> Write')
        return 1
    print('\n  OK: valid, write-scoped.')
    print(f'  SPACE_OWNER={name}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
