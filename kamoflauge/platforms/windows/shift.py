"""윈도우: Shift를 '누르고 있는지' 확인한다 (실명 보기용).

터미널은 Shift만 단독으로 눌렀을 때는 아무 키 이벤트도 보내지 않는다. 그래서 GetAsyncKeyState로
현재 키보드 상태를 직접 읽는다. 지금 맨 앞 창이 이 프로그램을 띄운 터미널일 때만 True를 돌려준다.
"""
from __future__ import annotations

import ctypes
import os

VK_SHIFT = 0x10
GW_OWNER = 4


def ancestor_pids() -> set[int]:
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
        from ctypes import wintypes
        self._user32 = ctypes.WinDLL("user32")
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        self._user32.GetWindow.restype = wintypes.HWND
        self._user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetConsoleWindow.restype = wintypes.HWND
        self._console = kernel32.GetConsoleWindow()
        self.ancestors = ancestor_pids()
        self.available = True

    def _shift_pressed(self) -> bool:
        return bool(self._user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)

    def terminal_in_front(self) -> bool:
        fg = self._user32.GetForegroundWindow()
        if not fg:
            return False
        if fg == self._console:  # 예전 콘솔 창(conhost)
            return True
        if self._console:
            # Windows Terminal의 실제 창은 의사 콘솔 창의 소유자다.
            owner = self._user32.GetWindow(self._console, GW_OWNER)
            if owner:
                return fg == owner
        pid = ctypes.c_ulong()
        self._user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
        return pid.value in self.ancestors

    def shift_down(self) -> bool:
        return self._shift_pressed() and self.terminal_in_front()

    # --- kamoflauge shifttest ---
    def diagnose_header(self) -> list[str]:
        return [f"콘솔 창: {self._console}", f"이 터미널로 인정하는 프로세스: {sorted(self.ancestors)}"]

    def diagnose_line(self) -> str:
        return (f"Shift={'눌림' if self._shift_pressed() else '-   '}  "
                f"이 터미널이 맨 앞={'예' if self.terminal_in_front() else '아니오'}  "
                f"→ 실명 보기 {'동작' if self.shift_down() else '안 함'}")
