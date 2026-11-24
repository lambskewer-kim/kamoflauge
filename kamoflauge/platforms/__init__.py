"""OS별 코드 고르기. 맥 전용 코드는 platforms/mac/, 윈도우 전용 코드는 platforms/windows/에만 둔다.

각 플랫폼 패키지는 같은 이름을 제공한다:
  adapter.py  카톡을 읽고 쓰는 어댑터 (adapters.base.Adapter 구현)
  shift.py    ShiftWatcher (shift_down(), diagnose_header(), diagnose_line())
  cli.py      make_adapter(raw), check_header(raw), check_footer(ad), dump_tree(path, redact)
  theme.py    BULLET, SPIN, STAR (터미널마다 이모지로 그려지는 기호가 달라서)
"""
from __future__ import annotations

import importlib
import sys
from types import ModuleType

NAMES = {"darwin": "mac", "win32": "windows"}


def current() -> str:
    """지금 OS의 플랫폼 이름 ('mac', 'windows'), 지원하지 않으면 ''."""
    return NAMES.get(sys.platform, "")


def load(part: str, name: str | None = None) -> ModuleType:
    """플랫폼 모듈 하나를 불러온다. 예: load('cli') → kamoflauge.platforms.mac.cli"""
    name = name or current()
    if not name:
        raise RuntimeError(f"지원하지 않는 OS입니다: {sys.platform} (--mock 으로 화면만 볼 수 있어요)")
    return importlib.import_module(f"{__name__}.{name}.{part}")


class NoShift:
    """Shift 감지를 쓸 수 없을 때 (지원 안 하는 OS, 권한/라이브러리 문제)."""
    available = False

    def shift_down(self) -> bool:
        return False


def theme() -> ModuleType:
    """글자 모양 (BULLET, SPIN, STAR). 지원 안 하는 OS(--mock)는 맥 모양을 쓴다."""
    try:
        return load("theme")
    except RuntimeError:
        return load("theme", "mac")


def shift_watcher():
    try:
        return load("shift").ShiftWatcher()
    except Exception:  # noqa: BLE001  기능만 끄고 프로그램은 계속 돈다
        return NoShift()
