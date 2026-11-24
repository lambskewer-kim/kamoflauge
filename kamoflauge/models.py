from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Message:
    sender: str          # 상대 이름 (내 메시지면 "")
    text: str
    time: str = ""       # "오후 2:03" 같은 표시용 문자열
    is_me: bool = False

    def key(self) -> tuple:
        # 시간은 비교에서 제외: 카톡은 같은 분 메시지가 이어지면 시간 표시를 마지막 것으로 옮긴다
        return (self.sender, self.text, self.is_me)


@dataclass(frozen=True)
class Room:
    id: str              # 어댑터 내부 식별자 (맥에서는 창 제목)
    name: str
