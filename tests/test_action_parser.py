import pytest

from ui_tars_7b_kit.action_parser import parse_mobile_output


def _parse(action_line: str):
    return parse_mobile_output(f"Thought: ok\nAction: {action_line}")


def test_parse_click_point():
    parsed = _parse("click(point='<point>100 200</point>')")
    action = parsed.actions[0]
    assert action.type == "click"
    assert action.params["point"] == (100.0, 200.0)


def test_parse_long_press_point():
    parsed = _parse("long_press(point='<point>10 20</point>')")
    action = parsed.actions[0]
    assert action.type == "long_press"
    assert action.params["point"] == (10.0, 20.0)


def test_parse_type_content_newline():
    parsed = _parse("type(content='hello\\n')")
    action = parsed.actions[0]
    assert action.type == "type"
    assert action.params["content"] == "hello\n"


def test_parse_scroll_direction_and_point():
    parsed = _parse("scroll(point='<point>12 34</point>', direction='down')")
    action = parsed.actions[0]
    assert action.type == "scroll"
    assert action.params["point"] == (12.0, 34.0)
    assert action.params["direction"] == "down"


def test_parse_scroll_tuple_point():
    parsed = _parse("scroll(point='(12,34)', direction='up')")
    action = parsed.actions[0]
    assert action.type == "scroll"
    assert action.params["point"] == (12.0, 34.0)
    assert action.params["direction"] == "up"


def test_parse_open_app():
    parsed = _parse("open_app(app_name='Settings')")
    action = parsed.actions[0]
    assert action.type == "open_app"
    assert action.params["app_name"] == "Settings"


def test_parse_drag_points():
    parsed = _parse(
        "drag(start_point='<point>1 2</point>', end_point='<point>3 4</point>')"
    )
    action = parsed.actions[0]
    assert action.type == "drag"
    assert action.params["start_point"] == (1.0, 2.0)
    assert action.params["end_point"] == (3.0, 4.0)


def test_parse_drag_tuple_points():
    parsed = _parse("drag(start_point='(5,6)', end_point='(7,8)')")
    action = parsed.actions[0]
    assert action.type == "drag"
    assert action.params["start_point"] == (5.0, 6.0)
    assert action.params["end_point"] == (7.0, 8.0)


def test_parse_hotkey():
    parsed = _parse("hotkey(key='enter')")
    action = parsed.actions[0]
    assert action.type == "hotkey"
    assert action.params["key"] == "enter"


def test_parse_finished():
    parsed = _parse("finished(content='done')")
    action = parsed.actions[0]
    assert action.type == "finished"
    assert action.params["content"] == "done"


def test_parse_wait():
    parsed = _parse("wait()")
    action = parsed.actions[0]
    assert action.type == "wait"
    assert action.params == {}


def test_parse_missing_action_raises():
    with pytest.raises(ValueError):
        parse_mobile_output("Thought: ok")
