import pytest  # pyright: ignore[reportMissingImports]

from common.captcha_util import CaptchaRecognizer, generate_captcha_id
from common.case_report_util import assert_response
from common.logger_util import sep, key, print_request, print_response
from common.requests_util import BaseRequest, parse_response_json
from common.yaml_util import read_yaml

# 全局实例
http = BaseRequest()
ocr = CaptchaRecognizer()


class TestLoginAPI:
    """
    登录接口测试（负向场景）
    """

    test_data = read_yaml("./yaml/test_login.yaml")["login_cases"]

    @pytest.mark.parametrize("case", test_data)
    def test_login_negative(self, base_url, auth_headers, case):
        """登录接口负向测试；动态验证码识别失败时重试，不掩盖最终业务断言。"""
        url = f"{base_url}/api/monitor/web-user/login"
        headers = {**auth_headers}
        uses_fixed_wrong_captcha = case["name"] == "验证码错误"
        max_attempts = 1 if uses_fixed_wrong_captcha else 3

        for attempt in range(1, max_attempts + 1):
            if uses_fixed_wrong_captcha:
                captcha_id = case["captchaId"]
                captcha_text = case["captcha"]
            else:
                captcha_id = generate_captcha_id()
                captcha_url = f"{base_url}/api/monitor/captcha?captchaId={captcha_id}"
                resp = http.send_request(
                    method="get",
                    url=captcha_url,
                    case_name="获取验证码",
                    log_level="none",
                )
                captcha_text = ocr.recognize_from_response(resp)

            payload = {
                "account": case["account"],
                "password": case["password"],
                "captcha": captcha_text,
                "captchaId": captcha_id,
            }
            sep(f" 测试用例: {case['name']} ")
            key("captchaId", captcha_id)
            key("验证码", captcha_text)
            print_request("POST", url, params=payload, headers=headers)
            res = BaseRequest().send_request(
                method="post",
                url=url,
                params=payload,
                headers=headers,
                case_name=case["name"],
                log_level="none",
            )
            print_response(res)

            response_data = parse_response_json(res, context=case["name"])
            captcha_invalid = (
                not uses_fixed_wrong_captcha
                and response_data.get("code") == 999
                and response_data.get("msg") == "验证码错误"
            )
            if captcha_invalid and attempt < max_attempts:
                key("验证码识别重试", f"第 {attempt}/{max_attempts} 次识别结果未通过")
                continue

            assert_response(
                case,
                res,
                biz_context={
                    "请求参数": {
                        "account": case["account"],
                        "captchaId": captcha_id,
                        "captcha": (
                            captcha_text
                            if uses_fixed_wrong_captcha
                            else "[动态获取]"
                        ),
                    }
                },
            )
            return
