"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 91.
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
ALLOWED_EXPR_NAMES = ('duration',)

_NUM_RE  = re.compile(r'\d+(?:\.\d+)?')

_NAME_RE = re.compile(r'[A-Za-z_]\w*')

def _expr_tokens(expr: str):
    """Tokenise. Returns (tokens, error). Never raises."""
    if expr is None:
        return None, 'expression is None'
    if not isinstance(expr, str):
        return None, f'expression is {type(expr).__name__}, not str'
    if len(expr) > 120:
        return None, 'expression too long'
    toks, i = [], 0
    while i < len(expr):
        ch = expr[i]
        if ch.isspace():
            i += 1
            continue
        if ch in '+-*/()':
            toks.append((ch, ch)); i += 1; continue
        m = _NUM_RE.match(expr, i)
        if m:
            toks.append(('num', float(m.group(0)))); i = m.end(); continue
        m = _NAME_RE.match(expr, i)
        if m:
            name = m.group(0)
            if name not in ALLOWED_EXPR_NAMES:
                return None, f'unknown name {name!r} (allowed: {", ".join(ALLOWED_EXPR_NAMES)})'
            toks.append(('name', name)); i = m.end(); continue
        return None, f'illegal character {ch!r} at position {i}'
    if not toks:
        return None, 'empty expression'
    return toks, None

class _ExprParser:
    """Recursive descent over the token list. Raises ValueError, caught by the caller."""

    def __init__(self, toks, values):
        self.toks, self.i, self.values = toks, 0, values

    def peek(self):
        return self.toks[self.i][0] if self.i < len(self.toks) else None

    def take(self):
        t = self.toks[self.i]; self.i += 1; return t

    def parse(self):
        v = self.expr()
        if self.i != len(self.toks):
            raise ValueError(f'unexpected token {self.toks[self.i][1]!r}')
        return v

    def expr(self):
        v = self.term()
        while self.peek() in ('+', '-'):
            op = self.take()[0]
            r = self.term()
            v = v + r if op == '+' else v - r
        return v

    def term(self):
        v = self.factor()
        while self.peek() in ('*', '/'):
            op = self.take()[0]
            r = self.factor()
            if op == '/':
                if abs(r) < 1e-12:
                    raise ValueError('division by zero')
                v = v / r
            else:
                v = v * r
        return v

    def factor(self):
        k = self.peek()
        if k is None:
            raise ValueError('expression ends early')
        if k == '-':
            self.take(); return -self.factor()
        if k == '(':
            self.take()
            v = self.expr()
            if self.peek() != ')':
                raise ValueError('unbalanced parenthesis')
            self.take(); return v
        kind, val = self.take()
        if kind == 'num':
            return val
        if kind == 'name':
            if val not in self.values:
                raise ValueError(f'no value supplied for {val!r}')
            return float(self.values[val])
        raise ValueError(f'unexpected token {val!r}')

def validate_time_expr(expr: str) -> tuple:
    """(ok, error). Checks the expression parses -- with a probe duration, since
    an expression that only fails for SOME durations (division by zero) must be
    caught at compile time, not on the video that happens to trigger it."""
    toks, err = _expr_tokens(expr)
    if err:
        return False, err
    for probe in (1.0, 30.0, 600.0):
        try:
            _ExprParser(list(toks), {'duration': probe}).parse()
        except ValueError as e:
            return False, str(e)
    return True, None

def resolve_time_expr(expr: str, duration: float) -> tuple:
    """
    (value_or_None, flags). Resolve a symbolic bound against a real video.

    Out-of-range results are CLAMPED and flagged rather than dropped: "duration - 5"
    on a 3-second video is a real brief meeting a real video, not a malformed
    expression, and the evaluator needs a usable window plus the knowledge that
    the video was too short for the brief's assumption.
    """
    flags = []
    toks, err = _expr_tokens(expr)
    if err:
        return None, [f'EXPR_INVALID:{err}']
    try:
        v = _ExprParser(toks, {'duration': float(duration)}).parse()
    except ValueError as e:
        return None, [f'EXPR_INVALID:{e}']
    if v != v or v in (float('inf'), float('-inf')):        # NaN / inf
        return None, ['EXPR_NOT_FINITE']
    if v < 0:
        flags.append(f'EXPR_CLAMPED_LOW:{v:.3f}')
        v = 0.0
    if v > duration:
        flags.append(f'EXPR_CLAMPED_HIGH:{v:.3f}>{duration:.3f}')
        v = float(duration)
    return round(float(v), 3), flags

def resolve_requirement_window(req, duration: float) -> dict:
    """
    Resolve one requirement's temporal constraints against one video.

    This is the function Phase 6 calls. It returns absolute seconds plus the
    flags raised on the way, and it never mutates the requirement -- the same
    compiled brief is used against many videos of different lengths.
    """
    out = {'deadline_seconds': req.deadline_seconds,
           'window_start_seconds': req.window_start_seconds,
           'window_end_seconds': req.window_end_seconds,
           'flags': []}
    for expr_field, abs_field in (('window_start_expr', 'window_start_seconds'),
                                  ('window_end_expr',   'window_end_seconds')):
        expr = getattr(req, expr_field, None)
        if not expr:
            continue
        val, fl = resolve_time_expr(expr, duration)
        out['flags'].extend(f'{abs_field}:{f}' for f in fl)
        if val is not None:
            out[abs_field] = val
    s, e = out['window_start_seconds'], out['window_end_seconds']
    if s is not None and e is not None and s > e:
        out['flags'].append(f'WINDOW_INVERTED:{s:.2f}>{e:.2f}')
        out['window_start_seconds'], out['window_end_seconds'] = e, s
    if out['deadline_seconds'] is not None and out['deadline_seconds'] > duration:
        out['flags'].append(
            f'DEADLINE_BEYOND_VIDEO:{out["deadline_seconds"]:.2f}>{duration:.2f}')
    return out


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 187: print('§39 temporal expressions loaded.')
#   line 188: for _e, _d in [('duration - 5', 12.35), ('duration', 30.0), ('duration * 0.8
#   line 191: _ok, _err = validate_time_expr("__import__('os').system('x')")
#   line 192: print(f'  code injection rejected: {not _ok}  ({_err})')
