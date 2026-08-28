import json

from common.logger_util import print_result
from common.requests_util import sanitize_sensitive_data

try:
    import allure  # pyright: ignore[reportMissingImports]
except Exception:
    allure = None


def _attach_text(content, name):
    """安全附加脱敏文本到 Allure。"""
    if allure:
        allure.attach(
            str(sanitize_sensitive_data(content)),
            name=name,
            attachment_type=allure.attachment_type.TEXT,
        )


def _attach_json(data, name):
    """安全附加脱敏 JSON 到 Allure。"""
    if allure:
        allure.attach(
            json.dumps(
                sanitize_sensitive_data(data),
                indent=2,
                ensure_ascii=False,
                default=str,
            ),
            name=name,
            attachment_type=allure.attachment_type.JSON,
        )


def assert_api_result(
    case_name,
    expected_code,
    expected_msg,
    actual_code,
    actual_msg,
    biz_context=None,
    compare_message=True,
):
    """
    统一接口断言与 Allure 附件输出。

    - 成功：附加简要成功信息
    - 失败：附加失败上下文并抛出清晰断言错误
    """
    code_matches = actual_code == expected_code
    message_matches = not compare_message or actual_msg == expected_msg
    if code_matches and message_matches:
        print_result(True, "验证通过!")
        message_summary = actual_msg if compare_message else "[未配置消息断言]"
        _attach_text(
            f"验证通过: code={actual_code}, msg={message_summary}",
            name="【成功】验证结果",
        )
        return

    failure_context = {
        "测试用例": case_name,
        "预期结果": {
            "code": expected_code,
            "msg": expected_msg
        },
        "实际结果": {
            "code": actual_code,
            "msg": actual_msg
        },
        "业务上下文": biz_context or {}
    }
    print_result(False, "验证失败!")
    _attach_json(failure_context, name="【失败】验证失败上下文")

    sanitized_actual_msg = sanitize_sensitive_data(actual_msg)
    assert actual_code == expected_code, (
        f"[{case_name}] code不匹配: 预期={expected_code}, "
        f"实际={actual_code}, msg={sanitized_actual_msg}"
    )
    if compare_message:
        sanitized_expected_msg = sanitize_sensitive_data(expected_msg)
        assert actual_msg == expected_msg, (
            f"[{case_name}] msg不匹配: 预期={sanitized_expected_msg}, "
            f"实际={sanitized_actual_msg}"
        )
