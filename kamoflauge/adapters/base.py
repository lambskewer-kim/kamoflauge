from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Message, Room


class Adapter(ABC):
    """카톡과 실제로 통신하는 계층. UI는 이 인터페이스만 안다."""

    @abstractmethod
    def rooms(self) -> list[Room]:
        """현재 읽을 수 있는 채팅방 목록."""

    @abstractmethod
    def messages(self, room_id: str) -> list[Message]:
        """채팅방에 현재 보이는 메시지들 (오래된 것 → 최신)."""

    @abstractmethod
    def send(self, room_id: str, text: str) -> None:
        """메시지 전송. 실패하면 예외."""

    def close(self) -> None:
        pass
