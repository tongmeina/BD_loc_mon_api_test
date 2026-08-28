"""验证码发送接口自动化：仅验证当前发送接口，不消费验证码或调用下游接口。

真实短信/邮件默认关闭。正向场景使用 YAML 中经明确授权配置的专用接收端；
启用 JKPT_ENABLE_VER_CODE_DELIVERY 后才会发送，限频探测另受
JKPT_ENABLE_VER_CODE_ABUSE_TEST 控制。
"""
import json
import os
import re
import time
import uuid

import jsonpath
import pytest

from common.case_report_util import assert_response
from common.logger_util import key, mask_log_data, print_request, print_response, sep
from common.requests_util import BaseRequest, parse_response_json
from common.yaml_util import read_yaml

_jsonpath_parse = jsonpath.jsonpath
_TEST_DATA = read_yaml("./yaml/test_ver_code_controller.yaml")
_LAST_DELIVERY_AT = 0.0


class _VerCodeHelpers:
    """验证码接口共享参数构造、开关控制、断言和安全检查。"""

    _ENDPOINT = ""

    @staticmethod
    def _enabled(name):
        return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _mask_recipient(value):
        return mask_log_data(value, "to")

    @classmethod
    def _recipient(cls, case):
        source = case.get("recipient_source")
        if source == "test_phone":
            value = os.getenv("JKPT_VER_CODE_TEST_PHONE", "").strip()
        elif source == "test_email":
            value = os.getenv("JKPT_VER_CODE_TEST_EMAIL", "").strip()
        else:
            value = case.get("to")

        if case.get("requires_delivery"):
            if not cls._enabled("JKPT_ENABLE_VER_CODE_DELIVERY"):
                pytest.skip("真实短信/邮件发送未开启：JKPT_ENABLE_VER_CODE_DELIVERY=false")
            if not value:
                pytest.skip(f"缺少专用测试接收端配置：{source or 'case.to'}")
        return value

    @classmethod
    def _wait_delivery_cooldown(cls):
        global _LAST_DELIVERY_AT
        cooldown = float(os.getenv("JKPT_VER_CODE_COOLDOWN_SECONDS", "3"))
        elapsed = time.monotonic() - _LAST_DELIVERY_AT
        if _LAST_DELIVERY_AT and cooldown > elapsed:
            time.sleep(cooldown - elapsed)
        _LAST_DELIVERY_AT = time.monotonic()

    @staticmethod
    def _headers_and_authorization(auth_headers, auth_mode):
        headers = {**auth_headers}
        if auth_mode in {"missing", "empty", "forged"}:
            headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}

        if auth_mode == "valid":
            return headers, headers.get("Authorization") or ""
        if auth_mode == "missing" or auth_mode == "header_only":
            return headers, None
        if auth_mode == "empty":
            return headers, ""
        if auth_mode == "forged":
            return headers, f"forged-{uuid.uuid4().hex}"
        raise ValueError(f"未知 authorization_mode: {auth_mode}")

    @classmethod
    def _build_params(cls, case, auth_headers):
        auth_mode = case.get("authorization_mode", "valid")
        headers, query_authorization = cls._headers_and_authorization(auth_headers, auth_mode)
        params = {}
        if query_authorization is not None:
            params["Authorization"] = query_authorization
        if "mode" in case:
            params["mode"] = case.get("mode")
        if "to" in case or case.get("recipient_source"):
            params["to"] = cls._recipient(case)
        return headers, params

    @staticmethod
    def _json_strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from _VerCodeHelpers._json_strings(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from _VerCodeHelpers._json_strings(item)

    @classmethod
    def _assert_response_security(cls, case, response, json_data, params):
        """检查验证码、PII 是否出现在响应或响应头中；不打印敏感原值。"""
        serialized = json.dumps(json_data, ensure_ascii=False, default=str)
        recipient = params.get("to")
        token = params.get("Authorization")
        if recipient and recipient not in ("", None):
            assert recipient not in serialized, (
                f"[{case['name']}] 响应回显完整通知对象: {cls._mask_recipient(recipient)}"
            )
        if token:
            assert token not in serialized, f"[{case['name']}] 响应回显 Authorization"

        data_value = json_data.get("data")
        code_like = (
            [data_value]
            if isinstance(data_value, str)
            and re.fullmatch(r"[A-Za-z0-9]{4,8}", data_value)
            and (data_value.isdigit() or any(ch.isdigit() for ch in data_value))
            else []
        )
        assert not code_like, f"[{case['name']}] data 疑似返回明文验证码（值已隐藏）"

        for header_name in response.headers:
            lower_name = header_name.lower()
            assert not any(token_name in lower_name for token_name in ("captcha", "verification-code", "verify-code")), (
                f"[{case['name']}] 响应头疑似携带验证码字段: {header_name}"
            )

    @classmethod
    def _assert_and_report(cls, case, response, params):
        json_data = assert_response(
            case,
            response,
            biz_context={
                "请求参数": mask_log_data(params),
                "接口": cls._ENDPOINT,
            },
        )
        cls._assert_response_security(case, response, json_data, params)
        return json_data

    @classmethod
    def run_case(cls, base_url, auth_headers, case):
        if case.get("abuse") and not cls._enabled("JKPT_ENABLE_VER_CODE_ABUSE_TEST"):
            pytest.skip("限频专项未开启：JKPT_ENABLE_VER_CODE_ABUSE_TEST=false")

        headers, params = cls._build_params(case, auth_headers)
        if case.get("requires_delivery"):
            cls._wait_delivery_cooldown()

        url = f"{base_url}{cls._ENDPOINT}"
        sep(f" 测试用例: {case['name']} ")
        print_request("POST", url, params=params, headers=headers)
        response = BaseRequest().send_request(
            method="post",
            url=url,
            params=params,
            headers=headers,
            case_name=case["name"],
            log_level="none",
            redact_response_secrets=True,
        )
        print_response(response)

        if case.get("observe_only"):
            assert response.status_code < 500, (
                f"[{case['name']}] 限频探测不应返回 5xx，实际={response.status_code}"
            )
            json_data = parse_response_json(response, context=f"{case['name']} 响应")
            assert "code" in json_data, f"[{case['name']}] 限频探测缺少业务 code"
            assert "msg" in json_data, f"[{case['name']}] 限频探测缺少业务 msg"
            key("限频探测结果", {"code": json_data.get("code"), "msg": "[已脱敏]"})
            cls._assert_response_security(case, response, json_data, params)
            self_params = {**params}
            for _ in range(max(0, int(case.get("repeat", 1)) - 1)):
                if case.get("requires_delivery"):
                    cls._wait_delivery_cooldown()
                repeat_response = BaseRequest().send_request(
                    method="post",
                    url=url,
                    params=self_params,
                    headers=headers,
                    case_name=f"{case['name']}-repeat",
                    log_level="none",
                    redact_response_secrets=True,
                )
                assert repeat_response.status_code < 500, (
                    f"[{case['name']}] 重复请求不应返回 5xx，实际={repeat_response.status_code}"
                )
                repeat_json = parse_response_json(
                    repeat_response, context=f"{case['name']} 重复响应"
                )
                cls._assert_response_security(case, repeat_response, repeat_json, self_params)
            return

        cls._assert_and_report(case, response, params)


class TestVc01LoginCode(_VerCodeHelpers):
    _ENDPOINT = "/api/monitor/ver-codes/login"

    @pytest.mark.parametrize("case", _TEST_DATA["login_code_cases"])
    def test_login_code(self, base_url, auth_headers, case):
        self.run_case(base_url, auth_headers, case)


class TestVc02RegisterCode(_VerCodeHelpers):
    _ENDPOINT = "/api/monitor/ver-codes/register"

    @pytest.mark.parametrize("case", _TEST_DATA["register_code_cases"])
    def test_register_code(self, base_url, auth_headers, case):
        self.run_case(base_url, auth_headers, case)


class TestVc03RetrievePasswordCode(_VerCodeHelpers):
    _ENDPOINT = "/api/monitor/ver-codes/retrieve"

    @pytest.mark.parametrize("case", _TEST_DATA["retrieve_password_code_cases"])
    def test_retrieve_password_code(self, base_url, auth_headers, case):
        self.run_case(base_url, auth_headers, case)


class TestVc04UpdatePasswordCode(_VerCodeHelpers):
    _ENDPOINT = "/api/monitor/ver-codes/update/pwd"

    @pytest.mark.parametrize("case", _TEST_DATA["update_password_code_cases"])
    def test_update_password_code(self, base_url, auth_headers, case):
        self.run_case(base_url, auth_headers, case)


class TestVc05BindEmailCode(_VerCodeHelpers):
    _ENDPOINT = "/api/monitor/ver-codes/bind/email"

    @pytest.mark.parametrize("case", _TEST_DATA["bind_email_code_cases"])
    def test_bind_email_code(self, base_url, auth_headers, case):
        self.run_case(base_url, auth_headers, case)


class TestVc06BindPhoneCode(_VerCodeHelpers):
    _ENDPOINT = "/api/monitor/ver-codes/bind/phone"

    @pytest.mark.parametrize("case", _TEST_DATA["bind_phone_code_cases"])
    def test_bind_phone_code(self, base_url, auth_headers, case):
        self.run_case(base_url, auth_headers, case)


class TestVc07SetEmergencyContactCode(_VerCodeHelpers):
    _ENDPOINT = "/api/monitor/ver-codes/set/emergency-contact"

    @pytest.mark.parametrize("case", _TEST_DATA["set_emergency_contact_code_cases"])
    def test_set_emergency_contact_code(self, base_url, auth_headers, case):
        self.run_case(base_url, auth_headers, case)
