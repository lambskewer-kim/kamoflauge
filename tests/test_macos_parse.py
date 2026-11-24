"""맥 파서 테스트. AX 호출은 가짜로 바꿔서 돌린다 (pyobjc가 있는 맥에서만)."""
import pytest

M = pytest.importorskip("kamoflauge.platforms.mac.adapter")

LEFT = 142


def other(text, first=False):
    return ([("AXButton", "Profile", 150, 30), ("AXStaticText", "민수", 197, 30)] if first else []) + \
        [("AXImage", "", 0, 0), ("AXTextArea", text, 202, 50)]


def me(text):
    return [("AXImage", "", 0, 0), ("AXTextArea", text, 400, 50)]


@pytest.fixture
def fake_table(monkeypatch):
    def install(rows):
        monkeypatch.setattr(M, "_attr", lambda el, name: rows if name == "AXRows" else None)
        monkeypatch.setattr(M, "_point", lambda el: (LEFT - 1, 0))
        monkeypatch.setattr(M, "_cell_items", lambda row: row)
        return object()
    return install


def test_parse_rows_me_and_continuation():
    msgs = M.parse_rows([other("a", first=True), other("b"), me("c")], LEFT)
    assert [(m.sender, m.text, m.is_me) for m in msgs] == [("민수", "a", False), ("민수", "b", False), ("", "c", True)]


def test_poll_window_extends_back_to_profile_row(fake_table):
    # 끝 2행만 읽으라고 해도, 맨 앞이 이름 없는 연속 메시지면 이름이 있는 행까지 더 읽는다
    rows = [me("x")] * 5 + [other("a", first=True), other("b"), other("c")]
    msgs = M.parse_table(fake_table(rows), min_rows=2)
    assert [(m.sender, m.text) for m in msgs] == [("민수", "a"), ("민수", "b"), ("민수", "c")]


def test_poll_window_stops_at_full_rows(fake_table):
    rows = [other(str(i)) for i in range(M.FULL_ROWS + 20)]  # 이름 있는 행이 없음
    msgs = M.parse_table(fake_table(rows), min_rows=3, last_n=999)
    assert len(msgs) == M.FULL_ROWS


def test_text_less_bubble_is_not_a_photo():
    # 새 메시지가 막 그려져서 말풍선(작은 AXImage)만 있고 글자가 아직 없는 행
    row = [("AXButton", "Profile", 150, 30), ("AXStaticText", "민수", 197, 30), ("AXImage", "", 202, 34)]
    assert M.parse_rows([row], LEFT) == []


def test_large_image_with_share_button_is_a_photo():
    row = [("AXButton", "Profile", 150, 30), ("AXButton", "Share", 754, 31), ("AXStaticText", "민수", 197, 30),
           ("AXImage", "", 483, 127), ("AXImage", "", 609, 127)]
    msgs = M.parse_rows([row], LEFT)
    assert [(m.sender, m.text, m.is_me) for m in msgs] == [("민수", "사진", False)]


def test_my_photo_is_mine():
    row = [("AXButton", "Share", 300, 31), ("AXImage", "", 330, 127)]
    msgs = M.parse_rows([row], LEFT)
    assert [(m.text, m.is_me) for m in msgs] == [("사진", True)]


def test_chat_list_row_unread_comes_after_time():
    # [Profile] 이름 [멤버 수] 시간 [안 읽은 수]: 시간 앞 숫자는 멤버 수, 뒤 숫자는 안 읽은 수
    row = [("AXButton", "Profile", 99, 44), ("AXStaticText", "동아리", 152, 42), ("AXStaticText", "2220", 275, 37),
           ("AXStaticText", "9:12 PM", 335, 49), ("AXStaticText", "300+", 346, 32)]
    assert M.parse_chat_row(row) == M.ChatEntry("동아리", 300)


def test_chat_list_row_member_count_is_not_unread():
    row = [("AXButton", "Profile", 99, 44), ("AXStaticText", "스터디", 152, 53), ("AXStaticText", "5", 204, 14),
           ("AXStaticText", "5:17 PM", 336, 48)]
    assert M.parse_chat_row(row) == M.ChatEntry("스터디", 0)
