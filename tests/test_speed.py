from kamoflauge.app import pick_opened
from kamoflauge.models import Room
from kamoflauge.speed import SPEEDS, find_speed, get_speed, next_speed


def test_find_speed_accepts_korean_and_english():
    assert find_speed("빠르게").key == "fast"
    assert find_speed("SLOW").key == "slow"
    assert find_speed("느림").key == "slow"
    assert find_speed("??") is None
    assert get_speed("??").key == "normal"


def test_speeds_are_ordered_and_cycle():
    fast, normal, slow = SPEEDS
    assert fast.every[1] < normal.every[0] + 1 and normal.every[1] < slow.every[1]
    assert fast.history_mix > normal.history_mix > slow.history_mix
    assert next_speed(slow) == fast


def test_pick_opened_prefers_exact_then_single_new():
    rooms = [Room("a", "a"), Room("점심팟 (3)", "점심팟 (3)")]
    assert pick_opened(rooms, {"a"}, "a").id == "a"
    assert pick_opened(rooms, {"a"}, "점심").id == "점심팟 (3)"
    assert pick_opened(rooms, {"a", "점심팟 (3)"}, "없는방") is None
