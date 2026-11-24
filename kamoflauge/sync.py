"""폴링한 스냅샷끼리 비교해서 '새 메시지'만 뽑아낸다.

카톡 화면에는 메시지 ID가 없으므로, 이전 스냅샷의 꼬리와
현재 스냅샷의 머리가 가장 길게 겹치는 지점을 찾는다.
"""
from __future__ import annotations

from .models import Message


def new_messages(prev: list[Message], cur: list[Message]) -> list[Message]:
    if not prev:
        return list(cur)
    pk = [m.key() for m in prev]
    ck = [m.key() for m in cur]
    for k in range(min(len(pk), len(ck)), 0, -1):
        if ck[:k] == pk[-k:]:
            return list(cur[k:])
    # 겹치는 부분이 없음: 스크롤이 크게 바뀌었거나 방이 다시 그려짐.
    # 이전 마지막 메시지가 현재 어딘가에 있으면 그 뒤만 새 것으로 본다.
    last = pk[-1]
    for i in range(len(ck) - 1, -1, -1):
        if ck[i] == last:
            return list(cur[i + 1:])
    return list(cur[-3:])
