"""맥/카톡 없이 UI를 테스트하기 위한 가짜 카톡."""
from __future__ import annotations

import random
import threading
import time

from ..models import Message, Room
from .base import Adapter

_INCOMING = [
    ("민수", "점심 뭐 먹음?"), ("민수", "학식 ㄱ?"), ("엄마", "저녁 먹고 들어오니"),
    ("지은", "교수님 오늘 랩미팅 30분 미뤄진대"), ("지은", "ㅋㅋㅋㅋㅋ"),
    ("민수", "사진"), ("지은", "이모티콘"), ("민수", "오늘 퇴근 몇시?"),
]


class MockAdapter(Adapter):
    def __init__(self, chatter: float = 6.0):
        self._lock = threading.Lock()
        self._rooms = {
            "민수": [Message("민수", "야 뭐함", "오후 1:58"), Message("", "연구실", "오후 1:59", True)],
            "엄마": [Message("엄마", "밥은 먹었어?", "오후 12:10")],
            "랩실 단톡": [
                Message("지은", "오늘 GPU 누가 쓰고 있어요?", "오후 1:40"),
                Message("현우", "제가 4번 쓰고 있어요", "오후 1:41"),
            ],
        }
        self._chatter = chatter
        self._next = time.time() + 3

    def _tick(self) -> None:
        now = time.time()
        if now < self._next:
            return
        self._next = now + random.uniform(self._chatter * 0.5, self._chatter * 1.5)
        sender, text = random.choice(_INCOMING)
        room = sender if sender in self._rooms else "랩실 단톡"
        self._rooms[room].append(Message(sender, text, time.strftime("%H:%M")))

    def rooms(self) -> list[Room]:
        return [Room(k, k) for k in self._rooms]

    def messages(self, room_id: str) -> list[Message]:
        with self._lock:
            self._tick()
            return list(self._rooms.get(room_id, []))[-50:]

    def send(self, room_id: str, text: str) -> None:
        with self._lock:
            self._rooms[room_id].append(Message("", text, time.strftime("%H:%M"), True))
