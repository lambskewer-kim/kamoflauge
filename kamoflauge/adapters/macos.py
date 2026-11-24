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

from ..models import Message, Room
from .base import Adapter

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
        return out

    def messages(self, room_id: str) -> list[Message]:
        table = self._table_cache.get(room_id)
        if table is None or not _attr(table, "AXRole"):  # 창이 닫혔거나 다시 그려졌으면 다시 찾는다
            self._win_cache.pop(room_id, None)
            table = _message_table(self._window(room_id))
            if table is None:
                return []
            self._table_cache[room_id] = table
        return parse_table(table)

    def send(self, room_id: str, text: str) -> None:
        win = self._window(room_id)
        inp = find_input(win)
        if inp is None:
            raise RuntimeError("입력창을 찾지 못했습니다 (kamoflauge dump 로 구조 확인 필요)")
        # 카톡은 자기 창 중 맨 앞(main) 창의 입력만 제대로 받는다. 방을 바꾸면 대상 창이 뒤에 있으므로
        # 카톡 안에서만 앞으로 올린다 (카톡 앱 자체를 활성화하지는 않음).
        _make_main(win, inp)
        AXUIElementSetAttributeValue(inp, "AXValue", text)

        def sent() -> bool:
            return (_attr(inp, "AXValue") or "") != text

        if self.send_mode in ("background", "auto"):
            btn = find_send_button(win)
            if btn is not None:
                AXUIElementPerformAction(btn, "AXPress")
                time.sleep(0.3)
                if sent():
                    return _send_log("ok: send button")
            AXUIElementSetAttributeValue(inp, "AXFocused", True)
            self._post_return_to_pid()
            time.sleep(0.35)
            if sent():
                return _send_log("ok: return to pid")
            if self.send_mode == "background":
                _send_log("fail: background")
                raise RuntimeError("백그라운드 전송 실패 (send_mode=activate 로 시도해보세요)")
        self._send_by_activating(win, inp)
        time.sleep(0.3)
        if sent():
            return _send_log("ok: activate")
        _send_log("fail: all methods")
        raise RuntimeError("전송 실패: 카톡 입력창에 글자가 남아 있습니다")

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
ME_LEFT_MARGIN = 73  # 셀 왼쪽에서 본문까지 거리가 이보다 크면 내 메시지(오른쪽 정렬)


def _make_main(win, inp) -> None:
    AXUIElementSetAttributeValue(win, "AXMain", True)
    AXUIElementPerformAction(win, "AXRaise")
    AXUIElementSetAttributeValue(inp, "AXFocused", True)
    time.sleep(0.05)


SEND_LOG = os.path.expanduser("~/.kamoflauge/send.log")


def _send_log(result: str) -> None:
    """어느 전송 방법이 통했는지 남긴다 (메시지 내용과 방 이름은 남기지 않음)."""
    try:
        with open(SEND_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {result}\n")
    except OSError:
        pass


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
            if role == "AXImage":
                items.append((role, text, 0, 0))
                continue
            p, sz = _xy(pos, kAXValueCGPointType), _xy(size, kAXValueCGSizeType)
            items.append((role, text, p[0] if p else 0, sz[0] if sz else 0))
    return items


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
            imgs = [r for r, *_ in items if r == "AXImage"]
            if imgs and (has_profile or time_s):
                bodies = [("사진", 0)]  # 텍스트 없는 말풍선 = 사진/이모티콘
            else:
                continue  # 날짜 구분선 등
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


def parse_table(table, last_n: int = 40) -> list[Message]:
    rows = list(_attr(table, "AXRows") or [c for c in _children(table) if _attr(c, "AXRole") == "AXRow"])
    p = _point(table)
    cell_left = p[0] + 1 if p else 0
    # 앞쪽 메시지의 보낸 사람을 알기 위해 조금 더 넉넉히 읽는다
    rows = rows[-(last_n + 10):]
    parsed = parse_rows([_cell_items(r) for r in rows], cell_left)
    return parsed[-last_n:]


def parse_window(win, last_n: int = 40) -> list[Message]:
    table = _message_table(win)
    return [] if table is None else parse_table(table, last_n)


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
