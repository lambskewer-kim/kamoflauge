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
from .models import ChatEntry, Message, Room
from .palette import Item, Palette, find_command, match_commands
from .platforms import shift_watcher, theme
from .speed import SPEEDS, find_speed, get_speed, next_speed
from .sync import new_messages

ORANGE = "#d77757"
DIM = "#8a8a8a"
GREEN = "#4eba65"
REVEAL = "#e5c07b"
REVEAL_HOLD = 0.3  # Shift를 이만큼(초) 계속 누르고 있어야 실명을 보여준다 (한글 쌍자음 입력과 구분)
_THEME = theme()
BULLET, SPIN, STAR = _THEME.BULLET, _THEME.SPIN, _THEME.STAR
BG_EVERY = 4  # 방 목록/다른 방은 폴링 4번에 한 번
LIST_EVERY = 8  # 카톡 채팅 목록(안 연 방의 안 읽은 수)은 폴링 8번에 한 번


def pick_opened(rooms: list[Room], before: set[str], name: str) -> Room | None:
    """방을 연 뒤 새로 생긴 방 찾기. 이름이 정확히 같은 방 → 새로 생긴 방 하나 → 이름이 들어간 방 순."""
    exact = next((r for r in rooms if r.id == name), None)
    if exact:
        return exact
    new = [r for r in rooms if r.id not in before]
    if len(new) == 1:
        return new[0]
    return next((r for r in new if name in r.name), None)


@dataclass
class Entry:
    lines: list[tuple[str, str]]  # (style, text)
    real: bool                    # True면 카톡 내용 → 보스 모드에서 숨김
    fake: bool = False            # True면 가짜 Claude 작업 로그 → Shift로 실명 볼 때 숨김
    room: str | None = None       # 추가될 때 보고 있던 방. 다른 방으로 바꾸면 안 보인다 (None = 항상 보임)


@dataclass
class Config:
    aliases: dict = field(default_factory=dict)
    cwd: str = "~/research/vision-transformer"
    poll: float = 0.7
    filler: bool = True           # 평소에도 가끔 가짜 작업 로그 섞기
    speed: str = "normal"         # 가짜 로그 빈도: fast | normal | slow (빠르게/보통/느리게)
    filler_every: tuple | None = None  # 지정하면 speed 대신 이 간격(초)을 쓴다 (테스트용)
    history: int = 15
    strip_emoji: bool = True
    show_time: bool = False
    show_media: bool = True       # False면 사진/이모티콘/동영상 줄([Image #N] 등)을 숨긴다
    notify: bool = True           # 다른 방 백그라운드 알림 줄을 보여줄지 (/notify로 켜고 끔)


class Kamoflauge(App):
    CSS_PATH = "app.tcss"
    TITLE = "claude"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("ctrl+b", "boss", "boss", show=False, priority=True),
        Binding("shift+tab", "toggle_claude", "mode", show=False, priority=True),
        Binding("ctrl+t", "toggle_claude", "mode", show=False, priority=True),  # 터미널이 shift+tab을 가로챌 때
        Binding("escape", "boss_toggle", "panic", show=False, priority=True),
        Binding("ctrl+n", "next_room", "next", show=False, priority=True),
        Binding("ctrl+p", "prev_room", "prev", show=False, priority=True),
        Binding("ctrl+c", "quit_twice", "quit", show=False, priority=True),
        Binding("up", "palette_move(-1)", show=False, priority=True),
        Binding("down", "palette_move(1)", show=False, priority=True),
        Binding("tab", "palette_complete", show=False, priority=True),
    ]

    def __init__(self, adapter: Adapter, cfg: Config | None = None):
        super().__init__()
        self.adapter = adapter
        self.cfg = cfg or Config()
        self.dis = Disguise(self.cfg.aliases, self.cfg.strip_emoji)
        self.entries: list[Entry] = []
        self.boss = False
        self.reveal = False               # Shift를 누르고 있는 동안 실명 표시
        self._shift = shift_watcher()
        self._shift_since = 0.0
        self._last_typed = 0.0
        self.claude_on = self.cfg.filler  # True: 가짜 작업 로그를 섞음, False: 채팅만
        self.speed = get_speed(self.cfg.speed)
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
        self._next_filler = time.time() + random.uniform(*self._filler_range())
        self._polling = False
        self._poll_n = 0
        self._last_poll_end = 0.0
        self._sending = 0
        self.muted: set[str] = set()                 # 알림을 끈 방 (실명)
        self.notify_on = self.cfg.notify            # 백그라운드 알림 전체 켜기 / 끄기
        self.chat_list: list[ChatEntry] = []         # 카톡 채팅 목록 (안 연 방 포함)
        self._list_unread: dict[str, int] | None = None  # 채팅 목록의 안 읽은 수 (None = 아직 기준값 없음)
        self._list_supported = True

    # ---------- layout ----------
    def compose(self) -> ComposeResult:
        yield RichLog(id="log", wrap=True, markup=False, auto_scroll=True)
        yield Static(id="spinner")
        with Horizontal(id="prompt-box"):
            yield Label(">")
            yield Input(id="prompt", placeholder='Try "fix lint errors"')
        yield Palette(id="palette")
        yield Static(id="footer")

    async def on_mount(self) -> None:
        self.query_one("#prompt", Input).focus()
        self.call_after_refresh(self._sync_ime_cursor)
        self._welcome()
        self.set_interval(0.12, self._tick_spinner)
        self.set_interval(0.2, self._poll)
        await self._refresh_rooms()
        if self.rooms:
            await self._open(self.rooms[0])
        else:
            self._sys("No open chat windows found. Open a chat window in KakaoTalk, then /rooms")
        self._update_footer()

    # ---------- rendering ----------
    def _welcome(self) -> None:
        body = Group(
            Text.assemble((f"{STAR} ", ORANGE), ("Welcome to ", "bold"), ("Claude Code", "bold"), ("!", "bold")),
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
            return Text.assemble((f"{BULLET} ", "#4eba65"), (name, "bold"), (("(" + arg) if arg else "", ""))
        if style == "msg":
            head, _, real = text.partition("\0")
            t = Text.assemble((f"{BULLET} ", "#4eba65"), ("Read", "bold"), (f"({head})", ""))
            if self.reveal and real:
                t.append(f"  ← {real}", style=f"bold {REVEAL}")
            return t
        if style == "notify":
            head, real, n = text.split("\0")
            t = Text.assemble((f"{BULLET} ", DIM), ("Background task", "bold"), (f" ({head})", ""),
                              (f" · {n} new line{'s' if n != '1' else ''}", DIM))
            if self.reveal and real:
                t.append(f"  ← {real}", style=f"bold {REVEAL}")
            return t
        if style == "tool_dim":
            name, _, arg = text.partition("(")
            return Text.assemble((f"{BULLET} ", DIM), (name, "bold"), (("(" + arg) if arg else "", ""))
        if style == "result":
            return Text.assemble(("  ⎿  ", DIM), (text, ""))
        if style == "result_dim":
            return Text.assemble(("  ⎿  ", DIM), (text, DIM))
        if style == "cont":
            return Text.assemble(("     ", ""), (text, ""))
        if style == "user":
            return Text.assemble(("> ", DIM), (text, DIM))
        if style == "prose":
            return Text.assemble((f"{BULLET} ", "#ffffff"), (text, ""))
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
        if e.room is not None and not (self.current and e.room == self.current.id):
            return False  # 다른 방에서 쌓인 줄은 섞지 않는다
        if e.real and self.boss:
            return False
        return not (e.fake and self.reveal)

    def _add(self, lines: list[tuple[str, str]], real: bool, fake: bool = False) -> None:
        if not lines:
            return
        while lines and lines[-1][0] == "blank":
            lines = lines[:-1]
        if lines and lines[0][0] != "cont":
            lines = [("blank", "")] + lines
        e = Entry(lines, real, fake, self.current.id if self.current else None)
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
        if not self.cfg.show_media and self.dis.is_media(m.text):
            return []  # 글자 없는 메시지는 숨긴다 (헷갈리지 않게)
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

    def on_input_changed(self, ev: Input.Changed) -> None:
        self._last_typed = time.time()
        self._update_palette(ev.value)

    # ---------- slash palette ----------
    def _update_palette(self, value: str) -> None:
        pal = self.query_one("#palette", Palette)
        if self.boss or not value.startswith("/"):
            pal.hide()
        elif " " not in value:
            pal.show([Item(f"/{c.name}" + (f" {c.args}" if c.args else ""), c.desc, c.name, "command")
                      for c in match_commands(value[1:])])
        else:
            cmd = find_command(value[1:].split(" ", 1)[0])
            query = value.split(" ", 1)[1].strip()
            if cmd and cmd.name == "open-chatroom" and not self.chat_list and self._list_supported:
                self.run_worker(self._load_chat_list(), exclusive=True, group="chatlist")
            pal.show(self._room_items(cmd.name, query) if cmd else [])
        self._set_palette_layout(pal.visible)

    def _set_palette_layout(self, palette_open: bool) -> None:
        """메뉴가 열리면 푸터를 숨기고, 로그 높이가 바뀌어도 최신 줄이 보이게 맨 아래로 내린다."""
        footer = self.query_one("#footer")
        if footer.display == (not palette_open):
            return
        footer.display = not palette_open
        log = self.query_one("#log", RichLog)
        self.call_after_refresh(lambda: log.scroll_end(animate=False))

    def _room_items(self, cmd: str, query: str) -> list[Item]:
        """/open-chatroom, /switch 뒤에 붙는 방 목록.
        /open-chatroom은 가명만 봐서는 어떤 방인지 모르니 오른쪽에 실명을 같이 보여준다(메뉴가 열려 있을 때만)."""
        if cmd == "speed":
            return [Item(f"/speed {sp.label}", "current" if sp == self.speed else "", sp.label, "room")
                    for sp in SPEEDS if not query or query in sp.label or query in sp.key]
        if cmd == "open-chatroom" and not self._list_supported:
            # 채팅 목록을 못 읽는 플랫폼(윈도우): 친 이름 그대로 연다
            if not query:
                return [Item("방 이름을 입력하세요", "예: /open-chatroom 점심팟", "", "hint")]
            return [Item(query, "Enter로 열기", query, "room")]
        if cmd == "open-chatroom":
            open_ids = {r.id for r in self.rooms}
            rooms = [(e.name, e.name + (f"  ({e.unread} new)" if e.unread else ""))
                     for e in self.chat_list if e.name not in open_ids]
        elif cmd == "switch":
            rooms = [(r.name, "current" if self.current and r.id == self.current.id else "") for r in self.rooms]
        else:
            return []
        q = query.lower()
        items = []
        for name, note in rooms:
            alias = f"{self.dis.room_dir(name)}/"
            if q and q not in alias.lower() and q not in name.lower():
                continue
            label = f"{alias}  ← {name}" if self.reveal and cmd == "switch" else alias
            items.append(Item(label, note, name, "room"))
        return items

    def action_palette_move(self, step: int) -> None:
        self.query_one("#palette", Palette).move(step)

    def action_palette_complete(self) -> None:
        """Tab: 고른 명령어나 방 이름으로 입력창을 채운다."""
        item = self.query_one("#palette", Palette).selected
        if item:
            self._complete(item)

    def _complete(self, item: Item) -> None:
        prompt = self.query_one("#prompt", Input)
        if item.kind == "command":
            c = find_command(item.value)
            prompt.value = f"/{item.value}" + (" " if c and c.args else "")
            if c and c.name == "open-chatroom" and self._list_supported:
                self.run_worker(self._load_chat_list(), exclusive=True, group="chatlist")
        else:
            prompt.value = f"{prompt.value.split(' ', 1)[0]} {item.value}"
        prompt.cursor_position = len(prompt.value)

    async def _load_chat_list(self) -> None:
        try:
            self.chat_list = await asyncio.to_thread(self.adapter.chat_list, 30)
        except NotImplementedError:
            self._list_supported = False  # 목록 없이 이름을 직접 쳐서 연다
        except Exception as ex:  # noqa: BLE001
            self._sys(f"Error: {ex}")
            return
        self._update_palette(self.query_one("#prompt", Input).value)

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
                lo, hi = self._filler_range()
                if self.boss:
                    lo, hi = lo / 3, hi / 3
                self._next_filler = time.time() + random.uniform(lo, hi)
                self._add_fake()

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
        """방을 연다. 화면에는 이 방의 줄만 보이고, 이 방의 예전 줄은 지우고 최근 대화를 새로 불러온다
        (자리를 비운 사이 온 메시지가 빠지거나 같은 메시지가 두 번 나오지 않게)."""
        self.current = room
        self.unread[room.id] = 0
        self.last_sender = None
        self.entries = [e for e in self.entries if e.room != room.id]
        self._rebuild()
        try:
            msgs = await asyncio.to_thread(self.adapter.messages, room.id)
        except Exception as ex:  # noqa: BLE001
            self._sys(f"Error: {ex}")
            return
        if self.current is not room:
            return  # 읽는 사이 다른 방으로 바뀜
        self.snapshots[room.id] = msgs
        self._add([("tool_dim", f"Bash(cd {self.dis.room_dir(room.name)} && git log --oneline -{self.cfg.history})"),
                   ("result_dim", f"{len(msgs[-self.cfg.history:])} commits")], real=True)
        mix = self.claude_on and not self.boss
        for m in msgs[-self.cfg.history:]:
            self._add(self._render_msg(room, m), real=True)
            if mix and random.random() < self.speed.history_mix:  # 처음 불러올 때도 가짜 작업 로그를 섞는다
                self._add_fake()
        self._update_footer()

    def _filler_range(self) -> tuple:
        return self.cfg.filler_every or self.speed.every

    def _add_fake(self) -> None:
        self._add(fake_event(), real=False, fake=True)
        self.last_sender = None

    async def _poll(self) -> None:
        """현재 방은 매번, 방 목록과 다른 방은 BG_EVERY번에 한 번 읽는다 (AX 호출이 느려서)."""
        # 카톡은 접근성 요청을 느리게 처리한다. 읽기가 끝난 뒤 poll초는 쉬게 해서 카톡(과 전송)이 숨 쉴 틈을 준다
        if self._polling or self._sending or time.time() - self._last_poll_end < self.cfg.poll:
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
            if self._list_supported and self._poll_n % LIST_EVERY == 1:
                await self._poll_chat_list()
        except Exception as ex:  # noqa: BLE001
            self.log.warning(f"poll error: {ex}")
        finally:
            self._polling = False
            self._last_poll_end = time.time()
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
        incoming = 0
        for m in new_messages(prev, cur):
            if m.is_me and (r.id, m.text) in self.pending_echo:
                self.pending_echo.remove((r.id, m.text))
                continue
            if self.current and r.id == self.current.id:
                self._add(self._render_msg(r, m), real=True)
            elif not m.is_me:
                incoming += 1
        if incoming:
            self.unread[r.id] = self.unread.get(r.id, 0) + incoming
            self._notify(r.name, incoming)

    def _notify(self, name: str, n: int) -> None:
        """다른 방에 새 메시지: 내용 없이 방(가명)과 개수만 Claude Code 백그라운드 작업 알림처럼 보여준다."""
        if not self.notify_on or name in self.muted:
            return
        self._add([("notify", f"{self.dis.room_dir(name)}/\0{name}\0{n}")], real=True)
        self.last_sender = None

    async def _poll_chat_list(self) -> None:
        """창으로 안 연 방은 카톡 채팅 목록의 안 읽은 수가 늘어난 만큼 알린다."""
        try:
            entries = await asyncio.to_thread(self.adapter.chat_list, 30)
        except NotImplementedError:
            self._list_supported = False
            return
        self.chat_list = entries
        open_ids = {r.id for r in self.rooms}
        now = {e.name: e.unread for e in entries if e.name not in open_ids}
        if self._list_unread is not None:  # 처음 한 번은 기준값만 잡는다
            for name, unread in now.items():
                delta = unread - self._list_unread.get(name, 0)
                if delta > 0:
                    self.unread[name] = self.unread.get(name, 0) + delta
                    self._notify(name, delta)
        self._list_unread = now

    # ---------- input ----------
    async def on_input_submitted(self, ev: Input.Submitted) -> None:
        pal = self.query_one("#palette", Palette)
        item = pal.selected
        if item and item.kind == "command":
            c = find_command(item.value)
            typed = ev.value.strip()[1:].split(" ", 1)
            if c and c.needs_arg and len(typed) == 1:
                self._complete(item)  # 인자가 필요한 명령은 Enter로 먼저 완성하고 방 목록을 띄운다
                return
            if c and len(typed) == 1:
                ev.input.value = f"/{c.name}"
        elif item and item.kind == "room":
            self._complete(item)
        text = self.query_one("#prompt", Input).value.strip()
        ev.input.value = ""
        pal.hide()
        self._set_palette_layout(False)
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
        self._sending += 1
        try:
            await asyncio.to_thread(self.adapter.send, room.id, text)
        except Exception as ex:  # noqa: BLE001
            self.pending_echo.remove((room.id, text))
            self._add([("result_dim", f"Error: {ex}")], real=True)
        finally:
            self._sending -= 1

    async def _command(self, line: str) -> None:
        name, _, arg = line[1:].partition(" ")
        arg = arg.strip()
        c = find_command(name)
        cmd = c.name if c else name
        if cmd == "open-chatroom":
            await self._cmd_open_chatroom(arg)
        elif cmd == "close-chatroom":
            await self._cmd_close_chatroom()
        elif cmd == "mute":
            if self.current:
                name = self.current.name
                self.muted ^= {name}
                self._sys(f"{'Muted' if name in self.muted else 'Unmuted'} background task {self.dis.room_dir(name)}/")
        elif cmd == "notify":
            self.notify_on = not self.notify_on
            self._sys(f"Background task notifications {'on' if self.notify_on else 'off'}")
        elif cmd == "rooms":
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
        elif cmd == "switch":
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
        elif cmd == "who":
            # 지금 방의 실제 이름을 잠깐 확인 (2초 뒤 사라지지 않음 주의)
            if self.current:
                self._sys(f"{self.dis.alias(self.current.name)} ↔ {self.current.name}")
        elif cmd == "auto":
            self.action_toggle_claude()
        elif cmd == "speed":
            self._cmd_speed(arg)
        elif cmd == "panic":
            self.action_boss()
        elif cmd == "clear":
            cur = self.current.id if self.current else None
            self.entries = [e for e in self.entries if e.room not in (None, cur)]  # 지금 방 화면만 지운다
            self._rebuild()
        elif cmd == "quit":
            self.exit()
        elif cmd == "help":
            self._add(self._help_lines(), real=True)  # 한국어라 패닉 모드에서는 숨긴다
        elif cmd == "status":
            self._add([("prose", "Model: claude-opus · API usage billing")], real=False)
        else:
            self._sys(f"Unknown slash command: /{cmd}")

    def _help_lines(self) -> list[tuple[str, str]]:
        from rich.cells import cell_len

        from .palette import COMMANDS

        def row(key: str, desc: str) -> tuple[str, str]:
            return ("cont", key + " " * max(2, 28 - cell_len(key)) + desc)

        lines = [("prose", "kamoflauge 도움말"), ("blank", "")]
        lines += [row(f"/{c.name} {c.args}".strip(), c.desc) for c in COMMANDS]
        lines += [("blank", ""),
                  row("esc", "패닉 모드 켜기 / 끄기 (카톡 내용 숨기기)"),
                  row("shift+tab / ctrl+t", "auto-claude 켜기 / 끄기"),
                  row("shift 꾹 누르기", "누르는 동안 실명 보기"),
                  row("ctrl+n / ctrl+p", "다음 / 이전 방"),
                  row("ctrl+c 두 번", "종료")]
        return lines

    def _cmd_speed(self, arg: str) -> None:
        sp = find_speed(arg) if arg else next_speed(self.speed)
        if not sp:
            self._sys("Usage: /speed 빠르게 | 보통 | 느리게")
            return
        self.speed = sp
        self._next_filler = time.time() + random.uniform(*self._filler_range()) / 2
        self._sys(f"Fake log speed: {sp.label}")

    async def _cmd_open_chatroom(self, name: str) -> None:
        if not name:  # 이름 없이 실행하면 방 목록 메뉴를 띄운다 (로그에 실명을 남기지 않게)
            prompt = self.query_one("#prompt", Input)
            prompt.value = "/open-chatroom "
            prompt.cursor_position = len(prompt.value)
            if self._list_supported:
                await self._load_chat_list()
            return
        before = {r.id for r in self.rooms}
        self._add([("tool_dim", f"Bash(git worktree add ../{self.dis.room_dir(name)})")], real=True)
        try:
            await asyncio.to_thread(self.adapter.open_room, name)
        except NotImplementedError:
            self._sys("Opening chatrooms is not supported on this platform")
            return
        except Exception as ex:  # noqa: BLE001
            self._add([("result_dim", f"Error: {ex}")], real=True)
            return
        await self._refresh_rooms()
        room = pick_opened(self.rooms, before, name)
        if room:
            name = room.id
            self.unread.pop(name, None)
            if self._list_unread is not None:
                self._list_unread.pop(name, None)
            await self._open(room)
        else:
            self._sys("Opened, but the window was not found yet. Try /switch in a moment")

    async def _cmd_close_chatroom(self) -> None:
        if not self.current:
            self._sys("No file open")
            return
        room = self.current
        try:
            await asyncio.to_thread(self.adapter.close_room, room.id)
        except NotImplementedError:
            self._sys("Closing chatrooms is not supported on this platform")
            return
        except Exception as ex:  # noqa: BLE001
            self._add([("result_dim", f"Error: {ex}")], real=True)
            return
        self._sys(f"Closed {self.dis.room_dir(room.name)}/")
        self.snapshots.pop(room.id, None)
        self.unread.pop(room.id, None)
        self.current = None
        await self._refresh_rooms()
        if self.rooms:
            await self._open(self.rooms[0])
        self._update_footer()

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

    def action_boss_toggle(self) -> None:
        """Esc: 패닉 모드 켜기 / 끄기. 켤 때는 열린 / 메뉴도 닫는다."""
        self.query_one("#palette", Palette).hide()
        self._set_palette_layout(False)
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
