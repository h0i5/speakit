"""Preload CUDA libs from nvidia pip wheels before ctranslate2 imports.

ctranslate2 4.x is built against CUDA 12 + cuDNN 9 and resolves those shared
libraries via the dynamic loader. If the system CUDA is a different major
(e.g. 13) or cuDNN is absent, the load fails. The nvidia-*-cu12 wheels ship
self-contained .so files; preloading them with RTLD_GLOBAL satisfies
ctranslate2's symbol references regardless of what's on the system.

Call preload() once, before importing faster_whisper / ctranslate2.
No-op (and harmless) if the wheels aren't installed or we're on CPU.
"""
from __future__ import annotations

import ctypes
import glob
import os
import sys


def _wheel_lib_dirs() -> list[str]:
    dirs: list[str] = []
    for entry in sys.path:
        if not entry or not entry.endswith("site-packages"):
            continue
        for sub in ("cublas", "cudnn"):
            d = os.path.join(entry, "nvidia", sub, "lib")
            if os.path.isdir(d):
                dirs.append(d)
    return dirs


def preload() -> bool:
    """Preload cuBLAS + cuDNN from wheels. Returns True if anything loaded."""
    loaded = False
    for d in _wheel_lib_dirs():
        # Load in dependency order: cublasLt -> cublas, cudnn graph/ops -> cudnn.
        for pattern in (
            "libcublasLt.so*",
            "libcublas.so*",
            "libcudnn_*.so*",
            "libcudnn.so*",
        ):
            for so in sorted(glob.glob(os.path.join(d, pattern))):
                try:
                    ctypes.CDLL(so, mode=ctypes.RTLD_GLOBAL)
                    loaded = True
                except OSError:
                    pass
    return loaded
