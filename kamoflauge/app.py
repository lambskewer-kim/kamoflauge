from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field

from rich.console import Group
from rich.panel import Panel
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Input, Label, RichLog, Static

from .adapters.base import Adapter
from .disguise import VERBS, Disguise, fake_event
from .models import Message, Room
from .shift import ShiftWatcher
from .sync import new_messages

ORANGE = "#d77757"
DIM = "#8a8a8a"
GREEN = "#4eba65"
REVEAL = "#e5c07b"
REVEAL_HOLD = 0.3  # Shift를 이만큼(초) 계속 누르고 있어야 실명을 보여준다 (한글 쌍자음 입력과 구분)
SPIN = "·✢✳✶✻✽✻✶✳✢"
BG_EVERY = 4  # 방 목록/다른 방은 폴링 4번에 한 번


@dataclass
class Entry:
    lines: list[tuple[str, str]]  # (style, text)
    real: bool                    # True면 카톡 내용 → 보스 모드에서 숨김
    fake: bool = False            # True면 가짜 Claude 작업 로그 → Shift로 실명 볼 때 숨김


@dataclass
class Config:
    aliases: dict = field(default_factory=dict)
    cwd: str = "~/research/vision-transformer"
    poll: float = 0.7
    filler: bool = True           # 평소에도 가끔 가짜 작업 로그 섞기
    filler_every: tuple = (8.0, 20.0)
    history: int = 15
    strip_emoji: bool = True
    show_time: bool = False


class Kamoflauge(App):
    CSS_PATH = "app.tcss"
    TITLE = "claude"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("ctrl+b", "boss", "boss", show=False, priority=True),
        Binding("shift+tab", "toggle_claude", "mode", show=False, priority=True),
        Binding("escape", "boss_on", "panic", show=False, priority=True),
        Binding("ctrl+n", "next_room", "next", show=False, priority=True),
        Binding("ctrl+p", "prev_room", "prev", show=False, priority=True),
        Binding("ctrl+c", "quit_twice", "quit", show=False, priority=True),
    ]

    def __init__(self, adapter: Adapter, cfg: Config | None = None):
        super().__init__()
        self.adapter = adapter
        self.cfg = cfg or Config()
        self.dis = Disguise(self.cfg.aliases, self.cfg.strip_emoji)
        self.entries: list[Entry] = []
        self.boss = False
        self.reveal = False               # Shift를 누르고 있는 동안 실명 표시
        self._shift = ShiftWatcher()
        self._shift_since = 0.0
        self._last_typed = 0.0
        self.claude_on = self.cfg.filler  # True: 가짜 작업 로그를 섞음, False: 채팅만
        self.rooms: list[Room] = []
        self.current: Room | None = None
        self.snapshots: dict[str, list[Message]] = {}
        self.unread: dict[str, int] = {}
        self.pending_echo: list[tuple[str, str]] = []
        self.last_sender: tuple[str, str] | None = None
        self.verb = random.choice(VERBS)
        self.spin_start = time.time()
        self.tokens = random.uniform(1.0, 4.0)
        self._quit_armed = 0.0
        self._next_filler = time.time() + random.uniform(*self.cfg.filler_every)
        self._polling = False
        self._poll_n = 0

    # ---------- layout ----------
    def compose(self) -> ComposeResult:
        yield RichLog(id="log", wrap=True, markup=False, auto_scroll=True)
        yield Static(id="spinner")
        with Horizontal(id="prompt-box"):
            yield Label(">")
            yield Input(id="prompt", placeholder='Try "fix lint errors"')
        yield Static(id="footer")

    async def on_mount(self) -> None:
        self.query_one("#prompt", Input).focus()
        self.call_after_refresh(self._sync_ime_cursor)
        self._welcome()
        self.set_interval(0.12, self._tick_spinner)
        self.set_interval(self.cfg.poll, self._poll)
        await self._refresh_rooms()
        if self.rooms:
            await self._open(self.rooms[0])
        else:
            self._sys("No open chat windows found. Open a chat window in KakaoTalk, then /rooms")
        self._update_footer()

    # ---------- rendering ----------
    def _welcome(self) -> None:
        body = Group(
            Text.assemble(("✻ ", ORANGE), ("Welcome to ", "bold"), ("Claude Code", "bold"), ("!", "bold")),
            Text(""),
            Text("  /help for help, /status for your current setup", style=f"italic {DIM}"),
            Text(""),
            Text(f"  cwd: {self.cfg.cwd}", style=DIM),
        )
        log = self.query_one("#log", RichLog)
        log.write(Panel(body, border_style=ORANGE, expand=False, padding=(0, 1), width=58))
        log.write(Text(""))
        log.write(Text(" Tips for getting started:", style=DIM))
        log.write(Text(""))
        log.write(Text(" 1. Ask Claude to create a new app or clone a repository", style=DIM))
        log.write(Text(" 2. Use Claude to help with file analysis, editing, bash commands and git", style=DIM))
        log.write(Text(" 3. Be as specific as you would with another engineer for the best results", style=DIM))
        log.write(Text(""))

    def _render_line(self, style: str, text: str) -> Text:
        if style == "tool":
            name, _, arg = text.partition("(")
            return Text.assemble(("⏺ ", "#4eba65"), (name, "bold"), (("(" + arg) if arg else "", ""))
        if style == "msg":
            head, _, real = text.partition("\0")
            t = Text.assemble(("⏺ ", "#4eba65"), ("Read", "bold"), (f"({head})", ""))
            if self.reveal and real:
                t.append(f"  ← {real}", style=f"bold {REVEAL}")
            return t
        if style == "tool_dim":
            name, _, arg = text.partition("(")
            return Text.assemble(("⏺ ", DIM), (name, "bold"), (("(" + arg) if arg else "", ""))
        if style == "result":
            return Text.assemble(("  ⎿  ", DIM), (text, ""))
        if style == "result_dim":
            return Text.assemble(("  ⎿  ", DIM), (text, DIM))
        if style == "cont":
            return Text.assemble(("     ", ""), (text, ""))
        if style == "user":
            return Text.assemble(("> ", DIM), (text, DIM))
        if style == "prose":
            return Text.assemble(("⏺ ", "#ffffff"), (text, ""))
        if style == "sys":
            return Text(f"  ⎿  {text}", style=DIM)
        if style == "blank":
            return Text("")
        return Text(text)

    def _write_entry(self, e: Entry) -> None:
        log = self.query_one("#log", RichLog)
        for st, tx in e.lines:
            log.write(self._render_line(st, tx))

    def _visible(self, e: Entry) -> bool:
        if e.real and self.boss:
            return False
        return not (e.fake and self.reveal)

    def _add(self, lines: list[tuple[str, str]], real: bool, fake: bool = False) -> None:
        while lines and lines[-1][0] == "blank":
            lines = lines[:-1]
        if lines and lines[0][0] != "cont":
            lines = [("blank", "")] + lines
        e = Entry(lines, real, fake)
        self.entries.append(e)
        if len(self.entries) > 600:
            self.entries = self.entries[-400:]
        if self._visible(e):
            self._write_entry(e)

    def _rebuild(self) -> None:
        log = self.query_one("#log", RichLog)
        log.clear()
        self._welcome()
        for e in self.entries:
            if self._visible(e):
                self._write_entry(e)

    def _sys(self, text: str) -> None:
        self._add([("sys", text)], real=False)

    def _render_msg(self, room: Room, m: Message) -> list[tuple[str, str]]:
        body = self.dis.text(m.text).split("\n")
        if self.cfg.show_time and m.time:
            body[-1] += f"  ({m.time})"
        if m.is_me:
            self.last_sender = None
            return [("user", body[0])] + [("cont", b) for b in body[1:]]
        who = (room.id, m.sender)
        if self.last_sender == who and self.entries and self.entries[-1].real:
            # 같은 사람 연속 메시지: 이전 블록에 이어 붙인 것처럼 보이게
            return [("cont", b) for b in body]
        self.last_sender = who
        head = f"{self.dis.room_dir(room.name)}/{self.dis.alias(m.sender or room.name)}"
        real = room.name if m.sender in ("", room.name) else f"{room.name} · {m.sender}"
        return [("msg", f"{head}\0{real}"),
                ("result", body[0])] + [("cont", b) for b in body[1:]]

    # ---------- spinner / footer ----------
    def _sync_ime_cursor(self) -> None:
        """터미널 커서를 입력창 커서 위치에 둔다.

        한글 IME는 조합 중인 글자를 터미널 커서 자리에 그린다. Textual은 입력창 선택이 바뀔 때만
        커서를 옮기는데, 마운트 시점에는 아직 레이아웃 전이라 엉뚱한 곳(화면 중간)에 남는다.
        """
        prompt = self.query_one("#prompt", Input)
        if self.focused is prompt and prompt.region.width:
            self.cursor_position = prompt.cursor_screen_offset

    def _check_reveal(self) -> None:
        now = time.time()
        held = self._shift.shift_down() and now - self._last_typed > REVEAL_HOLD
        if not held:
            self._shift_since = 0.0
        elif not self._shift_since:
            self._shift_since = now
        want = held and now - self._shift_since >= REVEAL_HOLD and not self.boss
        if want != self.reveal:
            self.reveal = want
            self._rebuild()
            self._update_footer()

    def on_input_changed(self, _ev: Input.Changed) -> None:
        self._last_typed = time.time()

    def _tick_spinner(self) -> None:
        self._sync_ime_cursor()
        self._check_reveal()
        el = int(time.time() - self.spin_start)
        if el > random.randint(25, 90):
            self.spin_start, self.verb = time.time(), random.choice(VERBS)
            el = 0
        self.tokens += random.uniform(0, 0.02)
        frame = SPIN[int(time.time() * 8) % len(SPIN)]
        spinner = self.query_one("#spinner", Static)
        if self.reveal:
            spinner.update("")
            return
        spinner.update(Text.assemble(
            (f"{frame} {self.verb}… ", ORANGE),
            (f"({el}s · ↑ {self.tokens:.1f}k tokens · esc to interrupt)", DIM),
        ))
        if self.claude_on or self.boss:
            if time.time() >= self._next_filler:
                lo, hi = self.cfg.filler_every
                if self.boss:
                    lo, hi = lo / 3, hi / 3
                self._next_filler = time.time() + random.uniform(lo, hi)
                self._add(fake_event(), real=False, fake=True)
                self.last_sender = None

    def _room_label(self) -> str:
        """현재 방을 'trainer/ (1/3)'처럼 보여준다. 패닉 모드나 방이 없으면 빈 문자열."""
        if not self.current or self.boss:
            return ""
        ids = [r.id for r in self.rooms]
        pos = f" ({ids.index(self.current.id) + 1}/{len(ids)})" if self.current.id in ids and len(ids) > 1 else ""
        return f"{self.dis.room_dir(self.current.name)}/{pos}"

    def _update_footer(self) -> None:
        room = self._room_label()
        left = Text.assemble(("⎇ ", DIM), (room, "bold #d0d0d0"), ("  ctrl+n/p to switch", DIM)) if room \
            else Text("? for shortcuts", style=DIM)
        if room and self.reveal:
            left = Text.assemble(("⎇ ", DIM), (room, "bold #d0d0d0"), (f"  ← {self.current.name}", f"bold {REVEAL}"))
        bg = sum(v for k, v in self.unread.items() if not self.current or k != self.current.id)
        right = []
        if bg:
            right.append(f"● {bg} background task{'s' if bg > 1 else ''}")
        r = Text("  ·  ".join(right) + ("  ·  " if right else ""), style=DIM)
        if self.claude_on or self.boss:
            r.append("⏵⏵ auto-claude on", style=GREEN)
        else:
            r.append("⏸ auto-claude off", style=DIM)
        r.append(" (shift+tab to cycle)", style=DIM)
        try:
            w = self.size.width - 6
        except Exception:
            w = 100
        if room and not self.reveal and left.cell_len + r.cell_len + 2 > w:  # 좁으면 방 전환 안내부터 뺀다
            left = Text.assemble(("⎇ ", DIM), (room, "bold #d0d0d0"))
        pad = max(1, w - left.cell_len - r.cell_len)
        self.query_one("#footer", Static).update(left + Text(" " * pad) + r)
        prompt = self.query_one("#prompt", Input)
        prompt.placeholder = (f'Try "refactor {self.dis.room_dir(self.current.name)}/"' if room
                              else 'Try "fix lint errors"')

    # ---------- adapter I/O ----------
    async def _refresh_rooms(self) -> None:
        try:
            self.rooms = await asyncio.to_thread(self.adapter.rooms)
        except Exception as ex:  # noqa: BLE001
            self._add([("tool", "Bash(kakao status)"), ("result_dim", f"Error: {ex}")], real=True)
            self.rooms = []

    async def _open(self, room: Room) -> None:
        self.current = room
        self.unread[room.id] = 0
        self.last_sender = None
        try:
            msgs = await asyncio.to_thread(self.adapter.messages, room.id)
        except Exception as ex:  # noqa: BLE001
            self._sys(f"Error: {ex}")
            return
        self.snapshots[room.id] = msgs
        self._add([("tool_dim", f"Bash(cd {self.dis.room_dir(room.name)} && git log --oneline -{self.cfg.history})"),
                   ("result_dim", f"{len(msgs[-self.cfg.history:])} commits")], real=True)
        for m in msgs[-self.cfg.history:]:
            self._add(self._render_msg(room, m), real=True)
        self._update_footer()

    async def _poll(self) -> None:
        """현재 방은 매번, 방 목록과 다른 방은 BG_EVERY번에 한 번 읽는다 (AX 호출이 느려서)."""
        if self._polling:
            return
        self._polling = True
        try:
            self._poll_n += 1
            full = self._poll_n % BG_EVERY == 1 or not self.rooms
            if full:
                await self._poll_room_list()
            targets = self.rooms if full else [r for r in self.rooms if self.current and r.id == self.current.id]
            for r in targets:
                await self._poll_room(r)
        except Exception as ex:  # noqa: BLE001
            self.log.warning(f"poll error: {ex}")
        finally:
            self._polling = False
            self._update_footer()

    async def _poll_room_list(self) -> None:
        rooms = await asyncio.to_thread(self.adapter.rooms)
        known = {r.id for r in self.rooms}
        for r in rooms:
            if r.id not in known:
                self._sys(f"New file detected: {self.dis.alias(r.name)}")
        self.rooms = rooms
        if self.current and self.current.id not in {r.id for r in rooms}:
            self._sys("Current file was closed.")
            self.current = None

    async def _poll_room(self, r: Room) -> None:
        cur = await asyncio.to_thread(self.adapter.messages, r.id)
        prev = self.snapshots.get(r.id)
        if not cur and prev:
            return  # 일시적으로 못 읽은 것. 스냅샷을 비우면 다음에 전부 새 메시지로 쏟아진다
        self.snapshots[r.id] = cur
        if prev is None:
            return
        for m in new_messages(prev, cur):
            if m.is_me and (r.id, m.text) in self.pending_echo:
                self.pending_echo.remove((r.id, m.text))
                continue
            if self.current and r.id == self.current.id:
                self._add(self._render_msg(r, m), real=True)
            elif not m.is_me:
                self.unread[r.id] = self.unread.get(r.id, 0) + 1

    # ---------- input ----------
    async def on_input_submitted(self, ev: Input.Submitted) -> None:
        text = ev.value.strip()
        ev.input.value = ""
        if not text:
            return
        if text.startswith("/"):
            await self._command(text)
            return
        if self.boss:
            self._add([("user", text)], real=False)
            self._add(fake_event(), real=False, fake=True)
            return
        if not self.current:
            self._sys("No file open. Use /rooms then /open <n>")
            return
        room = self.current
        self.pending_echo.append((room.id, text))
        self._add([("user", text)], real=True)
        self.last_sender = None
        try:
            await asyncio.to_thread(self.adapter.send, room.id, text)
        except Exception as ex:  # noqa: BLE001
            self.pending_echo.remove((room.id, text))
            self._add([("result_dim", f"Error: {ex}")], real=True)

    async def _command(self, line: str) -> None:
        cmd, _, arg = line[1:].partition(" ")
        arg = arg.strip()
        if cmd in ("rooms", "ls", "files"):
            await self._refresh_rooms()
            lines = [("tool_dim", 'Search(pattern: "**/*", path: ".")')]
            if not self.rooms:
                lines.append(("result_dim", "No files found"))
            for i, r in enumerate(self.rooms, 1):
                u = self.unread.get(r.id, 0)
                mark = " *" if self.current and r.id == self.current.id else ""
                label = f"{i}. {self.dis.alias(r.name)}{mark}" + (f"  (+{u})" if u else "")
                lines.append(("result" if i == 1 else "cont", label))
            self._add(lines, real=True)
        elif cmd in ("open", "o", "cd"):
            await self._refresh_rooms()
            room = self._find_room(arg)
            if room:
                await self._open(room)
            else:
                self._sys(f"File not found: {arg}")
        elif cmd == "alias" and arg:
            parts = arg.split()
            if len(parts) >= 2:
                self.dis.aliases[" ".join(parts[:-1])] = parts[-1]
                self._sys(f"Updated mapping → {parts[-1]}")
        elif cmd in ("who", "real"):
            # 지금 방의 실제 이름을 잠깐 확인 (2초 뒤 사라지지 않음 주의)
            if self.current:
                self._sys(f"{self.dis.alias(self.current.name)} ↔ {self.current.name}")
        elif cmd == "boss":
            self.action_boss()
        elif cmd == "clear":
            self.entries.clear()
            self._rebuild()
        elif cmd in ("quit", "exit"):
            self.exit()
        elif cmd == "help":
            self._add([
                ("prose", "Claude Code v2.0.31"),
                ("blank", ""),
                ("cont", "/rooms              list files (chat rooms)"),
                ("cont", "/open <n|name>      open file   (ctrl+n / ctrl+p to cycle)"),
                ("cont", "/alias <이름> <file> set disguise name"),
                ("cont", "/who                show real name of current file"),
                ("cont", "/clear              clear screen"),
                ("cont", "esc                 panic: hide everything (ctrl+b to toggle back)"),
                ("cont", "shift+tab           toggle auto-claude (fake work log on/off)"),
                ("cont", "hold shift          show real names"),
                ("cont", "ctrl+c ×2           quit"),
                ("blank", ""),
            ], real=False)
        elif cmd == "status":
            self._add([("prose", "Model: claude-opus · API usage billing")], real=False)
        else:
            self._sys(f"Unknown slash command: /{cmd}")

    def _find_room(self, arg: str) -> Room | None:
        if arg.isdigit() and 1 <= int(arg) <= len(self.rooms):
            return self.rooms[int(arg) - 1]
        for r in self.rooms:
            if arg in (r.name, self.dis.alias(r.name), self.dis.room_dir(r.name)):
                return r
        for r in self.rooms:
            if arg and (arg in r.name or arg in self.dis.alias(r.name)):
                return r
        return None

    # ---------- actions ----------
    def action_boss(self) -> None:
        self.boss = not self.boss
        self._next_filler = time.time() + 0.5
        self._rebuild()
        self._update_footer()

    def action_toggle_claude(self) -> None:
        """Claude on(가짜 작업 로그 섞기) ↔ 채팅만. 패닉 모드에서는 항상 가짜 로그가 나온다."""
        self.claude_on = not self.claude_on
        self._next_filler = time.time() + random.uniform(1.0, 3.0)
        self._update_footer()

    def action_boss_on(self) -> None:
        if not self.boss:
            self.action_boss()

    async def _cycle(self, step: int) -> None:
        if self.boss or not self.rooms:
            return
        idx = 0
        if self.current:
            ids = [r.id for r in self.rooms]
            idx = (ids.index(self.current.id) + step) % len(ids) if self.current.id in ids else 0
        await self._open(self.rooms[idx])

    async def action_next_room(self) -> None:
        await self._cycle(1)

    async def action_prev_room(self) -> None:
        await self._cycle(-1)

    def action_quit_twice(self) -> None:
        now = time.time()
        if now - self._quit_armed < 1.5:
            self.exit()
        else:
            self._quit_armed = now
            self.query_one("#footer", Static).update(Text("Press Ctrl-C again to exit", style=DIM))

    def on_resize(self) -> None:
        self._update_footer()
        self.call_after_refresh(self._sync_ime_cursor)
