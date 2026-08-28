# testcases/test_enclosure_controller.py
# 围栏管理接口 — S3 拆类范式（一接口一 TestClass，allure 按接口分组）
#
# 类序即执行序：Add → List → Update → Terminals → Export → AddByCode → Delete
# 依赖声明（extract 链）：
#   TestEn01EnclosureAdd     正向提取 enclosure_id/enclosure_name/enclosure_share_code → extract.yaml
#   TestEn02EnclosureList    消费 {{enclosure_id}}（断言列表包含）
#   TestEn03/04/05/07        消费 {{enclosure_id}}（编辑/绑设备/导出/删除）
#   TestEn06EnclosureAddByCode 正向提取 enclosure_cloned_id（分享码克隆围栏）
#   module 级 _cleanup_enclosures 兜底删除全部测试围栏（含克隆）
# YAML 映射：add_enclosure_cases→TestEn01 / list_enclosure_cases→TestEn02 / update_enclosure_cases→TestEn03
#           add_enclosure_terminals_cases→TestEn04 / export_enclosure_cases→TestEn05
#           add_enclosure_by_code_cases→TestEn06 / delete_enclosure_cases→TestEn07
import jsonpath
import pytest
import re
import time

from common.case_report_util import assert_response
from common.logger_util import key, print_request, print_response, sep
from common.requests_util import BaseRequest, parse_response_json
from common.yaml_util import is_extract_placeholder, read_yaml, resolve_extract_value, write_yaml

_jsonpath_parse = jsonpath.jsonpath
http = BaseRequest()
_STALE_NAME_RE = re.compile(r"^[EU]\d{10}$")
_STALE_NAMES = {"A", "1234567890123"}

_TEST_DATA = read_yaml("./yaml/test_enclosure_controller.yaml")


def _jp_first(data, expr):
    found = _jsonpath_parse(data, expr)
    if found:
        return found[0]
    return None


def _silent_delete(base_url, auth_headers, eid, tag):
    if not eid:
        return
    try:
        http.send_request(
            "delete",
            f"{base_url}/api/monitor/enclosures/{eid}",
            headers=auth_headers,
            case_name=f"teardown-del-{tag}",
            log_level="none",
        )
    except Exception as exc:
        key("teardown-del-失败", f"{tag}: {exc}")


def _append_cleanup_id(eid):
    if not eid:
        return
    existing = resolve_extract_value("{{enclosure_cleanup_ids}}", required=False) or ""
    ids = [x for x in str(existing).split(",") if x]
    sid = str(eid)
    if sid not in ids:
        ids.append(sid)
        write_yaml("./extract.yaml", {"enclosure_cleanup_ids": ",".join(ids)}, mode="append")


def _purge_stale_test_enclosures(base_url, auth_headers):
    """清掉上次失败残留的短名/时间戳名围栏，不删业务围栏。"""
    try:
        res = http.send_request(
            "get",
            f"{base_url}/api/monitor/enclosures",
            headers=auth_headers,
            case_name="teardown-list-stale",
            log_level="none",
        )
        data = parse_response_json(res, context="teardown-list-stale")
    except Exception as exc:
        key("teardown-list-失败", str(exc))
        return
    items = _jsonpath_parse(data, "$.data[*]") or []
    if items is False:
        items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        eid = item.get("id")
        if eid and (name in _STALE_NAMES or _STALE_NAME_RE.match(name)):
            _silent_delete(base_url, auth_headers, eid, f"stale-{name}")


@pytest.fixture(scope="module", autouse=True)
def _cleanup_enclosures(base_url, auth_headers):
    _purge_stale_test_enclosures(base_url, auth_headers)
    yield
    ids = []
    extra = resolve_extract_value("{{enclosure_cleanup_ids}}", required=False)
    if extra:
        ids.extend(str(extra).split(","))
    for extract_key in ("enclosure_cloned_id", "enclosure_id"):
        value = resolve_extract_value("{{%s}}" % extract_key, required=False)
        if value:
            ids.append(str(value))
    seen = set()
    for eid in ids:
        eid = eid.strip()
        if not eid or eid in seen:
            continue
        seen.add(eid)
        _silent_delete(base_url, auth_headers, eid, eid)


class _EnclosureHelpers:
    """不被 pytest 收集；供 7 个接口类复用断言/取数。"""

    # ---------- 辅助 ----------
    @staticmethod
    def _headers(auth_headers, case):
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}
        return headers

    @staticmethod
    def _resolve_enclosure_name(raw):
        name = raw if raw is not None else ""
        if isinstance(name, str) and "{int(time.time())}" in name:
            name = name.replace("{int(time.time())}", str(int(time.time())))
        return name

    @staticmethod
    def _list_ids(data):
        for expr in ("$.data[*].id", "$.data.items[*].id", "$.data.records[*].id"):
            found = _jsonpath_parse(data, expr)
            if found:
                return [str(x) for x in found]
        return []

    def _assert_and_report(self, case, res):
        return assert_response(
            case,
            res,
            biz_context={"请求用例": case["name"]},
        )

    def _assert_kml_or_json(self, case, res):
        raw = res.content or b""
        trimmed = raw.lstrip()
        if trimmed[:1] in (b"{", b"["):
            self._assert_and_report(case, res)
            return

        expected_http = case["expected"].get("http_status", 200)
        preview = trimmed[:500].decode("utf-8", errors="ignore").lower()
        sep(" 断言结果(KML导出) ")
        key("预期 HTTP", expected_http)
        key("实际 HTTP", res.status_code)
        key("响应体字节数", len(raw))
        assert res.status_code == expected_http, (
            f"[{case['name']}] HTTP 状态码不匹配: 预期={expected_http}, 实际={res.status_code}"
        )
        assert len(raw) > 0, f"[{case['name']}] 导出正文为空"
        assert "kml" in preview or "<?xml" in preview, (
            f"[{case['name']}] 预期 KML/XML，实际前缀={trimmed[:80]!r}"
        )


class TestEn01EnclosureAdd(_EnclosureHelpers):
    """POST /api/monitor/enclosures — 添加围栏（正向提取 enclosure_id/share_code）"""

    @pytest.mark.parametrize("case", _TEST_DATA["add_enclosure_cases"])
    def test_enclosure_add(self, base_url, auth_headers, case):
        """POST /enclosures，query: name + pointJson"""
        url = f"{base_url}/api/monitor/enclosures"
        headers = self._headers(auth_headers, case)
        ename = self._resolve_enclosure_name(case.get("enclosureName"))
        params = {"name": ename}
        if case.get("pointJson"):
            params["pointJson"] = case["pointJson"]

        sep(f" 测试用例: {case['name']}")
        print_request("POST", url, params=params, headers=headers)
        res = http.send_request(
            "post",
            url,
            params=params,
            headers=headers,
            case_name=case["name"],
            log_level="none",
        )
        print_response(res)
        json_data = self._assert_and_report(case, res)
        code = json_data["code"]
        if code == 0:
            eid = _jp_first(json_data, "$.data.id")
            _append_cleanup_id(eid)
            if case["name"] == "围栏-创建-正向":
                if not eid:
                    pytest.fail("创建围栏成功但未返回 data.id")
                payload = {"enclosure_id": eid, "enclosure_name": ename}
                share_code = _jp_first(json_data, "$.data.shareCode")
                if share_code:
                    payload["enclosure_share_code"] = share_code
                write_yaml("./extract.yaml", payload, mode="append")


class TestEn02EnclosureList(_EnclosureHelpers):
    """GET /api/monitor/enclosures — 围栏列表（消费 {{enclosure_id}} 断言包含）"""

    @pytest.mark.parametrize("case", _TEST_DATA["list_enclosure_cases"])
    def test_enclosure_list(self, base_url, auth_headers, case):
        """GET /enclosures"""
        url = f"{base_url}/api/monitor/enclosures"
        headers = self._headers(auth_headers, case)

        sep(f" 测试用例: {case['name']}")
        print_request("GET", url, headers=headers)
        res = http.send_request(
            "get",
            url,
            headers=headers,
            case_name=case["name"],
            log_level="none",
        )
        print_response(res)
        json_data = self._assert_and_report(case, res)

        if case.get("no_auth"):
            return
        eid = resolve_extract_value(case.get("enclosureId"), required=True)
        ids = self._list_ids(json_data)
        assert str(eid) in ids, f"列表未包含创建的围栏 id={eid}，实际 ids={ids[:20]}"


class TestEn03EnclosureUpdate(_EnclosureHelpers):
    """PUT /api/monitor/enclosures/{id} — 编辑围栏（消费 {{enclosure_id}}）"""

    @pytest.mark.parametrize("case", _TEST_DATA["update_enclosure_cases"])
    def test_enclosure_update(self, base_url, auth_headers, case):
        """PUT /enclosures/{id}，JSON body: name + pointJson"""
        raw_id = case.get("enclosureId")
        tid = resolve_extract_value(raw_id, required=is_extract_placeholder(raw_id))
        url = f"{base_url}/api/monitor/enclosures/{tid}"
        headers = self._headers(auth_headers, case)
        ename = self._resolve_enclosure_name(case.get("enclosureName"))
        body = {"name": ename}
        if case.get("pointJson"):
            body["pointJson"] = case["pointJson"]

        sep(f" 测试用例: {case['name']}")
        print_request("PUT", url, json=body, headers=headers)
        res = http.send_request(
            "put",
            url,
            json=body,
            headers=headers,
            case_name=case["name"],
            log_level="none",
        )
        print_response(res)
        self._assert_and_report(case, res)


class TestEn04EnclosureTerminals(_EnclosureHelpers):
    """PUT /api/monitor/enclosures/{id}/terminals — 绑/清设备（消费 {{enclosure_id}}）"""

    @pytest.mark.parametrize("case", _TEST_DATA["add_enclosure_terminals_cases"])
    def test_enclosure_terminals(self, base_url, auth_headers, msg_test_terminal, case):
        """PUT /enclosures/{id}/terminals，JSON body 的 addrs 为逗号字符串"""
        tid = resolve_extract_value(case.get("enclosureId"), required=True)
        url = f"{base_url}/api/monitor/enclosures/{tid}/terminals"
        headers = self._headers(auth_headers, case)
        addrs = case.get("addrs")
        if isinstance(addrs, str) and addrs.strip() == "{{msg_test_terminal}}":
            addrs = msg_test_terminal
        body = {"addrs": addrs if addrs is not None else ""}

        sep(f" 测试用例: {case['name']}")
        print_request("PUT", url, json=body, headers=headers)
        res = http.send_request(
            "put",
            url,
            json=body,
            headers=headers,
            case_name=case["name"],
            log_level="none",
        )
        print_response(res)
        self._assert_and_report(case, res)


class TestEn05EnclosureExport(_EnclosureHelpers):
    """GET /api/monitor/enclosures/{id}/export — 导出 KML（消费 {{enclosure_id}}）"""

    @pytest.mark.parametrize("case", _TEST_DATA["export_enclosure_cases"])
    def test_enclosure_export(self, base_url, auth_headers, case):
        """GET /enclosures/{id}/export；正向按 KML/XML 流断言，禁止 xlsx PK"""
        raw_id = case.get("enclosureId")
        tid = resolve_extract_value(raw_id, required=is_extract_placeholder(raw_id))
        url = f"{base_url}/api/monitor/enclosures/{tid}/export"
        headers = self._headers(auth_headers, case)

        sep(f" 测试用例: {case['name']}")
        print_request("GET", url, headers=headers)
        res = http.send_request(
            "get",
            url,
            headers=headers,
            case_name=case["name"],
            log_level="none",
        )
        print_response(res)
        self._assert_kml_or_json(case, res)


class TestEn06EnclosureAddByCode(_EnclosureHelpers):
    """POST /api/monitor/enclosures/codes/{shareCode} — 分享码添加（消费 {{enclosure_share_code}}）"""

    @pytest.mark.parametrize("case", _TEST_DATA["add_enclosure_by_code_cases"])
    def test_enclosure_add_by_code(self, base_url, auth_headers, case):
        """POST /enclosures/codes/{shareCode}；正向他账号字面量，反向自己的码"""
        raw_code = case.get("shareCode")
        share = resolve_extract_value(raw_code, required=is_extract_placeholder(raw_code))
        url = f"{base_url}/api/monitor/enclosures/codes/{share}"
        headers = self._headers(auth_headers, case)

        sep(f" 测试用例: {case['name']}")
        print_request("POST", url, headers=headers)
        res = http.send_request(
            "post",
            url,
            headers=headers,
            case_name=case["name"],
            log_level="none",
        )
        print_response(res)
        json_data = self._assert_and_report(case, res)
        code = json_data["code"]
        if code == 0:
            cloned_id = _jp_first(json_data, "$.data.id")
            _append_cleanup_id(cloned_id)
            if case["name"] == "围栏-分享码添加-正向" and cloned_id:
                write_yaml("./extract.yaml", {"enclosure_cloned_id": cloned_id}, mode="append")


class TestEn07EnclosureDelete(_EnclosureHelpers):
    """DELETE /api/monitor/enclosures/{id} — 删除围栏（消费 {{enclosure_id}}，正向只删主围栏）"""

    @pytest.mark.parametrize("case", _TEST_DATA["delete_enclosure_cases"])
    def test_enclosure_delete(self, base_url, auth_headers, case):
        """DELETE /enclosures/{id}；正向只删主围栏"""
        raw_id = case.get("enclosureId")
        tid = resolve_extract_value(raw_id, required=is_extract_placeholder(raw_id))
        url = f"{base_url}/api/monitor/enclosures/{tid}"
        headers = self._headers(auth_headers, case)

        sep(f" 测试用例: {case['name']}")
        print_request("DELETE", url, headers=headers)
        res = http.send_request(
            "delete",
            url,
            headers=headers,
            case_name=case["name"],
            log_level="none",
        )
        print_response(res)
        self._assert_and_report(case, res)
