from testcases.test_alarm_controller import _AlarmHelpers


def test_alarm_status_supports_name_value_holder_unhandled_and_handled():
    assert _AlarmHelpers._is_unhandled_alarm(
        {"handleStatus": {"name": "UN_HANDLED", "value": "未处理"}, "handleTimeStr": ""}
    ) is True
    assert _AlarmHelpers._is_unhandled_alarm(
        {"handleStatus": {"name": "PROCESSED", "value": "已处理"}, "handleTimeStr": "2026-08-28 12:00:00"}
    ) is False


def test_alarm_status_unknown_does_not_default_to_unhandled():
    assert _AlarmHelpers._is_unhandled_alarm(
        {"handleStatus": {"name": "UNKNOWN", "value": "未知"}, "handleTimeStr": None, "handleResult": None}
    ) is None


def test_handled_evidence_prefers_status_and_time_over_result_only():
    assert _AlarmHelpers._handled_evidence(
        {"handleStatus": {"name": "HANDLED"}, "handleResult": "已处理"},
        "已处理",
    )[0] is True
    assert _AlarmHelpers._handled_evidence(
        {"handleStatus": {"name": "UN_HANDLED"}, "handleResult": "已处理"},
        "已处理",
    )[0] is False
    assert _AlarmHelpers._handled_evidence(
        {"handleResult": "已处理"}, "已处理"
    )[0] is True
