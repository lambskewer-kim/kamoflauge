from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import ChatEntry, Message, Room


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

    # --- 선택 기능 (지원 안 하는 어댑터는 NotImplementedError) ---
    def chat_list(self, limit: int = 20) -> list[ChatEntry]:
        """카톡 채팅 목록(최근 순). 창으로 안 연 방도 포함."""
        raise NotImplementedError

    def open_room(self, name: str) -> None:
        """채팅 목록에서 방을 찾아 창으로 연다."""
        raise NotImplementedError

    def close_room(self, room_id: str) -> None:
        """채팅방 창을 닫는다."""
        raise NotImplementedError

    def close(self) -> None:
        pass
