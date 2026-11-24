"""Shift 키를 '누르고 있는지' 확인한다 (macOS, Windows. 그 밖의 OS에서는 항상 False).

터미널은 Shift만 단독으로 눌렀을 때는 아무 키 이벤트도 보내지 않는다. 그래서 OS에서 현재 키보드
상태를 직접 읽는다. 다른 앱을 쓰는 중에 Shift를 눌러도 실명이 뜨지 않도록, 지금 맨 앞 창이
이 프로그램을 띄운 터미널일 때만 True를 돌려준다.
"""
from __future__ import annotations

import os
import subprocess
import sys


def _ancestor_pids_ps() -> set[int]:
    pids, pid = set(), os.getpid()
    for _ in range(30):
        try:
            out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)],
                                 capture_output=True, text=True, timeout=2).stdout.strip()
            pid = int(out)
        except (OSError, ValueError, subprocess.SubprocessError):
            break
        if pid <= 1:
            break
        pids.add(pid)
    return pids


def _ancestor_pids_win() -> set[int]:
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    parent: dict[int, int] = {}
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        ok = k.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            parent[entry.th32ProcessID] = entry.th32ParentProcessID
            ok = k.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k.CloseHandle(snap)
    pids, pid = set(), os.getpid()
    for _ in range(30):
        pid = parent.get(pid, 0)
        if pid <= 4 or pid in pids:
            break
        pids.add(pid)
    return pids


class ShiftWatcher:
    def __init__(self) -> None:
        self._kind = ""
        try:
            if sys.platform == "darwin":
                self._init_mac()
            elif sys.platform == "win32":
                self._init_win()
        except Exception:  # noqa: BLE001  권한/라이브러리 문제면 기능만 끈다
            self._kind = ""

    def _init_mac(self) -> None:
        import Quartz  # type: ignore
        from AppKit import NSWorkspace  # type: ignore
        self._quartz = Quartz
        self._ws = NSWorkspace.sharedWorkspace()
        self._ancestors = _ancestor_pids_ps()
        self._kind = "mac" if self._ancestors else ""

    def _init_win(self) -> None:
        import ctypes
        self._user32 = ctypes.WinDLL("user32")
        self._console = ctypes.WinDLL("kernel32").GetConsoleWindow()
        self._ancestors = _ancestor_pids_win()
        self._kind = "win"

    def shift_down(self) -> bool:
        if self._kind == "mac":
            q = self._quartz
            flags = q.CGEventSourceFlagsState(q.kCGEventSourceStateCombinedSessionState)
            if not flags & q.kCGEventFlagMaskShift:
                return False
            front = self._ws.frontmostApplication()
            return front is not None and front.processIdentifier() in self._ancestors
        if self._kind == "win":
            import ctypes
            if not self._user32.GetAsyncKeyState(0x10) & 0x8000:  # VK_SHIFT
                return False
            fg = self._user32.GetForegroundWindow()
            if fg and fg == self._console:  # 예전 콘솔 창(conhost)
                return True
            pid = ctypes.c_ulong()
            self._user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
            return pid.value in self._ancestors  # Windows Terminal 등
        return False
