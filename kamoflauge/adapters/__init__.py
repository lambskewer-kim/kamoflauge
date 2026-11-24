from __future__ import annotations

from .base import Adapter


def get_adapter(name: str = "auto", raw_config: dict | None = None) -> Adapter:
    """name: 'auto'(지금 OS), 'mock', 'mac', 'windows'. OS별 어댑터는 kamoflauge/platforms/ 아래에 있다."""
    if name == "mock":
        from .mock import MockAdapter
        return MockAdapter()
    from ..platforms import load
    return load("cli", None if name == "auto" else name).make_adapter(raw_config or {})
