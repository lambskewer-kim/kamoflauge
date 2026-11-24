"""Windows 카카오톡을 Win32 메시지로 읽고 쓰는 어댑터 (ctypes만 사용, 추가 패키지 없음).

카톡 PC 채팅방 창 구조 (커뮤니티에 알려진 구조, 버전마다 다를 수 있음):
  #32770 (최상위 창, 제목 = 방 이름)
    RICHEDIT50W                  ← 입력창
    EVA_VH_ListControl_Dblclk    ← 메시지 목록 (직접 그리는 컨트롤이라 글자를 읽을 수 없음)

  - 읽기: 메시지 목록에 Ctrl+A, Ctrl+C를 보내서 클립보드에 복사한 다음 파싱한다.
    원래 클립보드 텍스트는 읽은 뒤 되돌려 놓는다 (텍스트만 복원됨).
  - 쓰기: 입력창에 WM_SETTEXT로 글자를 넣고 Enter를 보낸다. 카톡 창을 앞으로 꺼내지 않는다.

안 맞으면 `kamoflauge dump`로 창 구조를 보고 아래 클래스 이름을 고친다.
"""
from __future__ import annotations

import ctypes
import re
import threading
import time
from ctypes import wintypes

from ..models import Message, Room
from .base import Adapter

ROOM_CLASS = "#32770"
INPUT_CLASS = "RICHEDIT50W"
LIST_CLASS = "EVA_VH_ListControl_Dblclk"
MAIN_CLASS = "EVA_Window_Dblclk"

WM_SETTEXT = 0x000C
WM_GETTEXTLENGTH = 0x000E
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
VK_RETURN = 0x0D
VK_CONTROL = 0x11
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

# "[홍길동] [오후 3:15] 안녕"  /  "[Hong] [3:15 PM] hi"
LINE_RE = re.compile(
    r"^\[(?P<name>[^\]]+)\] \[(?P<time>(?:오전|오후|AM|PM)\s*\d{1,2}:\d{2}|\d{1,2}:\d{2}\s*(?:AM|PM))\] ?(?P<text>.*)$"
)
DATE_RE = re.compile(r"^-*\s*\d{4}년\s*\d{1,2}월\s*\d{1,2}일.*$|^-*\s*\w+day, \w+ \d{1,2}, \d{4}.*$")


# ---------- 순수 함수 (테스트용) ----------

def parse_clipboard(text: str, my_name: str = "") -> list[Message]:
    """카톡 PC에서 복사한 대화 텍스트 → Message 목록.

    헤더가 없는 줄은 바로 앞 메시지의 이어진 줄(여러 줄 메시지)로 본다.
    날짜 구분선과 헤더 없는 첫 줄들(입장 알림 등)은 버린다.
    """
    msgs: list[dict] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        m = LINE_RE.match(line)
        if m:
            name = m["name"].strip()
            msgs.append({"name": name, "time": m["time"], "lines": [m["text"]]})
        elif DATE_RE.match(line.strip()) or not msgs:
            continue
        else:
            msgs[-1]["lines"].append(line)
    out = []
    for d in msgs:
        body = "\n".join(d["lines"]).strip("\n")
        is_me = bool(my_name) and d["name"] == my_name
        out.append(Message("" if is_me else d["name"], body, d["time"], is_me))
    return out


def guess_my_name(text: str, room_title: str) -> str:
    """1:1 방(제목 = 상대 이름)에서 제목이 아닌 다른 이름 하나가 있으면 그게 나다."""
    names = {m["name"].strip() for m in (LINE_RE.match(l.rstrip()) for l in text.splitlines()) if m}
    others = names - {room_title}
    return others.pop() if room_title in names and len(others) == 1 else ""


# ---------- Win32 ----------

def _win32():
    """windll은 Windows에서만 있으므로 처음 쓸 때 불러온다."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    return user32, kernel32


ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM) if hasattr(ctypes, "WINFUNCTYPE") else None


class WinKakaoAdapter(Adapter):
    def __init__(self, my_name: str = ""):
        self.u, self.k = _win32()
        self.my_name = my_name
        self._lock = threading.Lock()  # 클립보드를 쓰는 읽기와 전송이 겹치지 않게

    # --- window helpers ---
    def _class(self, hwnd) -> str:
        buf = ctypes.create_unicode_buffer(256)
        self.u.GetClassNameW(hwnd, buf, 256)
        return buf.value

    def _title(self, hwnd) -> str:
        n = self.u.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        self.u.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def _top_windows(self) -> list:
        out = []
        cb = ENUM_PROC(lambda h, _: out.append(h) or True)
        self.u.EnumWindows(cb, 0)
        return out

    def _children(self, hwnd) -> list:
        out = []
        cb = ENUM_PROC(lambda h, _: out.append(h) or True)
        self.u.EnumChildWindows(hwnd, cb, 0)
        return out

    def _find_child(self, hwnd, cls: str):
        return next((c for c in self._children(hwnd) if self._class(c) == cls), None)

    def _room_windows(self) -> list[tuple[str, int]]:
        wins = []
        for h in self._top_windows():
            if self._class(h) != ROOM_CLASS:
                continue
            if self._find_child(h, INPUT_CLASS) and self._find_child(h, LIST_CLASS):
                wins.append((self._title(h), h))
        return wins

    def _window(self, room_id: str):
        for title, h in self._room_windows():
            if title == room_id:
                return h
        raise KeyError(f"채팅방 창을 찾을 수 없음: {room_id}")

    # --- keyboard ---
    def _post_key(self, hwnd, key: int, ctrl: bool = False) -> None:
        """창을 앞으로 꺼내지 않고 키를 보낸다. Ctrl 조합은 대상 스레드의 키보드 상태를 잠깐 바꿔서 흉내낸다."""
        scan = self.u.MapVirtualKeyW(key, 0)
        lparam = 1 | (scan << 16)
        tid = self.u.GetWindowThreadProcessId(hwnd, None)
        me = self.k.GetCurrentThreadId()
        old = (ctypes.c_ubyte * 256)()
        if ctrl:
            self.u.AttachThreadInput(me, tid, True)
            self.u.GetKeyboardState(old)
            new = (ctypes.c_ubyte * 256)(*old)
            new[VK_CONTROL] |= 0x80
            self.u.SetKeyboardState(new)
            time.sleep(0.01)
        try:
            self.u.PostMessageW(hwnd, WM_KEYDOWN, key, lparam)
            time.sleep(0.01)
            self.u.PostMessageW(hwnd, WM_KEYUP, key, lparam | 0xC0000000)
            time.sleep(0.02)
        finally:
            if ctrl:
                self.u.SetKeyboardState(old)
                self.u.AttachThreadInput(me, tid, False)

    # --- clipboard ---
    def _open_clipboard(self) -> bool:
        for _ in range(20):
            if self.u.OpenClipboard(None):
                return True
            time.sleep(0.01)
        return False

    def _get_clipboard(self) -> str | None:
        if not self._open_clipboard():
            return None
        try:
            h = self.u.GetClipboardData(CF_UNICODETEXT)
            if not h:
                return None
            p = self.k.GlobalLock(h)
            try:
                return ctypes.wstring_at(p) if p else None
            finally:
                self.k.GlobalUnlock(h)
        finally:
            self.u.CloseClipboard()

    def _set_clipboard(self, text: str | None) -> None:
        if not self._open_clipboard():
            return
        try:
            self.u.EmptyClipboard()
            if text is None:
                return
            data = ctypes.create_unicode_buffer(text)
            size = ctypes.sizeof(data)
            h = self.k.GlobalAlloc(GMEM_MOVEABLE, size)
            p = self.k.GlobalLock(h)
            ctypes.memmove(p, data, size)
            self.k.GlobalUnlock(h)
            self.u.SetClipboardData(CF_UNICODETEXT, h)
        finally:
            self.u.CloseClipboard()

    def _copy_chat(self, hwnd) -> str:
        lst = self._find_child(hwnd, LIST_CLASS)
        if not lst:
            return ""
        saved = self._get_clipboard()
        marker = f"kamoflauge-{time.time()}"
        self._set_clipboard(marker)
        try:
            self._post_key(lst, ord("A"), ctrl=True)
            self._post_key(lst, ord("C"), ctrl=True)
            text = ""
            for _ in range(30):  # 카톡이 복사를 끝낼 때까지 잠깐 기다린다
                time.sleep(0.02)
                cur = self._get_clipboard()
                if cur and cur != marker:
                    text = cur
                    break
            return text
        finally:
            self._set_clipboard(saved)

    # --- public ---
    def rooms(self) -> list[Room]:
        seen, out = set(), []
        for title, _ in self._room_windows():
            if title not in seen:
                seen.add(title)
                out.append(Room(title, title))
        return out

    def messages(self, room_id: str, last_n: int = 40) -> list[Message]:
        with self._lock:
            text = self._copy_chat(self._window(room_id))
        if not self.my_name:
            self.my_name = guess_my_name(text, room_id)
        return parse_clipboard(text, self.my_name)[-last_n:]

    def send(self, room_id: str, text: str) -> None:
        with self._lock:
            hwnd = self._window(room_id)
            edit = self._find_child(hwnd, INPUT_CLASS)
            if not edit:
                raise RuntimeError("입력창을 찾지 못했습니다 (kamoflauge dump 로 구조 확인 필요)")
            buf = ctypes.create_unicode_buffer(text)
            self.u.SendMessageW(edit, WM_SETTEXT, 0, ctypes.addressof(buf))
            self._post_key(edit, VK_RETURN)
            time.sleep(0.3)
            if self.u.SendMessageW(edit, WM_GETTEXTLENGTH, 0, 0) > 0:
                raise RuntimeError("전송 실패: 카톡 입력창에 글자가 남아 있습니다")

    def has_input(self, room_id: str) -> bool:
        return self._find_child(self._window(room_id), INPUT_CLASS) is not None


def dump_tree(path: str, redact: bool = True) -> int:
    """카톡 창들과 자식 컨트롤의 클래스/제목을 파일로 저장한다. 한글은 ㅁ으로 가린다."""
    ad = WinKakaoAdapter()
    hide = (lambda s: re.sub(r"[가-힣]", "ㅁ", s)) if redact else (lambda s: s)
    n, lines = 0, []
    for h in ad._top_windows():
        cls = ad._class(h)
        if cls not in (ROOM_CLASS, MAIN_CLASS):
            continue
        lines.append(f"{cls}  title={hide(ad._title(h))!r}  visible={bool(ad.u.IsWindowVisible(h))}")
        n += 1
        for c in ad._children(h)[:200]:
            lines.append(f"    {ad._class(c)}  title={hide(ad._title(c))!r}")
            n += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return n
