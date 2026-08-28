# testcases/test_location_controller.py
# 位置管理接口 — S3 拆类范式（一接口一 TestClass，allure 按接口分组）
#
# 类序即执行序：List → Track → Export（三接口相互独立，均消费 bd_test_terminal 造数，无 extract 链）
# YAML 映射：location_list_cases → TestLc01 / location_track_cases → TestLc02 / location_export_cases → TestLc03
# 计划见 plan/location-controller-tests.plan.md：addr 仅用 bd_test_terminal；时间窗为 Asia/Shanghai 当天
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from common.requests_util import BaseRequest
from common.yaml_util import read_yaml
from common.logger_util import sep, key, print_request, print_response
from common.case_report_util import assert_response
from common.export_assert_util import assert_export_response

http = BaseRequest()
_SHANGHAI = ZoneInfo("Asia/Shanghai")

_TEST_DATA = read_yaml("./yaml/test_location_controller.yaml")


class _LocationHelpers:
    """不被 pytest 收集；供三个接口类复用查询/断言/造数。"""

    test_data = _TEST_DATA

    # ---------- 辅助 ----------
    @staticmethod
    def _today_range_shanghai():
        d = datetime.now(_SHANGHAI).date().strftime("%Y-%m-%d")
        return f"{d} 00:00:00", f"{d} 23:59:59"

    def _time_window(self, case):
        st = case.get("startTimeStr")
        et = case.get("endTimeStr")
        if st and et:
            return st, et
        return self._today_range_shanghai()

    def _resolve_bd_addr(self, yaml_value, bd_test_terminal):
        if isinstance(yaml_value, str) and yaml_value.strip() == "{{bd_test_terminal}}":
            return bd_test_terminal
        return yaml_value if yaml_value is not None else ""

    def _build_location_query_params(self, headers, addr, case):
        """OpenAPI 将 Authorization 标为 query；与 Header 一并传入以兼容网关。"""
        auth = headers.get("Authorization") or ""
        start_str, end_str = self._time_window(case)
        params = {
            "Authorization": auth,
            "addr": addr,
            "startTimeStr": start_str,
            "endTimeStr": end_str,
        }
        if "page" in case:
            params["page"] = case.get("page", 1)
        if "pageSize" in case:
            params["pageSize"] = case.get("pageSize", 100)
        return params

    def _no_auth_headers(self, auth_headers):
        headers = {**auth_headers}
        return {k: v for k, v in headers.items() if k.lower() != "authorization"}

    def _assert_and_report(self, case, response, biz_context=None):
        return assert_response(
            case,
            response,
            biz_context=biz_context or {"请求用例": case["name"]},
        )

    def _assert_export_response(self, case, res):
        """导出接口统一走公共断言，不再只看 HTTP 200。"""
        assert_export_response(
            case_name=case["name"],
            response=res,
            expected=case["expected"],
            require_binary=bool(case.get("binary_response")),
        )


class TestLc01LocationList(_LocationHelpers):
    """GET /api/monitor/locations — 分页查询位置列表"""

    @pytest.mark.parametrize("case", _TEST_DATA["location_list_cases"])
    def test_location_list(self, base_url, auth_headers, bd_test_terminal, case):
        """分页查询位置列表"""
        url = f"{base_url}/api/monitor/locations"
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers = self._no_auth_headers(headers)

        addr = self._resolve_bd_addr(case.get("addr"), bd_test_terminal)
        params = self._build_location_query_params(headers, addr, case)

        sep(f" 测试用例: {case['name']}")
        print_request("GET", url, params=params, headers=headers)
        res = http.send_request(
            "get",
            url,
            params=params,
            headers=headers,
            case_name=case["name"],
            log_level="none",
        )
        print_response(res)
        self._assert_and_report(case, res)


class TestLc02LocationTrack(_LocationHelpers):
    """GET /api/monitor/locations/track — 轨迹查询"""

    @pytest.mark.parametrize("case", _TEST_DATA["location_track_cases"])
    def test_location_track(self, base_url, auth_headers, bd_test_terminal, case):
        """轨迹查询"""
        url = f"{base_url}/api/monitor/locations/track"
        headers = {**auth_headers}

        addr = self._resolve_bd_addr(case.get("addr"), bd_test_terminal)
        params = self._build_location_query_params(headers, addr, case)

        sep(f" 测试用例: {case['name']}")
        print_request("GET", url, params=params, headers=headers)
        res = http.send_request(
            "get",
            url,
            params=params,
            headers=headers,
            case_name=case["name"],
            log_level="none",
        )
        print_response(res)
        self._assert_and_report(case, res)


class TestLc03LocationExport(_LocationHelpers):
    """POST /api/monitor/locations/export — 导出轨迹（Time-Zone 头）"""

    @pytest.mark.parametrize("case", _TEST_DATA["location_export_cases"])
    def test_location_export(self, base_url, auth_headers, bd_test_terminal, case):
        """导出轨迹；正文为 JSON 时断言业务 code/msg，否则断言 HTTP + 非空二进制"""
        url = f"{base_url}/api/monitor/locations/export"
        headers = {
            **auth_headers,
            "Time-Zone": "Asia/Shanghai",
            "time-zone-utc": "+08:00"
        }

        addr = self._resolve_bd_addr(case.get("addr"), bd_test_terminal)
        params = self._build_location_query_params(headers, addr, case)

        sep(f" 测试用例: {case['name']}")
        key("请求方法", "POST")
        key("请求地址", url)
        key("查询参数", {k: ("******" if k.lower() == "authorization" else v) for k, v in params.items()})
        key("请求头", {k: ("******" if k.lower() == "authorization" else v) for k, v in headers.items()})
        res = http.send_request(
            "post",
            url,
            params=params,
            headers=headers,
            case_name=case["name"],
            log_level="none",
        )
        print_response(res)

        if case.get("binary_response"):
            self._assert_export_response(case, res)
        else:
            self._assert_and_report(case, res)
