"""가짜 Claude 작업 로그가 섞이는 빈도 (빠르게 / 보통 / 느리게)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Speed:
    key: str
    label: str            # 화면에 보이는 한국어 이름
    every: tuple          # 평소 가짜 로그 간격(초) 범위
    history_mix: float    # 방을 처음 열 때 메시지 사이에 가짜 로그를 끼울 확률


SPEEDS = (
    Speed("fast", "빠르게", (3.0, 8.0), 0.6),
    Speed("normal", "보통", (8.0, 20.0), 0.3),
    Speed("slow", "느리게", (20.0, 45.0), 0.12),
)
DEFAULT = "normal"
_ALIASES = {"빠름": "fast", "빨리": "fast", "중간": "normal", "느림": "slow", "천천히": "slow"}


def find_speed(text: str) -> Speed | None:
    """'fast', '빠르게', '빠름' 등을 Speed로. 모르는 값이면 None."""
    t = text.strip().lower()
    t = _ALIASES.get(t, t)
    return next((s for s in SPEEDS if t in (s.key, s.label)), None)


def get_speed(text: str) -> Speed:
    return find_speed(text) or find_speed(DEFAULT)


def next_speed(cur: Speed) -> Speed:
    i = SPEEDS.index(cur)
    return SPEEDS[(i + 1) % len(SPEEDS)]
