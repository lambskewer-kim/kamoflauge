from kamoflauge.palette import find_command, match_commands


def test_prefix_match_first():
    assert [c.name for c in match_commands("clo")] == ["close-chatroom"]
    assert match_commands("")[0].name == "help"


def test_aliases_resolve():
    assert find_command("open").name == "switch"
    assert find_command("oc").name == "open-chatroom"
    assert find_command("nope") is None


def test_needs_arg():
    assert find_command("open-chatroom").needs_arg
    assert not find_command("close-chatroom").needs_arg
