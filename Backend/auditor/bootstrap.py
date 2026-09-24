"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 3.
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
# §0.2  Imports, hardware profile, backend detection
#
# VRAM DISCIPLINE (plan.md resource lever 2): never hold Whisper and OCR
# resident at once. Whisper -> GPU. OCR -> CPU, which also sidesteps the whole
# ONNXRuntime/CUDA conflict class.
# ============================================================================
import os, gc, io, json, math, time, tarfile, hashlib, dataclasses, traceback

import subprocess, shutil, platform, re, string, wave, zlib, importlib

# textwrap is used at module level in §43, §47 and §48 and was imported
# only in §74 -- fine in a session that had already run the self-check,
# a NameError on a fresh kernel run top to bottom.
import textwrap

from pathlib import Path

from typing import Optional, Literal, Any

from dataclasses import dataclass, field, asdict

import numpy as np

import cv2

import av

from PIL import Image

from pydantic import BaseModel, Field

import matplotlib.pyplot as plt

import pandas as pd

from rapidfuzz import fuzz

import pydantic

# ---- hardware --------------------------------------------------------------
try:
    import torch
    HAS_CUDA = torch.cuda.is_available()
    GPU_NAME = torch.cuda.get_device_name(0) if HAS_CUDA else 'none'
    CAP = torch.cuda.get_device_capability(0) if HAS_CUDA else (0, 0)
except Exception as _exc:
    HAS_CUDA, GPU_NAME, CAP = False, 'none', (0, 0)
    print(f'torch unusable: {type(_exc).__name__}: {str(_exc)[:160]}')

# ---- is the CUDA stack internally consistent? ------------------------------
# torch, torchvision and torchaudio are built and released together. A mismatch
# means something pip-installed moved one of them, and every CUDA call after
# this point is unreliable. Catching it HERE, in ten lines, is the difference
# between a clear message and debugging a vision-model load twenty cells later.
import importlib.metadata as _md2

# ---- which backends actually imported --------------------------------------
def _importable(name: str) -> bool:
    try:
        importlib.import_module(name); return True
    except Exception:
        return False

BACKENDS = {
    'faster_whisper': _importable('faster_whisper'),
    'transformers':   _importable('transformers'),
    'silero_vad':     _importable('silero_vad'),
    'rapidocr':       _importable('rapidocr_onnxruntime') or _importable('rapidocr'),
    'paddleocr':      _importable('paddleocr'),
    'pytesseract':    _importable('pytesseract') and shutil.which('tesseract') is not None,
    'wordninja':      _importable('wordninja'),
}


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 27: print(f'python         {platform.python_version()}')
#   line 28: print(f'numpy          {np.__version__}')
#   line 29: print(f'opencv         {cv2.__version__}')
#   line 30: print(f'PyAV           {av.__version__}')
#   line 31: print(f"ffmpeg libs    {av.library_versions.get('libavformat', '?')} (libavf
#   line 34: print(f'pydantic       {pydantic.VERSION}')
#   line 35: assert pydantic.VERSION.startswith('2'), 'This notebook targets pydantic v2.
#   line 37: for binary in ('ffmpeg', 'ffprobe'):
#   line 57: _stack = {}
#   line 58: for _p in ('torch', 'torchvision', 'torchaudio'):
#   line 63: print('\ntorch stack:')
#   line 64: for _p, _v in _stack.items():
#   line 72: _present = {k: v for k, v in _stack.items() if v}
#   line 73: _tags = {k: v.split('+')[1] if '+' in v else '' for k, v in _present.items()
#   line 74: _broken = []
#   line 75: if not _stack['torch']:
#   line 91: if _stack['torch'] and _stack['torchvision']:
#   line 102: if any(('torchvision' in b for b in _broken)):
#   line 109: if _stack['torch'] and _tags.get('torch', '').startswith('cu') and (not HAS_
#   line 113: if _broken:
#   line 164: if HAS_CUDA:
#   line 188: print('\nbackends available:')
#   line 189: for k, v in BACKENDS.items():
