"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 67.
Regenerate with:  python Backend/tools/extract_from_notebook.py

Bodies are VERBATIM. The only removal is the notebook's driver
statements (the lines that run a stage and print a table); those
are listed at the foot of this file and are replaced by
Backend/app/services/.

This file is LOADED BY auditor.runtime, not imported directly.
The notebook shares one global namespace and binds some names
late (globals().get(...)), so the loader reproduces that exactly
rather than guessing an import graph that the original never had.
"""
# ============================================================================
# §37a  API key  --  HOISTED, because Phase 3 needs it too
# ============================================================================
# In the local-vision notebook this cell sits in Phase 4, which is the only
# place that needed a key. Here Phase 3 sends the frames to Gemini, and Phase 3
# runs ABOVE Phase 4 -- so the key has to be set before §26b or the vision
# backend raises NameError on an environment variable that does not exist yet.
#
# MOVED rather than duplicated: a secret in two cells is a secret you will
# rotate in one of them. Phase 4 still reads it straight out of os.environ.
#
# NO KEY IN THIS FILE, EVER.
#
# Add them as Colab secrets instead -- key icon in the left sidebar -- named
# GEMINI_API_KEY and OPENAI_API_KEY, with "Notebook access" enabled. Outside
# Colab, export them as environment variables.
#
# A key hardcoded here does not stay here. It is copied into the Phase 7
# builds, into every .bak, and into the file you upload and re-download. There
# is no version of "just for testing" that survives contact with a build step.
_KEY_WHERE = {}          # name -> where it came from, or why it did not

try:
    from google.colab import userdata          # noqa: F401
    _in_colab = True
except Exception:
    userdata, _in_colab = None, False

def key_failure_verdict(errors: list) -> str:
    """One line: is the KEY the problem, the quota, or the servers?

    Each has a different fix, and "nothing answered" hides which one you have.
    Only claims a cause when EVERY candidate failed the same way -- a mixed
    bag means read the individual errors, not a confident wrong summary.
    """
    errors = [str(e) for e in (errors or [])]
    if not errors:
        return ''
    def _all(*needles):
        return all(any(n in e for n in needles) for e in errors)
    if _all('API_KEY_INVALID', 'PERMISSION_DENIED', 'UNAUTHENTICATED',
            'API key not valid', '401', '403'):
        return ('THE KEY IS THE PROBLEM: every candidate refused it. '
                'Check GEMINI_API_KEY in Colab secrets.')
    if _all('RESOURCE_EXHAUSTED', '429'):
        return ('QUOTA, not the key: every candidate returned 429. A new key '
                'in the SAME project shares the same quota -- use a new '
                'project, or wait for the daily reset (midnight Pacific).')
    if _all('UNAVAILABLE', '503', 'high demand', 'overloaded'):
        return ('SERVER SIDE: every candidate returned 503. The key is fine. '
                'Retry shortly; a new key will not help.')
    if _all('NOT_FOUND', '404'):
        return ('RETIRED MODELS: every candidate 404d. The candidate list is '
                'out of date, not the key.')
    return 'MIXED failures -- read the per-model errors above.'


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 28: for _n in ('GEMINI_API_KEY', 'OPENAI_API_KEY'):
#   line 59: for _name, _tier in (('GEMINI_API_KEY', 'free tier, tried first'), ('OPENAI_
#   line 71: if not os.environ.get('GEMINI_API_KEY', '').strip():
#   line 80: print()
#   line 85: if 'P4' in globals():
