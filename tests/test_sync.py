from kamoflauge.models import Message
from kamoflauge.sync import new_messages


def m(text, sender="a", me=False, time=""):
    return Message("" if me else sender, text, time, me)


def test_appended_messages_are_new():
    prev = [m("1"), m("2")]
    cur = [m("1"), m("2"), m("3")]
    assert new_messages(prev, cur) == [m("3")]


def test_scrolled_window_keeps_overlap():
    prev = [m("1"), m("2"), m("3")]
    cur = [m("2"), m("3"), m("4"), m("5")]
    assert [x.text for x in new_messages(prev, cur)] == ["4", "5"]


def test_time_moving_to_last_message_is_not_a_new_message():
    prev = [m("1", time="4:13 PM")]
    cur = [m("1"), m("2", time="4:13 PM")]
    assert [x.text for x in new_messages(prev, cur)] == ["2"]
