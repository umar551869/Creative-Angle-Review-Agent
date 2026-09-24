"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 21.
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
HALLUCINATION_PHRASES = (
    'thanks for watching', 'thank you for watching', 'subscribe to my channel',
    'please subscribe', 'like and subscribe', 'see you in the next video',
    'amara.org', 'subtitles by', 'transcription by', 'www.', '.com/',
)

def read_wav_mono16k(path) -> np.ndarray:
    """
    Load Phase 1's audio.wav with the STDLIB `wave` module.
    Phase 1 wrote exactly 16 kHz mono pcm_s16le, so no torchaudio / librosa / av
    is needed -- one less native dependency to fail on Python 3.13.
    """
    with wave.open(str(path), 'rb') as w:
        assert w.getsampwidth() == 2, f'expected 16-bit PCM, got {w.getsampwidth()*8}-bit'
        raw = w.readframes(w.getnframes())
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if w.getnchannels() > 1:
            audio = audio.reshape(-1, w.getnchannels()).mean(axis=1)
        return audio

def compression_ratio(text: str) -> float:
    """Whisper's own degenerate-repetition signature: highly compressible == repeated."""
    b = text.encode('utf-8')
    if not b:
        return 0.0
    return len(b) / len(zlib.compress(b))

# ---------------------------------------------------------------------------
# VAD -- only needed for the transformers path. faster-whisper bundles Silero.
# ---------------------------------------------------------------------------
def load_vad(cfg: ASRConfig):
    """Returns (speech_regions_fn | None, backend_name)."""
    if not BACKENDS.get('silero_vad'):
        return None, 'none'
    try:
        from silero_vad import load_silero_vad, get_speech_timestamps
        import torch as _torch
        model = load_silero_vad()

        def regions(audio: np.ndarray) -> list:
            ts = get_speech_timestamps(
                _torch.from_numpy(audio), model, sampling_rate=16000,
                min_silence_duration_ms=cfg.vad_min_silence_ms,
                speech_pad_ms=cfg.vad_speech_pad_ms,
                return_seconds=True,
            )
            return [{'start': float(t['start']), 'end': float(t['end'])} for t in ts]

        return regions, 'silero_vad'
    except Exception as exc:
        print(f'  silero-vad unavailable ({type(exc).__name__}) -> no VAD')
        return None, 'none'

# ---------------------------------------------------------------------------
# Hugging Face credentials, resolved HERE because this is where the download
# happens: WhisperModel() below, and SentenceTransformer() in Phase 6 L2.
#
# OPTIONAL. Every model fetched here is public and works anonymously. A token
# only raises the download RATE LIMIT, which is what bites on Colab: a
# datacentre IP is throttled far harder than a home connection, and a cold
# runtime pulls ~1.8 GB before the first word is transcribed.
#
# NOT used by OCR -- RapidOCR bundles its ONNX models and PaddleOCR fetches
# from Paddle, so neither goes near the Hub.
# ---------------------------------------------------------------------------
def ensure_hf_token(verbose: bool = False) -> bool:
    """Put HF_TOKEN in the environment, from a Colab secret if need be.

    Returns True when a token is in play. Never raises and never prints the
    token: notebook output is saved with the file and outlives the session.

    huggingface_hub reads HF_TOKEN; older versions and some downstream
    libraries read HUGGING_FACE_HUB_TOKEN. Both are set, because one of them
    being set is the confusing way for this to half-work.
    """
    tok = (os.environ.get('HF_TOKEN', '').strip()
           or os.environ.get('HUGGING_FACE_HUB_TOKEN', '').strip())
    if not tok:
        try:
            from google.colab import userdata
            tok = (userdata.get('HF_TOKEN') or '').strip()
        except Exception:
            tok = ''
    if not tok:
        if verbose:
            print('  HF: anonymous (fine -- these models are public). Set a '
                  'Colab secret')
            print('      HF_TOKEN if a download hits a rate limit: '
                  'huggingface.co/settings/tokens, Read scope.')
        return False
    os.environ['HF_TOKEN'] = tok
    os.environ['HUGGING_FACE_HUB_TOKEN'] = tok
    if verbose:
        print(f'  HF: token set ({len(tok)} chars) -- higher download rate '
              f'limit')
    return True

# ---------------------------------------------------------------------------
# Backend A -- faster-whisper (preferred). CTranslate2, bundles Silero VAD.
# ---------------------------------------------------------------------------
class FasterWhisperBackend:
    name = 'faster_whisper'
    has_builtin_vad = True

    def __init__(self, model, info):
        self.model, self.info = model, info

    @classmethod
    def load(cls, cfg: ASRConfig, prefer_gpu: bool = True):
        ensure_hf_token()          # before the first weights fetch
        from faster_whisper import WhisperModel
        device_plan = ([('cuda', 'float16')] if (prefer_gpu and HAS_CUDA) else []) + [('cpu', 'int8')]
        errors = []
        for device, compute_type in device_plan:
            for name in cfg.model_candidates:
                t0 = time.time()
                try:
                    model = WhisperModel(name, device=device, compute_type=compute_type)
                    # Smoke test on 0.5 s of silence. cuDNN/cuBLAS mismatches surface
                    # at INFERENCE, not at load -- this is what catches them.
                    segs, _ = model.transcribe(np.zeros(8000, dtype=np.float32),
                                               language='en', vad_filter=False)
                    _ = list(segs)
                    return cls(model, {'backend': cls.name, 'model': name, 'device': device,
                                       'compute_type': compute_type,
                                       'load_seconds': round(time.time() - t0, 2)})
                except Exception as exc:
                    errors.append(f'{name}@{device}/{compute_type}: {type(exc).__name__}: {str(exc)[:110]}')
        raise RuntimeError('faster-whisper: no model loaded.\n  ' + '\n  '.join(errors))

    def transcribe_raw(self, audio_path, cfg: ASRConfig) -> tuple:
        vad_params = {'min_silence_duration_ms': cfg.vad_min_silence_ms,
                      'speech_pad_ms': cfg.vad_speech_pad_ms}
        kwargs = dict(
            language=cfg.language, task='transcribe', beam_size=cfg.beam_size,
            temperature=cfg.temperature,
            condition_on_previous_text=cfg.condition_on_previous_text,
            word_timestamps=cfg.word_timestamps, vad_filter=cfg.vad_filter,
            no_speech_threshold=cfg.no_speech_threshold,
            compression_ratio_threshold=cfg.compression_ratio_threshold,
            log_prob_threshold=cfg.log_prob_threshold,
            initial_prompt=cfg.initial_prompt,
        )
        try:
            seg_iter, info = self.model.transcribe(str(audio_path), vad_parameters=vad_params, **kwargs)
        except TypeError:
            seg_iter, info = self.model.transcribe(str(audio_path), **kwargs)

        segments = []
        for s in seg_iter:
            words = [{'word': w.word, 'start': round(float(w.start), 3),
                      'end': round(float(w.end), 3),
                      'probability': round(float(w.probability), 4)}
                     for w in (s.words or [])]
            segments.append({
                'id': int(s.id), 'start': round(float(s.start), 3), 'end': round(float(s.end), 3),
                'text': s.text, 'avg_logprob': round(float(s.avg_logprob), 4),
                'no_speech_prob': round(float(s.no_speech_prob), 4),
                'compression_ratio': round(float(s.compression_ratio), 4),
                'words': words,
            })
        meta = {'language': getattr(info, 'language', cfg.language),
                'language_probability': round(float(getattr(info, 'language_probability', 0.0) or 0.0), 4),
                'audio_duration_seconds': round(float(getattr(info, 'duration', 0.0) or 0.0), 3),
                'vad_backend': 'silero (bundled)' if cfg.vad_filter else 'disabled'}
        return segments, meta

# ---------------------------------------------------------------------------
# Backend B -- transformers Whisper (Python 3.13 fallback).
# Pure torch: no ctranslate2, no native wheel to be missing.
# plan.md §0.2 named this as the documented escape hatch.
# ---------------------------------------------------------------------------
class TransformersWhisperBackend:
    name = 'transformers'
    has_builtin_vad = False

    def __init__(self, pipe, info, vad_fn, vad_backend):
        self.pipe, self.info = pipe, info
        self.vad_fn, self.vad_backend = vad_fn, vad_backend
        self._vad_dropped = 0

    @classmethod
    def load(cls, cfg: ASRConfig, prefer_gpu: bool = True):
        from transformers import pipeline
        import torch as _torch
        device = 0 if (prefer_gpu and HAS_CUDA) else -1
        dtype = _torch.float16 if (prefer_gpu and HAS_CUDA) else _torch.float32
        errors = []
        for name in cfg.hf_model_candidates:
            t0 = time.time()
            try:
                pipe = pipeline('automatic-speech-recognition', model=name,
                                torch_dtype=dtype, device=device)
                _ = pipe({'raw': np.zeros(8000, dtype=np.float32), 'sampling_rate': 16000},
                         return_timestamps='word')
                vad_fn, vad_backend = load_vad(cfg)
                return cls(pipe, {'backend': cls.name, 'model': name,
                                  'device': 'cuda' if device == 0 else 'cpu',
                                  'compute_type': str(dtype).replace('torch.', ''),
                                  'load_seconds': round(time.time() - t0, 2)},
                           vad_fn, vad_backend)
            except Exception as exc:
                errors.append(f'{name}: {type(exc).__name__}: {str(exc)[:110]}')
        raise RuntimeError('transformers Whisper: no model loaded.\n  ' + '\n  '.join(errors))

    def transcribe_raw(self, audio_path, cfg: ASRConfig) -> tuple:
        audio = read_wav_mono16k(audio_path)
        duration = len(audio) / 16000.0

        # Map the ASRConfig knobs onto HF generate(). Added defensively: generate()
        # rejects unknown kwargs and the accepted set shifts between transformers
        # releases, so an unsupported one must not lose you the whole transcript.
        gen_kwargs = {'task': 'transcribe', 'do_sample': False}   # greedy == reproducible
        if cfg.language:
            gen_kwargs['language'] = cfg.language
        if cfg.beam_size and cfg.beam_size > 1:
            gen_kwargs['num_beams'] = cfg.beam_size
        gen_kwargs['condition_on_prev_tokens'] = cfg.condition_on_previous_text
        if cfg.initial_prompt:
            try:
                gen_kwargs['prompt_ids'] = self.pipe.tokenizer.get_prompt_ids(
                    cfg.initial_prompt, return_tensors='pt').to(self.pipe.model.device)
            except Exception:
                pass    # not fatal -- brand_vocabulary still corrects post-hoc

        def _run(kw):
            return self.pipe({'raw': audio, 'sampling_rate': 16000},
                             return_timestamps='word', chunk_length_s=30,
                             generate_kwargs=kw)

        used_kwargs = dict(gen_kwargs)
        try:
            out = _run(gen_kwargs)
        except (TypeError, ValueError) as exc:
            print(f'  generate() rejected a kwarg ({str(exc)[:90]}) -> retrying minimal')
            used_kwargs = {'task': 'transcribe'}
            if cfg.language:
                used_kwargs['language'] = cfg.language
            out = _run(used_kwargs)

        # ---- normalize the word chunks -------------------------------------
        raw_words, prev_end = [], 0.0
        for ch in out.get('chunks', []):
            ts = ch.get('timestamp') or (None, None)
            start = ts[0] if ts[0] is not None else prev_end
            end = ts[1] if ts[1] is not None else start + 0.20
            raw_words.append({'word': ch.get('text', ''),
                              'start': round(float(start), 3), 'end': round(float(end), 3),
                              # the pipeline exposes no per-token probability
                              'probability': 1.0})
            prev_end = end

        # ---- apply VAD post-hoc (the transformers path has none built in) ---
        vad_regions = []
        self._vad_dropped = 0
        if cfg.vad_filter and self.vad_fn is not None:
            vad_regions = self.vad_fn(audio)
            if vad_regions:
                def in_speech(w):
                    mid = (w['start'] + w['end']) / 2.0
                    return any(r['start'] <= mid <= r['end'] for r in vad_regions)
                before = len(raw_words)
                raw_words = [w for w in raw_words if in_speech(w)]
                self._vad_dropped = before - len(raw_words)
                if self._vad_dropped:
                    print(f'  VAD dropped {self._vad_dropped} word(s) outside detected speech '
                          f'({len(vad_regions)} speech region(s))')
            else:
                # No speech anywhere. On a music-only clip this is the CORRECT
                # answer, and it is exactly the hallucination case VAD exists for.
                self._vad_dropped = len(raw_words)
                if raw_words:
                    print(f'  VAD found NO speech regions -> dropping all '
                          f'{len(raw_words)} word(s) as hallucination')
                raw_words = []

        # ---- group words into segments (faster-whisper does this itself) ----
        segments, buf = [], []

        def flush():
            if not buf:
                return
            text = ''.join(w['word'] for w in buf)
            segments.append({
                'id': len(segments), 'start': buf[0]['start'], 'end': buf[-1]['end'],
                'text': text,
                'avg_logprob': None,        # not exposed by the pipeline
                'no_speech_prob': None,     # not exposed by the pipeline
                'compression_ratio': round(compression_ratio(text), 4),
                'words': list(buf),
            })
            buf.clear()

        for w in raw_words:
            if buf and (w['start'] - buf[-1]['end'] > cfg.segment_gap_s
                        or len(buf) >= cfg.segment_max_words
                        or buf[-1]['word'].strip().endswith(('.', '?', '!'))):
                flush()
            buf.append(w)
        flush()

        meta = {'language': cfg.language or 'unknown', 'language_probability': 0.0,
                'audio_duration_seconds': round(duration, 3),
                'vad_backend': self.vad_backend,
                'vad_regions': vad_regions,
                'vad_speech_seconds': round(sum(r['end'] - r['start'] for r in vad_regions), 2),
                'words_dropped_by_vad': self._vad_dropped,
                # degraded ONLY when VAD is genuinely missing. With silero-vad
                # present this path carries the same anti-hallucination guarantee
                # as faster-whisper, and must not be labelled degraded.
                'degraded': self.vad_backend == 'none',
                'decode_params': {k: str(v)[:40] for k, v in used_kwargs.items()},
                'note': ('avg_logprob / no_speech_prob are not exposed by the '
                         'transformers pipeline; those two post-filters are skipped. '
                         'compression_ratio is computed locally and still applies.')}
        return segments, meta

def load_asr(cfg: ASRConfig, prefer_gpu: bool = True) -> tuple:
    """
    Selects the best available backend. Returns (backend, info).
    On Python 3.13, faster-whisper may be absent -- the transformers path is
    a full substitute apart from the built-in VAD.
    """
    order = []
    if cfg.backend in ('auto', 'faster_whisper') and BACKENDS.get('faster_whisper'):
        order.append(FasterWhisperBackend)
    if cfg.backend in ('auto', 'transformers') and BACKENDS.get('transformers'):
        order.append(TransformersWhisperBackend)
    if not order:
        raise RuntimeError('No ASR backend importable. Re-run §0.1.')

    errors = []
    for backend_cls in order:
        try:
            backend = backend_cls.load(cfg, prefer_gpu)
            i = backend.info
            print(f'ASR ready: [{i["backend"]}] {i["model"]} on {i["device"]}/'
                  f'{i["compute_type"]}  ({i["load_seconds"]}s)')
            if backend_cls is TransformersWhisperBackend:
                if backend.vad_backend == 'none':
                    print('  WARNING: no VAD available. Hallucination over music is likely.')
                    print('           The transcript will be marked degraded (§13 flags it).')
                else:
                    print(f'  VAD: {backend.vad_backend} (loaded separately)')
            return backend, backend.info
        except Exception as exc:
            errors.append(f'{backend_cls.name}: {type(exc).__name__}: {str(exc)[:140]}')
            print(f'  {backend_cls.name} failed -> trying next')
    raise RuntimeError('All ASR backends failed.\n  ' + '\n  '.join(errors))

def _segment_filter_reason(seg: dict, cfg: ASRConfig) -> Optional[str]:
    text = seg['text'].strip()
    if not text:
        return 'EMPTY'
    # The transformers backend cannot expose no_speech_prob / avg_logprob, so those
    # two filters are skipped rather than silently applied against a fake 0.0.
    # compression_ratio is computed by us, so it ALWAYS applies -- which matters,
    # because it is the filter that catches degenerate repetition.
    if seg.get('no_speech_prob') is not None and seg['no_speech_prob'] > cfg.no_speech_threshold:
        return 'NO_SPEECH_PROB'
    if seg.get('avg_logprob') is not None and seg['avg_logprob'] < cfg.log_prob_threshold:
        return 'LOW_LOGPROB'
    if seg.get('compression_ratio') is not None and seg['compression_ratio'] > cfg.compression_ratio_threshold:
        return 'HIGH_COMPRESSION'
    return None

def _hallucination_flags(text: str) -> list:
    low = text.lower()
    return [p for p in HALLUCINATION_PHRASES if p in low]

def _correct_brand_terms(words: list, cfg: ASRConfig) -> list:
    """Fuzzy-correct phonetic brand transcriptions. Never destructive."""
    if not cfg.brand_vocabulary:
        return []
    corrections = []
    for i, w in enumerate(words):
        tok = normalize_token(w.get('word', ''))
        if len(tok) < 3:
            continue
        best, best_score = None, 0
        for brand in cfg.brand_vocabulary:
            s = fuzz.ratio(tok, normalize_token(brand))
            if s > best_score:
                best, best_score = brand, s
        if best and best_score >= cfg.brand_match_threshold and tok != normalize_token(best):
            corrections.append({'word_index': i, 'heard': w.get('word', '').strip(),
                                'corrected_to': best, 'score': int(best_score),
                                'start': w.get('start'), 'end': w.get('end')})
    return corrections

def transcribe(backend, audio_path, cfg: ASRConfig, model_info: dict) -> dict:
    """
    Backend-agnostic. `backend` is whatever load_asr() returned -- the two
    implementations differ only in transcribe_raw(), so everything below
    (filtering, indexing, brand correction, stats) is shared.
    """
    t0 = time.time()
    raw_segments, meta = backend.transcribe_raw(audio_path, cfg)
    all_words = []

    # ---- post-filtering, explicit and logged --------------------------------
    kept, dropped, prev_text = [], [], None
    for seg in raw_segments:
        reason = _segment_filter_reason(seg, cfg)
        flags = _hallucination_flags(seg['text'])
        if reason is None and seg['text'].strip() == (prev_text or '').strip():
            reason = 'REPEATED'
        # a known hallucination phrase is only dropped if the stats are ALSO weak
        if reason is None and flags and (seg['no_speech_prob'] > 0.3 or seg['avg_logprob'] < -0.7):
            reason = 'HALLUCINATION_PHRASE'
        seg['hallucination_flags'] = flags
        if reason:
            dropped.append({**seg, 'filter_reason': reason})
        else:
            kept.append(seg)
            all_words.extend(seg['words'])
            prev_text = seg['text']

    normalized_text, spans = build_word_index(all_words)
    corrections = _correct_brand_terms(all_words, cfg)

    elapsed = time.time() - t0
    audio_dur = float(meta.get('audio_duration_seconds', 0.0) or 0.0)

    return {
        'schema_version': ASR_STAGE_VERSION,
        'backend': model_info.get('backend', 'unknown'),
        'vad_backend': meta.get('vad_backend', 'unknown'),
        'degraded': bool(meta.get('degraded', False)),
        'degradation_reason': ('no VAD available — hallucination over music not suppressed'
                               if meta.get('degraded') else None),
        'vad': {'backend': meta.get('vad_backend'),
                'regions': meta.get('vad_regions', []),
                'speech_seconds': meta.get('vad_speech_seconds'),
                'words_dropped': meta.get('words_dropped_by_vad', 0)},
        'decode_params': meta.get('decode_params'),
        'backend_note': meta.get('note'),
        'language': meta.get('language', cfg.language),
        'language_probability': meta.get('language_probability', 0.0),
        'audio_duration_seconds': round(audio_dur, 3),
        'full_text': ' '.join(s['text'].strip() for s in kept).strip(),
        'segments': kept,
        'words': all_words,
        'normalized_text': normalized_text,
        'word_spans': spans,
        'filtered_segments': dropped,
        'brand_corrections': corrections,
        'stats': {
            'segments_raw': len(raw_segments),
            'segments_kept': len(kept),
            'segments_dropped': len(dropped),
            'drop_reasons': {r: sum(1 for d in dropped if d['filter_reason'] == r)
                             for r in {d['filter_reason'] for d in dropped}},
            'word_count': len(all_words),
            'speech_seconds': round(sum(s['end'] - s['start'] for s in kept), 2),
            'speech_ratio': round(sum(s['end'] - s['start'] for s in kept) / audio_dur, 3) if audio_dur else 0.0,
            'mean_word_probability': round(float(np.mean([w['probability'] for w in all_words])), 4) if all_words else 0.0,
            'transcribe_seconds': round(elapsed, 2),
            'realtime_factor': round(audio_dur / elapsed, 2) if elapsed > 0 else 0.0,
        },
        'model': model_info,
        'config': asdict(cfg),
    }


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 481: print('whisper.py loaded')
