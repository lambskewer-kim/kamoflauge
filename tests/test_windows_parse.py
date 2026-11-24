"""윈도우 카톡에서 복사한 대화 텍스트 파서 테스트 (윈도우가 아니어도 돈다)."""
from kamoflauge.adapters.windows import guess_my_name, parse_clipboard

SAMPLE = """\
2026년 11월 24일 화요일
홍길동님이 들어왔습니다.
[홍길동] [오후 3:15] 안녕
[홍길동] [오후 3:15] 여러 줄
메시지야
[김철수] [오후 3:16] ㅋㅋ
[홍길동] [오후 3:17] 사진
"""


def test_parse_basic():
    msgs = parse_clipboard(SAMPLE, my_name="김철수")
    assert [(m.sender, m.text, m.is_me) for m in msgs] == [
        ("홍길동", "안녕", False),
        ("홍길동", "여러 줄\n메시지야", False),
        ("", "ㅋㅋ", True),
        ("홍길동", "사진", False),
    ]
    assert msgs[0].time == "오후 3:15"


def test_parse_crlf_and_english_time():
    text = "[Hong] [3:15 PM] hi\r\n[Me] [PM 3:16] yo\r\n"
    msgs = parse_clipboard(text, my_name="Me")
    assert [(m.sender, m.text, m.is_me, m.time) for m in msgs] == [
        ("Hong", "hi", False, "3:15 PM"),
        ("", "yo", True, "PM 3:16"),
    ]


def test_parse_without_my_name_keeps_everyone_as_others():
    msgs = parse_clipboard(SAMPLE)
    assert not any(m.is_me for m in msgs)


def test_guess_my_name_in_one_to_one_room():
    assert guess_my_name(SAMPLE, "홍길동") == "김철수"


def test_guess_my_name_fails_in_group_room():
    assert guess_my_name(SAMPLE, "랩실 단톡") == ""


def test_empty_text():
    assert parse_clipboard("") == []
