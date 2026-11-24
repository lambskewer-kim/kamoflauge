"""맥: Shift를 '누르고 있는지' 확인한다 (실명 보기용).

터미널은 Shift만 단독으로 눌렀을 때는 아무 키 이벤트도 보내지 않는다. 그래서 Quartz로 현재 키보드
modifier 상태를 직접 읽는다. 다른 앱을 쓰는 중에 Shift를 눌러도 실명이 뜨지 않도록, 지금 맨 앞 창이
이 프로그램을 띄운 터미널(조상 프로세스)일 때만 True를 돌려준다.
"""
from __future__ import annotations

import os
import subprocess
import time

FRONT_CACHE = 0.3  # 맨 앞 앱 확인(창 목록 조회, 수십 ms)은 이 간격(초)으로만 다시 한다


def ancestor_pids() -> set[int]:
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


class ShiftWatcher:
    def __init__(self) -> None:
        import Quartz  # type: ignore
        self._q = Quartz
        self.ancestors = ancestor_pids()
        self.available = bool(self.ancestors)
        self._front = (0.0, False)

    def _shift_pressed(self) -> bool:
        q = self._q
        return bool(q.CGEventSourceFlagsState(q.kCGEventSourceStateCombinedSessionState) & q.kCGEventFlagMaskShift)

    def front_pid(self) -> int | None:
        """맨 앞 창의 주인 프로세스. NSWorkspace.frontmostApplication은 이벤트 루프가 없는 프로그램에서
        실행 시점 값에 멈춰 있을 수 있어서, 화면의 창 목록(앞에서부터 정렬됨)으로 매번 확인한다."""
        q = self._q
        wins = q.CGWindowListCopyWindowInfo(
            q.kCGWindowListOptionOnScreenOnly | q.kCGWindowListExcludeDesktopElements, q.kCGNullWindowID)
        front = next((w for w in wins or [] if w.get("kCGWindowLayer") == 0), None)
        return int(front["kCGWindowOwnerPID"]) if front else None

    def terminal_in_front(self) -> bool:
        now = time.time()
        if now - self._front[0] > FRONT_CACHE:
            self._front = (now, self.front_pid() in self.ancestors)
        return self._front[1]

    def shift_down(self) -> bool:
        return self.available and self._shift_pressed() and self.terminal_in_front()

    # --- kamoflauge shifttest ---
    def diagnose_header(self) -> list[str]:
        return [f"입력 모니터링 권한: {'OK' if self._q.CGPreflightListenEventAccess() else '없음'}",
                f"이 터미널로 인정하는 프로세스: {sorted(self.ancestors)}"]

    def diagnose_line(self) -> str:
        front = self.front_pid()
        return (f"Shift={'눌림' if self._shift_pressed() else '-   '}  맨 앞 창 pid={front}  "
                f"이 터미널={'예' if front in self.ancestors else '아니오'}  → 실명 보기 {'동작' if self.shift_down() else '안 함'}")
