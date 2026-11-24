"""mock 어댑터로 UI 흐름을 헤드리스로 확인한다."""
import asyncio
import random
import time

from kamoflauge.adapters.mock import MockAdapter
from kamoflauge.app import Config, Kamoflauge
from kamoflauge.models import Message


def make(filler=False):
    ad = MockAdapter(chatter=1e9)
    ad._next = time.time() + 1e9
    return ad, Kamoflauge(ad, Config(filler=filler, filler_every=(1e9, 1e9)))


def run(coro):
    asyncio.run(coro)


def test_history_mixes_fake_logs_when_auto_claude_on():
    random.seed(0)
    ad, app = make(filler=True)
    ad._rooms["민수"] = [Message("민수", f"m{i}") for i in range(12)]

    async def go():
        async with app.run_test() as pilot:
            await pilot.pause(0.5)
            assert any(e.fake for e in app.entries)
    run(go())


def test_slash_palette_close_and_open_chatroom():
    ad, app = make()

    async def go():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.5)
            first = app.current.id
            await pilot.press(*"/clo")
            await pilot.press("enter")
            await pilot.pause(0.4)
            assert first not in ad._rooms
            await pilot.press(*"/open-chatroom")
            await pilot.press("enter")          # 인자가 필요하면 먼저 완성 + 방 목록
            await pilot.pause(0.4)
            pal = app.query_one("#palette")
            assert pal.visible and all(i.kind == "room" for i in pal.items)
            target = pal.selected.value
            await pilot.press("enter")
            await pilot.pause(0.4)
            assert app.current.id == target
    run(go())


def test_notification_for_other_room_shows_count_only():
    ad, app = make()

    async def go():
        async with app.run_test() as pilot:
            await pilot.pause(0.5)
            other = next(r for r in app.rooms if r.id != app.current.id)
            ad._rooms[other.id] += [Message(other.id, "secret 1"), Message(other.id, "secret 2")]
            for _ in range(40):
                await pilot.pause(0.2)
                notes = [t for e in app.entries for st, t in e.lines if st == "notify"]
                if notes:
                    break
            assert notes and notes[0].endswith("\0" + "2")
            assert not any("secret" in t for e in app.entries for _, t in e.lines)
    run(go())


class NoListAdapter(MockAdapter):
    """윈도우처럼 채팅 목록을 못 읽는 어댑터."""
    def chat_list(self, limit: int = 20):
        raise NotImplementedError


def test_open_chatroom_by_typed_name_without_chat_list():
    ad = NoListAdapter(chatter=1e9)
    ad._next = time.time() + 1e9
    app = Kamoflauge(ad, Config(filler=False, filler_every=(1e9, 1e9)))
    target = next(iter(ad._closed))

    async def go():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.5)
            await pilot.press(*"/open-chatroom ")
            await pilot.pause(0.3)
            pal = app.query_one("#palette")
            assert [i.kind for i in pal.items] == ["hint"]
            await pilot.press(*target)
            await pilot.pause(0.2)
            assert pal.selected.value == target
            await pilot.press("enter")
            await pilot.pause(0.5)
            assert app.current.id == target
            assert not any("not supported" in t for e in app.entries for _, t in e.lines)
    run(go())


def test_speed_command_sets_and_cycles():
    ad, app = make()

    async def go():
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            assert app.speed.key == "normal"
            await app._command("/speed 빠르게")
            assert app.speed.key == "fast"
            await app._command("/speed")
            assert app.speed.key == "normal"
            await app._command("/speed 아무거나")
            assert app.speed.key == "normal"
    run(go())


def test_escape_toggles_panic_mode():
    ad, app = make()

    async def go():
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            await pilot.press("escape")
            assert app.boss
            await pilot.press("escape")
            assert not app.boss
    run(go())


def test_notify_command_turns_background_notifications_off():
    ad, app = make()

    async def go():
        async with app.run_test() as pilot:
            await pilot.pause(0.5)
            await app._command("/notify")
            assert not app.notify_on
            other = next(r for r in app.rooms if r.id != app.current.id)
            app._notify(other.name, 3)
            assert not any(st == "notify" for e in app.entries for st, _ in e.lines)
            await app._command("/bg")
            app._notify(other.name, 3)
            assert any(st == "notify" for e in app.entries for st, _ in e.lines)
    run(go())
