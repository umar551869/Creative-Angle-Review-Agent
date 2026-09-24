"""Is the configured Gemini key live, and what will it serve?

models.list() costs NO tokens, so this is the cheapest possible check and
never spends quota. It is deliberately separate from a generate call: a key
that can list but cannot generate is a quota or capacity problem, not a key
problem, and those need different fixes.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from app.config import get_settings  # noqa: E402
from auditor import runtime  # noqa: E402

GENERATE = '--generate' in sys.argv     # opt in; this one DOES spend quota


def main() -> int:
    s = get_settings()
    print('=' * 70)
    print('  KEY CHECK')
    print('=' * 70)
    print(f'  gemini : {s.redacted()["gemini_api_key"]}')
    print(f'  hf     : {s.redacted()["hf_token"]}')
    if not s.gemini_api_key:
        print('\n  No GEMINI_API_KEY. Set it in Backend/.env (no quotes).')
        return 1

    try:
        from google import genai
        client = genai.Client(api_key=s.gemini_api_key)
        try:
            listing = list(client.models.list(config={'query_base': True}))
        except Exception:
            listing = list(client.models.list())
    except Exception as exc:
        print(f'\n  models.list() FAILED: {type(exc).__name__}: '
              f'{str(exc)[:200]}')
        ns = runtime.load()
        verdict = ns.get('key_failure_verdict')
        if callable(verdict):
            print(f'  -> {verdict([str(exc)])}')
        return 1

    print(f'\n  KEY IS LIVE -- it can see {len(listing)} model(s).')

    ns = runtime.load()
    found = ns['discover_vision_models'](verbose=True)
    print(f'\n  vision candidates the pipeline would probe ({len(found)}):')
    for m in found:
        print(f'      {m}')

    if not GENERATE:
        print('\n  Not sending a generate call (pass --generate to test one).')
        print('  Listing costs no tokens; generating does.')
        return 0

    print('\n  one real generate call, 4 images ...')
    import time

    from PIL import Image
    imgs = [Image.new('RGB', (256, 448), (40 + 50 * i, 90, 200 - 40 * i))
            for i in range(4)]
    for model in found[:3]:
        t0 = time.time()
        try:
            r = client.models.generate_content(
                model=model,
                contents=imgs + ['Reply with JSON: {"n": <how many images>}'],
                config={'max_output_tokens': 128, 'temperature': 0.0,
                        'response_mime_type': 'application/json'})
            txt = (getattr(r, 'text', '') or '').strip()
            print(f'      OK    {model:<30} {time.time() - t0:5.1f}s  '
                  f'{txt[:40]!r}')
            return 0
        except Exception as exc:
            print(f'      FAIL  {model:<30} {type(exc).__name__}: '
                  f'{str(exc)[:110]}')
    print('\n  Nothing generated. The key LISTS fine, so this is quota or '
          'capacity,\n  not the key.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
