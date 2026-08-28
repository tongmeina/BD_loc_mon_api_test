import json
from pathlib import Path

import pytest
import requests

from common.case_report_util import assert_case, assert_response, send_case
from common.requests_util import (
    BaseRequest,
    NonJsonResponseError,
    get_response_json,
    parse_response_json,
    sanitize_sensitive_data,
)


class CountingResponse(requests.Response):
    def __init__(self, payload=None, *, status_code=200, raw_text=None):
        super().__init__()
        self.status_code = status_code
        self.json_call_count = 0
        self._payload = payload
        if raw_text is None and payload is not None:
            raw_text = json.dumps(payload, ensure_ascii=False)
        self._content = (raw_text or "").encode("utf-8")
        self.headers["Content-Type"] = "application/json"

    def json(self, **kwargs):
        self.json_call_count += 1
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class StubHttp:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def send_request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.response


def test_response_json_is_cached_across_consumers():
    response = CountingResponse({"code": 0, "msg": "成功"})

    assert get_response_json(response)["code"] == 0
    assert parse_response_json(response, context="缓存测试")["msg"] == "成功"
    assert response.json_call_count == 1


def test_parse_response_json_rejects_non_json_with_context():
    response = CountingResponse(raw_text="<html>error</html>", status_code=502)
    response.headers["Content-Type"] = "text/html"

    with pytest.raises(NonJsonResponseError, match="非 JSON") as error_info:
        parse_response_json(response, context="网关响应")

    assert "status=502" in str(error_info.value)
    assert "网关响应" in str(error_info.value)


def test_parse_response_json_rejects_json_array():
    response = CountingResponse([{"code": 0}])

    with pytest.raises(NonJsonResponseError, match="实际 list"):
        parse_response_json(response, context="信封响应")


def test_sanitize_sensitive_data_recursively_masks_credentials_and_pii():
    payload = {
        "Authorization": "secret-token",
        "nested": {
            "phone": "13900001234",
            "email": "qa-user@example.com",
            "captcha": "123456",
            "message": "联系 13900001234 或 qa-user@example.com",
        },
    }

    sanitized = sanitize_sensitive_data(payload)

    assert sanitized["Authorization"] == "******"
    assert sanitized["nested"]["phone"] == "139******34"
    assert sanitized["nested"]["email"] == "q***@example.com"
    assert sanitized["nested"]["captcha"] == "******"
    assert "13900001234" not in sanitized["nested"]["message"]
    assert "qa-user@example.com" not in sanitized["nested"]["message"]


def test_sensitive_response_mode_masks_code_like_data_without_changing_default():
    response_payload = {"code": 0, "msg": "成功", "data": "A12345"}

    assert sanitize_sensitive_data(response_payload)["data"] == "A12345"
    assert sanitize_sensitive_data(
        response_payload,
        mask_verification_code_values=True,
    )["data"] == "******"


def test_base_request_sensitive_context_masks_verification_code_data():
    response = CountingResponse({"code": 0, "msg": "成功", "data": "123456"})

    context = BaseRequest()._build_response_context(
        response,
        elapsed_ms=5,
        redact_response_secrets=True,
    )

    assert context["body"]["data"] == "******"
    assert response.json_call_count == 1


def test_assert_case_requires_code_field():
    case = {"name": "缺 code", "expected": {"code": 0, "msg": "成功"}}

    with pytest.raises(AssertionError, match=r"响应缺少 \$\.code"):
        assert_case(case, {"msg": "成功"})


def test_assert_case_requires_message_when_yaml_declares_message():
    case = {"name": "缺 msg", "expected": {"code": 0, "msg": "成功"}}

    with pytest.raises(AssertionError, match=r"响应缺少 \$\.msg"):
        assert_case(case, {"code": 0})


def test_assert_case_allows_missing_message_when_yaml_does_not_declare_it():
    case = {"name": "仅业务码", "expected": {"code": 0}}

    code, message = assert_case(case, {"code": 0})

    assert code == 0
    assert message is None


def test_assert_case_preserves_null_message_instead_of_converting_to_empty():
    case = {"name": "null msg", "expected": {"code": 0, "msg": ""}}

    with pytest.raises(AssertionError, match="msg不匹配"):
        assert_case(case, {"code": 0, "msg": None})


def test_assert_response_only_checks_http_status_when_configured():
    response = CountingResponse({"code": 0, "msg": "成功"}, status_code=202)
    case_without_http = {"name": "未配置 HTTP", "expected": {"code": 0, "msg": "成功"}}
    case_with_http = {
        "name": "配置 HTTP",
        "expected": {"code": 0, "msg": "成功", "http_status": 200},
    }

    assert_response(case_without_http, response)
    with pytest.raises(AssertionError, match="HTTP 状态码不匹配"):
        assert_response(case_with_http, response)


def test_send_case_keeps_dict_return_contract_and_uses_cached_json():
    response = CountingResponse({"code": 0, "msg": "成功"})
    http = StubHttp(response)
    case = {"name": "兼容入口", "expected": {"code": 0, "msg": "成功"}}

    json_data = send_case(
        http,
        "get",
        "http://example.test/api",
        case,
        {"Authorization": "token"},
    )

    assert json_data == {"code": 0, "msg": "成功"}
    assert response.json_call_count == 1
    assert http.calls[0]["method"] == "get"


def test_testcases_do_not_import_low_level_assert_api_result_directly():
    testcase_directory = Path(__file__).parents[1] / "testcases"
    violations = []
    forbidden_import = "from common.allure_assert_util import assert_api_result"

    for testcase_path in sorted(testcase_directory.glob("test_*.py")):
        source = testcase_path.read_text(encoding="utf-8")
        if forbidden_import in source:
            violations.append(testcase_path.name)

    assert violations == [], (
        "普通 testcase 应使用 common.case_report_util.assert_response；"
        f"发现底层断言直连: {violations}"
    )


def test_assert_case_reads_negative_message_from_error_msg():
    case = {"name": "负向 error_msg", "expected": {"code": 1001, "error_msg": "参数错误"}}

    assert_case(case, {"code": 1001, "msg": "参数错误"}) == (1001, "参数错误")
