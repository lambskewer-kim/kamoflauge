"""macOS 카카오톡을 손쉬운 사용(Accessibility) API로 읽고 쓰는 어댑터.

전제:
  - 터미널 앱(Terminal/iTerm/Ghostty 등)에 '손쉬운 사용' 권한이 있어야 한다.
  - 읽고 싶은 채팅방은 카톡에서 창으로 열어둔다(더블클릭). 열린 채팅방 창 = 방 목록.

카톡 UI 구조는 버전마다 다를 수 있다. 안 맞으면 `kamoflauge dump`로
접근성 트리를 뽑아서 아래 휴리스틱을 조정한다.
"""
from __future__ import annotations

import os
import re
import threading
import time

from ApplicationServices import (  # type: ignore
    AXIsProcessTrustedWithOptions,
    AXUIElementCopyAttributeValue,
    AXUIElementCopyMultipleAttributeValues,
    AXUIElementCreateApplication,
    AXUIElementIsAttributeSettable,
    AXUIElementPerformAction,
    AXUIElementSetAttributeValue,
    AXValueGetValue,
    kAXTrustedCheckOptionPrompt,
    kAXValueCGPointType,
    kAXValueCGSizeType,
)
from AppKit import (  # type: ignore
    NSApplicationActivateIgnoringOtherApps,
    NSRunningApplication,
    NSWorkspace,
)
import Quartz  # type: ignore

from ...models import ChatEntry, Message, Room
from ...adapters.base import Adapter

BUNDLE_IDS = ("com.kakao.KakaoTalkMac", "com.kakao.KakaoTalk")
MAIN_TITLES = {"카카오톡", "KakaoTalk", ""}
KEY_RETURN = 36

TIME_RE = re.compile(r"^(오전|오후|AM|PM)?\s*\d{1,2}:\d{2}\s*(AM|PM)?$")
DATE_RE = re.compile(r"^\d{4}년\s*\d{1,2}월\s*\d{1,2}일|^\d{4}[./-]\d{1,2}[./-]\d{1,2}")
COUNT_RE = re.compile(r"^\d{1,3}$")
TEXT_ROLES = {"AXStaticText", "AXTextArea", "AXTextField", "AXLink"}
LIST_ROLES = {"AXTable", "AXList", "AXOutline", "AXCollection"}


class KakaoNotFound(RuntimeError):
    pass


# ---------- AX helpers ----------

def _attr(el, name):
    try:
        err, val = AXUIElementCopyAttributeValue(el, name, None)
    except Exception:
        return None
    return val if err == 0 else None


def _point(el):
    v = _attr(el, "AXPosition")
    if v is None:
        return None
    ok, p = AXValueGetValue(v, kAXValueCGPointType, None)
    return (p.x, p.y) if ok else None


def _size(el):
    v = _attr(el, "AXSize")
    if v is None:
        return None
    ok, s = AXValueGetValue(v, kAXValueCGSizeType, None)
    return (s.width, s.height) if ok else None


def _children(el):
    return list(_attr(el, "AXChildren") or [])


def _walk(el, depth=0, max_depth=30):
    yield el, depth
    if depth >= max_depth:
        return
    for c in _children(el):
        yield from _walk(c, depth + 1, max_depth)


ITEM_ATTRS = ["AXRole", "AXValue", "AXTitle", "AXDescription", "AXPosition", "AXSize"]


def _multi(el, names: list) -> list:
    """속성 여러 개를 AX 호출 한 번으로 읽는다. 없는 속성은 None."""
    try:
        err, vals = AXUIElementCopyMultipleAttributeValues(el, names, 0, None)
    except Exception:
        err, vals = -1, None
    if err != 0 or vals is None or len(vals) != len(names):
        return [_attr(el, n) for n in names]
    return list(vals)


def _xy(v, kind):
    """AXValue(point/size) → (a, b). 에러 값이나 None이면 None."""
    if v is None or isinstance(v, str):
        return None
    try:
        ok, p = AXValueGetValue(v, kind, None)
    except Exception:
        return None
    if not ok:
        return None
    return (p.x, p.y) if kind == kAXValueCGPointType else (p.width, p.height)


def _settable(el, name="AXValue") -> bool:
    try:
        err, ok = AXUIElementIsAttributeSettable(el, name, None)
        return err == 0 and bool(ok)
    except Exception:
        return False


def _text_of(el) -> str:
    for a in ("AXValue", "AXTitle", "AXDescription"):
        v = _attr(el, a)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def is_trusted(prompt: bool = False) -> bool:
    return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: prompt}))


# ---------- adapter ----------

class MacKakaoAdapter(Adapter):
    def __init__(self, send_mode: str = "auto", include_main: bool = False):
        """send_mode: 'background'(포커스 안 뺏음), 'activate'(잠깐 카톡 활성화), 'auto'(앞에 것 실패 시 뒤에 것)."""
        self.send_mode = send_mode
        self.include_main = include_main
        self._win_cache: dict = {}
        self._table_cache: dict = {}
        self._read_once: set = set()
        self._lock = threading.Lock()  # 읽기와 전송의 AX 호출이 뒤섞이지 않게
        if not is_trusted(prompt=True):
            raise PermissionError(
                "손쉬운 사용 권한이 없습니다. 시스템 설정 > 개인정보 보호 및 보안 > 손쉬운 사용 에서 "
                "지금 쓰는 터미널 앱을 켜고 터미널을 다시 실행하세요."
            )

    # --- app / windows ---
    def _app(self):
        for bid in BUNDLE_IDS:
            apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bid)
            if apps and len(apps):
                return apps[0]
        raise KakaoNotFound("카카오톡이 실행 중이 아닙니다.")

    def _ax_app(self):
        return AXUIElementCreateApplication(self._app().processIdentifier())

    def _windows(self):
        wins = []
        for w in _attr(self._ax_app(), "AXWindows") or []:
            title = _attr(w, "AXTitle") or ""
            if not self.include_main and (title in MAIN_TITLES or not is_chat_window(w)):
                continue
            wins.append((title, w))
        return wins

    def _window(self, room_id: str):
        w = self._win_cache.get(room_id)
        if w is not None and _attr(w, "AXRole"):  # 닫힌 창의 요소는 속성을 못 읽는다
            return w
        for title, w in self._windows():
            if title == room_id:
                self._win_cache[room_id] = w
                return w
        raise KeyError(f"채팅방 창을 찾을 수 없음: {room_id}")

    # --- public ---
    def rooms(self) -> list[Room]:
        seen, out, cache = set(), [], {}
        for title, w in self._windows():
            if title not in seen:
                seen.add(title)
                cache[title] = w
                out.append(Room(title, title))
        self._win_cache = cache
        self._table_cache = {k: v for k, v in self._table_cache.items() if k in cache}
        self._read_once &= set(cache)
        return out

    def messages(self, room_id: str) -> list[Message]:
        table = self._table_cache.get(room_id)
        if table is None or not _attr(table, "AXRole"):  # 창이 닫혔거나 다시 그려졌으면 다시 찾는다
            self._win_cache.pop(room_id, None)
            table = _message_table(self._window(room_id))
            if table is None:
                return []
            self._table_cache[room_id] = table
        rows = POLL_ROWS if room_id in self._read_once else FULL_ROWS
        with self._lock:
            msgs = parse_table(table, rows)
        if msgs:
            self._read_once.add(room_id)
        return msgs

    def send(self, room_id: str, text: str) -> None:
        t0 = time.perf_counter()
        with self._lock:
            waited = time.perf_counter() - t0
            try:
                how = self._send_locked(room_id, text)
            except Exception as ex:
                _send_log(f"fail: {type(ex).__name__}: {_safe_reason(ex)} (waited {waited:.1f}s)")
                raise
        _send_log(f"ok: {how} (waited {waited:.1f}s, total {time.perf_counter() - t0:.1f}s)")

    def _send_locked(self, room_id: str, text: str) -> str:
        win = self._window(room_id)
        inp = find_input(win)
        if inp is None:
            raise RuntimeError("입력창을 찾지 못했습니다 (kamoflauge dump 로 구조 확인 필요)")
        # 카톡은 자기 창 중 맨 앞(main) 창의 입력만 제대로 받는다. 방을 바꾸면 대상 창이 뒤에 있으므로
        # 카톡 안에서만 앞으로 올린다 (카톡 앱 자체를 활성화하지는 않음).
        _make_main(win, inp)
        for _ in range(3):
            AXUIElementSetAttributeValue(inp, "AXValue", text)
            if (_attr(inp, "AXValue") or "") == text:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("카톡 입력창에 글자를 넣지 못했습니다")

        def sent() -> bool:  # 입력창이 완전히 비었을 때만 전송된 것으로 본다
            return not (_attr(inp, "AXValue") or "").strip()

        if self.send_mode in ("background", "auto"):
            btn = find_send_button(win)
            if btn is not None:
                AXUIElementPerformAction(btn, "AXPress")
                time.sleep(0.3)
                if sent():
                    return "send button"
            AXUIElementSetAttributeValue(inp, "AXValue", text)  # Return이 줄바꿈으로 들어갔을 수 있으니 다시 맞춘다
            AXUIElementSetAttributeValue(inp, "AXFocused", True)
            self._post_return_to_pid()
            time.sleep(0.35)
            if sent():
                return "return to pid"
            if self.send_mode == "background":
                raise RuntimeError("백그라운드 전송 실패 (send_mode=activate 로 시도해보세요)")
        AXUIElementSetAttributeValue(inp, "AXValue", text)
        self._send_by_activating(win, inp)
        time.sleep(0.3)
        if sent():
            return "activate"
        raise RuntimeError("전송 실패: 카톡 입력창에 글자가 남아 있습니다")

    # --- 채팅 목록 / 방 열고 닫기 ---
    def _main_window(self):
        for w in _attr(self._ax_app(), "AXWindows") or []:
            if (_attr(w, "AXTitle") or "") in MAIN_TITLES and _chat_list_table(w) is not None:
                return w
        raise RuntimeError("카톡 메인 창(채팅 목록)을 찾지 못했습니다. 카톡 메인 창을 열어두세요")

    def chat_list(self, limit: int = 20) -> list[ChatEntry]:
        with self._lock:
            table = _chat_list_table(self._main_window())
            rows = list(_attr(table, "AXRows") or [])[:limit]
            out = [parse_chat_row(_cell_items(r)) for r in rows]
        return [e for e in out if e is not None]

    def open_room(self, name: str) -> None:
        if name in {r.id for r in self.rooms()}:
            return
        with self._lock:
            main = self._main_window()
            table = _chat_list_table(main)
            row = next((r for r in list(_attr(table, "AXRows") or [])[:OPEN_SEARCH_ROWS]
                        if (e := parse_chat_row(_cell_items(r))) and e.name == name), None)
            if row is None:
                raise RuntimeError(f"채팅 목록 위쪽 {OPEN_SEARCH_ROWS}개 안에서 방을 찾지 못했습니다")
            # 목록에서 행을 선택하고 Enter → 카톡이 그 방을 새 창으로 연다
            _make_main(main, table)
            AXUIElementSetAttributeValue(row, "AXSelected", True)
            self._post_return_to_pid()
        if self._wait_window(name):
            return
        with self._lock:  # 백그라운드 Enter가 안 먹으면 카톡을 잠깐 앞으로 꺼내서 Enter
            self._send_by_activating(main, table)
        if not self._wait_window(name):
            raise RuntimeError("방을 열지 못했습니다")

    def _wait_window(self, name: str, timeout: float = 2.5) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if any((_attr(w, "AXTitle") or "") == name for w in _attr(self._ax_app(), "AXWindows") or []):
                return True
            time.sleep(0.15)
        return False

    def close_room(self, room_id: str) -> None:
        with self._lock:
            win = self._window(room_id)
            btn = next((c for role, c in _top_children(win)
                        if role == "AXButton" and _attr(c, "AXSubrole") == "AXCloseButton"), None)
            if btn is None:
                raise RuntimeError("닫기 버튼을 찾지 못했습니다")
            AXUIElementPerformAction(btn, "AXPress")
            self._win_cache.pop(room_id, None)
            self._table_cache.pop(room_id, None)
            self._read_once.discard(room_id)

    def has_input(self, room_id: str) -> bool:
        return find_input(self._window(room_id)) is not None

    # --- sending internals ---
    def _post_return_to_pid(self):
        pid = self._app().processIdentifier()
        post = getattr(Quartz, "CGEventPostToPid", None)
        if post is None:
            return
        for down in (True, False):
            ev = Quartz.CGEventCreateKeyboardEvent(None, KEY_RETURN, down)
            post(pid, ev)

    def _send_by_activating(self, win, inp):
        app = self._app()
        was_hidden = bool(app.isHidden())
        prev = NSWorkspace.sharedWorkspace().frontmostApplication()
        app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        _make_main(win, inp)
        time.sleep(0.15)
        for down in (True, False):
            ev = Quartz.CGEventCreateKeyboardEvent(None, KEY_RETURN, down)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        time.sleep(0.12)
        if prev is not None:
            prev.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        if was_hidden:
            app.hide()


# ---------- parsing (UI 휴리스틱) ----------
#
# 실제 카톡 맥 구조 (v2026 기준):
#   AXWindow (title = 방 이름)
#     AXScrollArea > AXTable > AXRow > AXCell > [Profile 버튼, 이름(StaticText),
#                                                 시간/안읽음 수(StaticText), 말풍선(AXImage), 본문(AXTextArea)]
#     AXScrollArea > AXTextArea 'Enter a message' (settable)  ← 입력창
#     AXButton 'Send'                                          ← 전송 버튼

SEND_TITLES = {"Send", "전송"}
SHARE_TITLES = {"Share", "공유"}
PHOTO_MIN = 80  # 말풍선 배경도 AXImage라서, 이보다 작은 이미지만 있는 행은 사진으로 보지 않는다
FULL_ROWS = 50  # 방을 처음 읽을 때 행 수
OPEN_SEARCH_ROWS = 200  # /open-chatroom 때 채팅 목록에서 찾아볼 행 수
POLL_ROWS = 15  # 그다음부터 폴링할 때 읽는 행 수 (새 메시지는 아래에 붙으므로 끝부분만 보면 된다)
ME_LEFT_MARGIN = 73  # 셀 왼쪽에서 본문까지 거리가 이보다 크면 내 메시지(오른쪽 정렬)


def _make_main(win, inp) -> None:
    AXUIElementSetAttributeValue(win, "AXMain", True)
    AXUIElementPerformAction(win, "AXRaise")
    AXUIElementSetAttributeValue(inp, "AXFocused", True)
    time.sleep(0.05)


SEND_LOG = os.path.expanduser("~/.kamoflauge/send.log")


def _safe_reason(ex: Exception) -> str:
    """로그용 실패 사유. KeyError에는 방 이름이 들어 있으므로 빼고 남긴다."""
    return "chat window not found" if isinstance(ex, KeyError) else str(ex)


def _send_log(result: str) -> None:
    """어느 전송 방법이 통했는지 남긴다 (메시지 내용과 방 이름은 남기지 않음)."""
    try:
        with open(SEND_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {result}\n")
    except OSError:
        pass


def _chat_list_table(main):
    """메인 창의 채팅 목록 표 (AXScrollArea > AXTable)."""
    for role, c in _top_children(main):
        if role == "AXScrollArea":
            for cc in _children(c):
                if _attr(cc, "AXRole") == "AXTable":
                    return cc
    return None


BADGE_RE = re.compile(r"^\d{1,3}\+?$")


def parse_chat_row(items) -> ChatEntry | None:
    """채팅 목록 한 행 → ChatEntry. 순서: [Profile] 이름 [멤버 수] 시간 [마지막 메시지] [안 읽은 수].
    멤버 수는 시간 앞에, 안 읽은 수는 시간 뒤에 온다."""
    name, unread, seen_time = "", 0, False
    for role, text, _, _ in items:
        if role != "AXStaticText" or not text:
            continue
        t = text.replace("\u202f", " ").strip()
        if TIME_RE.match(t) or DATE_RE.match(t) or t in ("Yesterday", "어제"):
            seen_time = True
        elif BADGE_RE.match(t) or t.isdigit():
            if seen_time:
                unread = int(t.rstrip("+"))
        elif not name:
            name = t
    return ChatEntry(name, unread) if name else None


def _top_children(win):
    return [(_attr(c, "AXRole") or "", c) for c in _children(win)]


def is_chat_window(win) -> bool:
    for role, c in _top_children(win):
        if role == "AXButton" and _text_of(c) in SEND_TITLES:
            return True
        if role == "AXScrollArea":
            for cc in _children(c):
                if _attr(cc, "AXRole") == "AXTextArea" and _settable(cc):
                    return True
    return False


def find_input(win):
    for role, c in _top_children(win):
        if role == "AXScrollArea":
            for cc in _children(c):
                if _attr(cc, "AXRole") == "AXTextArea" and _settable(cc):
                    return cc
    # 폴백: 전체 탐색
    best, best_y = None, -1.0
    for el, _ in _walk(win, max_depth=6):
        if _attr(el, "AXRole") in ("AXTextArea", "AXTextField") and _settable(el):
            p = _point(el)
            y = p[1] if p else 0
            if y >= best_y:
                best, best_y = el, y
    return best


def find_send_button(win):
    for role, c in _top_children(win):
        if role == "AXButton" and _text_of(c) in SEND_TITLES:
            return c
    return None


def _message_table(win):
    for role, c in _top_children(win):
        if role == "AXScrollArea":
            for cc in _children(c):
                if _attr(cc, "AXRole") in LIST_ROLES:
                    return cc
    best, best_n = None, 0
    for el, _ in _walk(win, max_depth=6):
        if _attr(el, "AXRole") in LIST_ROLES:
            n = len(_attr(el, "AXRows") or _children(el))
            if n > best_n:
                best, best_n = el, n
    return best


def _cell_items(row):
    """행 하나 → [(role, text, x, width)]. 요소마다 AX 호출 한 번(_multi)으로 읽는다."""
    items = []
    for cell in _children(row):
        for k in _children(cell):
            role, value, title, desc, pos, size = _multi(k, ITEM_ATTRS)
            if role not in ("AXStaticText", "AXTextArea", "AXButton", "AXImage"):
                continue
            text = next((t.strip() for t in (value, title, desc) if isinstance(t, str) and t.strip()), "")
            p, sz = _xy(pos, kAXValueCGPointType), _xy(size, kAXValueCGSizeType)
            if role == "AXImage":  # 이미지는 width 자리에 짧은 변 길이를 넣는다 (사진 판정용)
                items.append((role, text, p[0] if p else 0, min(sz) if sz else 0))
                continue
            items.append((role, text, p[0] if p else 0, sz[0] if sz else 0))
    return items


def _photo_x(items) -> float | None:
    """사진 행이면 사진의 x 좌표, 아니면 None. Share 버튼이 있거나 큰 이미지가 있어야 사진이다."""
    big = [x for r, _, x, side in items if r == "AXImage" and side >= PHOTO_MIN]
    share = any(r == "AXButton" and t in SHARE_TITLES for r, t, _, _ in items)
    if not big and not share:
        return None
    return big[0] if big else 0


def parse_rows(rows: list, cell_left: float) -> list[Message]:
    """rows: [[(role, text, x, width), ...], ...]  — AX와 분리된 순수 함수(테스트용)."""
    msgs: list[Message] = []
    last_sender = ""
    for items in rows:
        has_profile = any(r == "AXButton" and t == "Profile" for r, t, _, _ in items)
        bodies = [(t, x) for r, t, x, _ in items if r == "AXTextArea" and t]
        time_s, name = "", ""
        for r, t, x, _ in items:
            if r != "AXStaticText" or not t:
                continue
            parts = [q.strip() for q in t.split("\n") if q.strip()]
            leftover = []
            for q in parts:
                if TIME_RE.match(q):
                    time_s = q.replace("\u202f", " ")
                elif COUNT_RE.match(q) or DATE_RE.match(q):
                    pass
                else:
                    leftover.append(q)
            if leftover and has_profile and not name:
                name = " ".join(leftover)
        if not bodies:
            photo = _photo_x(items)
            if photo is None:
                continue  # 날짜 구분선, 또는 글자가 아직 안 채워진 말풍선 → 다음 폴링 때 다시 읽는다
            bodies = [("사진", photo)]
        text = "\n".join(t for t, _ in bodies)
        x = bodies[0][1]
        is_me = (not has_profile) and x > 0 and (x - cell_left) > ME_LEFT_MARGIN
        if is_me:
            msgs.append(Message("", text, time_s, True))
            continue
        if name:
            last_sender = name
        msgs.append(Message(last_sender, text, time_s, False))
    return msgs


def _has_profile(items) -> bool:
    return any(r == "AXButton" and t == "Profile" for r, t, _, _ in items)


def parse_table(table, min_rows: int = FULL_ROWS, last_n: int = 40) -> list[Message]:
    """마지막 min_rows 행을 읽는다. 맨 앞 행이 연속 메시지(이름 없음)면 보낸 사람을 알 수 있도록
    Profile이 있는 행이 나올 때까지 한 행씩 더 읽는다 (최대 FULL_ROWS)."""
    rows = list(_attr(table, "AXRows") or [c for c in _children(table) if _attr(c, "AXRole") == "AXRow"])
    p = _point(table)
    cell_left = p[0] + 1 if p else 0
    start = max(0, len(rows) - min_rows)
    parsed_rows = [_cell_items(r) for r in rows[start:]]
    limit = max(0, len(rows) - FULL_ROWS)
    while start > limit and parsed_rows and not _has_profile(parsed_rows[0]):
        start -= 1
        parsed_rows.insert(0, _cell_items(rows[start]))
    return parse_rows(parsed_rows, cell_left)[-last_n:]


def parse_window(win, last_n: int = 40) -> list[Message]:
    table = _message_table(win)
    return [] if table is None else parse_table(table, last_n=last_n)


# ---------- 진단 도구 ----------

def dump_tree(path: str, max_depth: int = 25, max_nodes: int = 3000, max_kids: int = 40,
              redact: bool = True) -> int:
    """채팅방 창 하나의 접근성 트리를 빠르게 덤프. redact=True면 한글을 ㅁ으로 가린다."""
    ad = MacKakaoAdapter.__new__(MacKakaoAdapter)
    ad.include_main = False
    wins = ad._windows()
    if not wins:
        raise RuntimeError("열린 채팅방 창이 없습니다. 카톡에서 채팅방을 더블클릭해 열어두세요.")
    out: list[str] = []

    def walk(el, d):
        if len(out) >= max_nodes or d > max_depth:
            return
        role = _attr(el, "AXRole") or "?"
        sub = _attr(el, "AXSubrole") or ""
        txt = _text_of(el).replace("\n", "\\n")[:60]
        flag = " [settable]" if role in ("AXTextArea", "AXTextField") and _settable(el) else ""
        out.append(f"{'  ' * d}{role}{'/' + sub if sub else ''} {txt!r} pos={_point(el)} size={_size(el)}{flag}")
        kids = _children(el)
        if len(kids) > max_kids:
            out.append(f"{'  ' * (d + 1)}... ({len(kids)} children, first/last {max_kids // 2} only)")
            kids = kids[: max_kids // 2] + kids[-max_kids // 2:]
        for c in kids:
            walk(c, d + 1)

    walk(wins[0][1], 0)
    text = "\n".join(out)
    if redact:
        text = re.sub(r"[가-힣]", "ㅁ", text)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return len(out)
