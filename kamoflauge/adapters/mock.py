"""맥/카톡 없이 UI를 테스트하기 위한 가짜 카톡."""
from __future__ import annotations

import random
import threading
import time

from ..models import Message, Room
from .base import Adapter

# (방, 보낸 사람, 내용). 메시지는 항상 자기 방에만 들어간다.
_INCOMING = [
    ("고딩 친구들", "민수", "야 이번 주 토요일 다들 시간 됨?"),
    ("고딩 친구들", "지은", "나 오후는 됨"),
    ("고딩 친구들", "현우", "ㅋㅋㅋㅋㅋㅋ"),
    ("고딩 친구들", "서연", "어디서 봐? 강남?"),
    ("고딩 친구들", "민수", "사진"),
    ("고딩 친구들", "지은", "이모티콘"),
    ("고딩 친구들", "현우", "나 방금 일어남"),
    ("대학 동기들", "준호", "과제 마감 오늘 자정 맞지?"),
    ("대학 동기들", "하은", "ㅇㅇ 11시 59분까지"),
    ("대학 동기들", "준호", "살려줘"),
    ("민수", "민수", "야 아까 그 짤 뭐였지"),
    ("민수", "민수", "ㅋㅋㅋ 보내줘"),
]


class MockAdapter(Adapter):
    def __init__(self, chatter: float = 6.0):
        self._lock = threading.Lock()
        self._rooms = {
            "고딩 친구들": [
                Message("민수", "다들 살아있냐", "오후 1:52"),
                Message("서연", "ㅇㅇ 연구실", "오후 1:53"),
                Message("", "나도 연구실ㅋㅋ", "오후 1:53", True),
                Message("현우", "다들 고생이 많다", "오후 1:55"),
                Message("지은", "이번 주에 한 번 모이자", "오후 1:56"),
            ],
            "대학 동기들": [
                Message("준호", "내일 수업 휴강이래", "오전 11:20"),
                Message("하은", "개꿀", "오전 11:21"),
            ],
            "민수": [Message("민수", "야 뭐함", "오후 1:58"), Message("", "연구실", "오후 1:59", True)],
        }
        self._chatter = chatter
        self._closed: dict = {"동아리": [Message("수빈", "이번 주 회식 언제?", "오전 9:02")]}  # 창으로 안 연 방
        self._list_unread: dict = {"동아리": 2}
        self._next = time.time() + 3

    def _tick(self) -> None:
        now = time.time()
        if now < self._next:
            return
        self._next = now + random.uniform(self._chatter * 0.5, self._chatter * 1.5)
        room, sender, text = random.choice(_INCOMING)
        if room in self._rooms:
            self._rooms[room].append(Message(sender, text, time.strftime("%H:%M")))
        elif room in self._closed:
            self._closed[room].append(Message(sender, text, time.strftime("%H:%M")))
            self._list_unread[room] = self._list_unread.get(room, 0) + 1

    def rooms(self) -> list[Room]:
        return [Room(k, k) for k in self._rooms]

    def messages(self, room_id: str) -> list[Message]:
        with self._lock:
            self._tick()
            return list(self._rooms.get(room_id, []))[-50:]

    def chat_list(self, limit: int = 20):
        from ..models import ChatEntry
        with self._lock:
            listed = list(self._rooms) + [n for n in self._closed if n not in self._rooms]
            return [ChatEntry(n, self._list_unread.get(n, 0)) for n in listed][:limit]

    def open_room(self, name: str) -> None:
        with self._lock:
            if name not in self._rooms:
                self._rooms[name] = self._closed.pop(name, [])
            self._list_unread.pop(name, None)

    def close_room(self, room_id: str) -> None:
        with self._lock:
            self._closed[room_id] = self._rooms.pop(room_id)

    def send(self, room_id: str, text: str) -> None:
        with self._lock:
            self._rooms[room_id].append(Message("", text, time.strftime("%H:%M"), True))
