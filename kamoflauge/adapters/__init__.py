from __future__ import annotations

import sys

from .base import Adapter


def get_adapter(name: str = "auto", **opts) -> Adapter:
    if name == "auto":
        name = {"darwin": "macos", "win32": "windows"}.get(sys.platform, "mock")
    if name == "mock":
        from .mock import MockAdapter
        return MockAdapter()
    if name == "macos":
        from .macos import MacKakaoAdapter
        return MacKakaoAdapter(**opts)
    if name == "windows":
        from .windows import WinKakaoAdapter
        return WinKakaoAdapter(**opts)
    raise ValueError(f"unknown adapter: {name}")
