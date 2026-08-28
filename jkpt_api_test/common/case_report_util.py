# common/case_report_util.py
"""用例层通用「信封断言 + 扩展结果」工具。

抽取动机：对讲群（`_IgHelpers`）与对讲群消息（`_ImHelpers`）两套 suite 逐字重复同一套
headers/send/assert/report 逻辑（规则：≥2 个 testcase 重复 ≥5 行 → 抽到 common/）。
口径原样保留：扩展断言成功只打一行结论，失败才打全表 + Allure 附件。
"""
import json as _json

import jsonpath

from common.allure_assert_util import assert_api_result
from common.logger_util import key, print_request, print_response, print_result, sep
from common.requests_util import parse_response_json, sanitize_sensitive_data
from common.yaml_util import read_expected_msg

try:
    import allure
except Exception:
    allure = None

_jsonpath_parse = jsonpath.jsonpath


def jp_first(data, expr):
    """jsonpath 取首个匹配；无匹配返回 None（jsonpath 失败返回 False 的坑已封）。"""
    found = _jsonpath_parse(data, expr)
    if found:
        return found[0]
    return None


def jp_list(data, expr):
    """jsonpath 取列表；无匹配返回 []。"""
    found = _jsonpath_parse(data, expr)
    return found if found else []


def case_headers(auth_headers, case):
    """`no_auth: true` 用例剥 Authorization，保留 Accept-Language。"""
    headers = {**auth_headers}
    if case.get("no_auth"):
        headers.pop("Authorization", None)
    return headers


def send_case(http, method, url, case, headers, *, params=None, json=None):
    """打印请求/响应并返回响应 JSON 对象；保留 intercom 既有调用契约。"""
    sep(f" 测试用例: {case['name']}")
    print_request(method.upper(), url, params=params, json=json, headers=headers)
    response = http.send_request(
        method,
        url,
        params=params,
        json=json,
        headers=headers,
        case_name=case["name"],
        log_level="none",
    )
    json_data = parse_response_json(response, context=case["name"])
    print_response(response)
    return json_data


def _expected_has_message(expected):
    return isinstance(expected, dict) and (
        "msg" in expected or "error_msg" in expected
    )


def assert_case(case, json_data, biz_context=None):
    """兼容信封断言：保留 dict 入参与 `(code, msg)` 返回值。"""
    if not isinstance(json_data, dict):
        raise AssertionError(
            f"[{case['name']}] 响应信封必须是 JSON object，实际={type(json_data).__name__}"
        )
    if "code" not in json_data:
        raise AssertionError(f"[{case['name']}] 响应缺少 $.code")

    expected = case.get("expected") or {}
    message_is_expected = _expected_has_message(expected)
    message_is_present = "msg" in json_data
    if message_is_expected and not message_is_present:
        raise AssertionError(f"[{case['name']}] 响应缺少 $.msg")

    code = json_data["code"]
    msg = json_data.get("msg")
    expected_msg = read_expected_msg(expected) if message_is_expected else None

    sep(" 断言结果 ")
    key("预期 code", expected.get("code"))
    key("实际 code", code)
    key("预期 msg", expected_msg if message_is_expected else "[未配置]")
    key("实际 msg", msg if message_is_present else "[缺失]")
    assert_api_result(
        case_name=case["name"],
        expected_code=expected.get("code"),
        expected_msg=expected_msg,
        actual_code=code,
        actual_msg=msg,
        biz_context=biz_context,
        compare_message=message_is_expected,
    )
    return code, msg


def assert_response(
    case,
    response,
    biz_context=None,
    expected_http_status=None,
):
    """普通 REST 统一入口：安全解析、可选 HTTP 校验、信封断言并返回 JSON。"""
    expected = case.get("expected") or {}
    configured_http_status = expected_http_status
    if configured_http_status is None:
        configured_http_status = expected.get("http_status")
    if (
        configured_http_status is not None
        and response.status_code != configured_http_status
    ):
        raise AssertionError(
            f"[{case['name']}] HTTP 状态码不匹配: "
            f"预期={configured_http_status}, 实际={response.status_code}"
        )

    json_data = parse_response_json(response, context=case["name"])
    assert_case(case, json_data, biz_context)
    return json_data


def report_extra(title, rows, *, ok, summary=None):
    """扩展结果：成功一行结论 + Allure 压缩 JSON；失败框+全表 + Allure rows。"""
    line = summary or (f"{title}通过" if ok else f"{title}失败")
    if ok:
        print(f"  ✅ {line}")
        if allure:
            allure.attach(
                _json.dumps(
                    sanitize_sensitive_data(
                        {"title": title, "ok": True, "summary": line}
                    ),
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                ),
                name=f"【扩展】{title}",
                attachment_type=allure.attachment_type.JSON,
            )
        return
    sep(title)
    print(f"  {'项':<32} {'期望':<28} {'实际'}")
    sanitized_rows = sanitize_sensitive_data(rows)
    for row in sanitized_rows:
        print(
            f"  {str(row.get('项', '')):<32} "
            f"{str(row.get('期望', '')):<28} "
            f"{str(row.get('实际', ''))}"
        )
    print_result(False, f"{title}失败")
    if allure:
        allure.attach(
            _json.dumps(
                sanitize_sensitive_data(
                    {"title": title, "ok": False, "rows": rows}
                ),
                indent=2,
                ensure_ascii=False,
                default=str,
            ),
            name=f"【扩展】{title}",
            attachment_type=allure.attachment_type.JSON,
        )


def report_extra_and_assert(title, rows, summary):
    """扩展结果 + 失败即抛：行内 `通过` 为 False 即整体失败。"""
    ok = all(r.get("通过", True) for r in rows)
    report_extra(title, rows, ok=ok, summary=summary if ok else None)
    if not ok:
        failed_rows = [row for row in rows if row.get("通过") is False]
        raise AssertionError(
            f"{title}失败: {sanitize_sensitive_data(failed_rows)}"
        )
