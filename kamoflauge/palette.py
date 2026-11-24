"""Claude Code처럼 입력창에 `/`를 치면 뜨는 명령어 목록."""
from __future__ import annotations

from dataclasses import dataclass

from rich.cells import cell_len
from rich.text import Text
from textual.widgets import Static

ACCENT = "#b1b9f9"   # 선택된 줄 (Claude Code의 보라빛 하이라이트)
DIM = "#8a8a8a"
MAX_ROWS = 8


@dataclass(frozen=True)
class Command:
    name: str           # 슬래시 없이
    args: str = ""      # 인자 힌트, 예: "<room>"
    desc: str = ""
    aliases: tuple = ()

    @property
    def needs_arg(self) -> bool:
        return self.args.startswith("<")


COMMANDS: tuple[Command, ...] = (
    Command("help", "", "도움말과 명령어 목록"),
    Command("open-chatroom", "<방>", "다른 방 열기 (예: /open-chatroom 점심팟)", ("oc",)),
    Command("close-chatroom", "", "지금 방 창 닫기", ("cc",)),
    Command("switch", "<번호|이름>", "열린 방 사이 이동 (ctrl+n / ctrl+p)", ("open", "o", "cd")),
    Command("rooms", "", "열린 방 목록", ("ls", "files")),
    Command("mute", "", "지금 방 알림 끄기 / 켜기"),
    Command("auto", "", "auto-claude 켜기 / 끄기 (가짜 작업 로그)", ("claude",)),
    Command("speed", "[빠르게|보통|느리게]", "가짜 작업 로그가 나오는 빈도", ("freq",)),
    Command("panic", "", "패닉 모드: 카톡 내용 숨기기 (esc와 같음, ctrl+b로 복귀)", ("boss",)),
    Command("who", "", "지금 방의 실제 이름 보기", ("real",)),
    Command("alias", "[이름] [파일명]", "가명 직접 지정 (예: /alias 엄마 config.yaml)"),
    Command("clear", "", "화면 지우기"),
    Command("quit", "", "종료", ("exit",)),
)


def find_command(name: str) -> Command | None:
    for c in COMMANDS:
        if name == c.name or name in c.aliases:
            return c
    return None


def match_commands(query: str) -> list[Command]:
    """'/clo' → close-chatroom 처럼 앞부분 일치를 먼저, 그다음 중간 일치."""
    q = query.lower()
    starts = [c for c in COMMANDS if c.name.startswith(q) or any(a.startswith(q) for a in c.aliases)]
    contains = [c for c in COMMANDS if q in c.name and c not in starts]
    return starts + contains


@dataclass(frozen=True)
class Item:
    label: str          # 왼쪽 열 (명령어 또는 방 이름)
    desc: str           # 오른쪽 열
    value: str          # 고르면 실행/완성할 값 (명령어 이름 또는 방 실명)
    kind: str           # "command" | "room" (Enter로 완성) | "hint" (안내만)


class Palette(Static):
    """입력창 아래 목록. 위/아래로 고르고 Tab으로 완성, Enter로 실행한다."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.items: list[Item] = []
        self.index = 0
        self.display = False

    @property
    def visible(self) -> bool:
        return bool(self.display and self.items)

    @property
    def selected(self) -> Item | None:
        return self.items[self.index] if self.visible else None

    def show(self, items: list[Item]) -> None:
        keep = self.selected.value if self.selected else None
        self.items = items
        values = [i.value for i in items]
        self.index = values.index(keep) if keep in values else 0
        self.display = bool(items)
        self._paint()

    def hide(self) -> None:
        self.items = []
        self.display = False

    def move(self, step: int) -> None:
        if self.items:
            self.index = (self.index + step) % len(self.items)
            self._paint()

    def _paint(self) -> None:
        if not self.items:
            return
        top = min(max(0, self.index - MAX_ROWS + 1), max(0, len(self.items) - MAX_ROWS))
        width = max(cell_len(i.label) for i in self.items) + 4
        out = Text()
        for n, item in enumerate(self.items[top:top + MAX_ROWS], start=top):
            sel = n == self.index
            out.append(item.label + " " * (width - cell_len(item.label)), style=f"bold {ACCENT}" if sel else "")
            out.append(item.desc, style=ACCENT if sel else DIM)
            out.append("\n")
        out.rstrip()
        self.update(out)
