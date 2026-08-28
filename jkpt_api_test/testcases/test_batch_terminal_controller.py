# testcases/test_batch_terminal_controller.py
# 设备批量管理接口 — S3 拆类范式（一接口一 TestClass，allure 按接口分组）
#
# 类序即执行序：Import → Details → Remark → AggrPoint → LngLat → MoveGroup → Export → Delete(解绑)
# 依赖声明（extract 链）：
#   TestBt01BatchImport   正向提取 batch_addrs（首个正向写一次，类级标记防重复）→ extract.yaml
#   TestBt02~07           消费 {{batch_addrs}}（详情/备注/聚合点/经纬度/移动分组/导出）
#   TestBt08BatchDelete   消费 {{batch_addrs}}（批量解绑，放在最后防数据自毁）
#   TestBt06MoveGroup     newGroupId 走 group_fixture["one_id"]（fixture 依赖，非 extract）
# YAML 映射：batch_import_cases→TestBt01 / batch_details_cases→TestBt02 / batch_remark_cases→TestBt03
#           batch_aggr_point_cases→TestBt04 / batch_lnglat_cases→TestBt05
#           batch_move_group_cases→TestBt06 / batch_export_cases→TestBt07 / batch_delete_cases→TestBt08
import io
import jsonpath
import os
import pytest
from common.case_report_util import assert_response
from common.export_assert_util import assert_export_response
from common.logger_util import sep, key, print_request, print_response
from common.requests_util import BaseRequest
from common.yaml_util import read_yaml, write_yaml, resolve_extract_value

_jsonpath_parse = jsonpath.jsonpath
http = BaseRequest()

_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
_TEMPLATE_XLSX = r"C:\Users\33606\Desktop\BD_loc_mon_api_test\jkpt_api_test\yaml\import-device-template2026_5_1.xlsx"

_TEST_DATA = read_yaml("./yaml/test_batch_terminal_controller.yaml")


class _BatchTerminalHelpers:
    """不被 pytest 收集；供 8 个接口类复用断言。"""

    def _assert_and_report(self, case, res):
        return assert_response(
            case,
            res,
            biz_context={"请求用例": case["name"]},
        )

    def _assert_export_response(self, case, res, addr_list=None):
        """导出接口统一走公共断言，不再只看 HTTP 200。"""
        assert_export_response(
            case_name=case["name"],
            response=res,
            expected=case["expected"],
            require_binary=bool(case.get("binary_response")),
            addr_count=len(addr_list) if addr_list else None,
        )


class TestBt01BatchImport(_BatchTerminalHelpers):
    """POST /api/monitor/terminals/batch/import — 批量导入设备（提取 batch_addrs）"""

    _first_batch_addrs_written = False

    @pytest.mark.parametrize("case", _TEST_DATA["batch_import_cases"])
    def test_batch_import(self, base_url, auth_headers, case):
        """批量导入设备（正向提取 batch_addrs 写入 extract.yaml）"""
        url = f"{base_url}/api/monitor/terminals/batch/import"
        headers = {**auth_headers}
        scenario = case.get("scenario", "positive")
        files = None

        if scenario == "positive":
            if not os.path.isfile(_TEMPLATE_XLSX):
                pytest.skip(f"缺少导入模板文件: {_TEMPLATE_XLSX}")
            with open(_TEMPLATE_XLSX, "rb") as fp:
                files = {
                    "importFile": (
                        os.path.basename(_TEMPLATE_XLSX),
                        fp,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                }
                sep(f" 测试用例: {case['name']}")
                print_request("POST", url, headers=headers)
                res = http.send_request(
                    "post",
                    url,
                    headers=headers,
                    files=files,
                    case_name=case["name"],
                    log_level="none",
                )
        elif scenario == "no_file":
            sep(f" 测试用例: {case['name']}")
            print_request("POST", url, headers=headers)
            res = http.send_request(
                "post",
                url,
                headers=headers,
                case_name=case["name"],
                log_level="none",
            )
        elif scenario == "empty_file":
            files = {"importFile": ("empty.xlsx", io.BytesIO(b""), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
            sep(f" 测试用例: {case['name']}")
            print_request("POST", url, headers=headers)
            res = http.send_request(
                "post",
                url,
                headers=headers,
                files=files,
                case_name=case["name"],
                log_level="none",
            )
        else:
            pytest.fail(f"未知场景类型: {scenario}")

        print_response(res)
        json_data = self._assert_and_report(case, res)
        code = json_data["code"]

        if scenario == "positive" and code == 0 and not TestBt01BatchImport._first_batch_addrs_written:
            addrs = _jsonpath_parse(json_data, "$.data.addedTerminals[*].addr") or []
            addrs = [addr for addr in addrs if addr]
            if addrs:
                write_yaml("./extract.yaml", {"batch_addrs": ",".join(addrs)}, mode="append")
                TestBt01BatchImport._first_batch_addrs_written = True


class TestBt02BatchDetails(_BatchTerminalHelpers):
    """POST /api/monitor/terminals/batch/details — 批量查询设备详情（消费 {{batch_addrs}}）"""

    @pytest.mark.parametrize("case", _TEST_DATA["batch_details_cases"])
    def test_batch_query_details(self, base_url, auth_headers, case):
        """批量查询设备详细信息"""
        url = f"{base_url}/api/monitor/terminals/batch/details"
        headers = {**auth_headers, "Content-Type": "application/json"}
        addrs_raw = case.get("addrs")
        addrs = resolve_extract_value(addrs_raw, required=True)
        body = {"addrs": addrs}

        sep(f" 测试用例: {case['name']}")
        print_request("POST", url, json=body, headers=headers)
        res = http.send_request(
            "post",
            url,
            json=body,
            headers=headers,
            case_name=case["name"],
            log_level="none",
        )
        print_response(res)
        self._assert_and_report(case, res)


class TestBt03BatchRemark(_BatchTerminalHelpers):
    """POST /api/monitor/terminals/batch/remark — 批量查询设备备注（消费 {{batch_addrs}}）"""

    @pytest.mark.parametrize("case", _TEST_DATA["batch_remark_cases"])
    def test_batch_query_remark(self, base_url, auth_headers, case):
        """批量查询设备备注信息"""
        url = f"{base_url}/api/monitor/terminals/batch/remark"
        headers = {**auth_headers, "Content-Type": "application/json"}
        addrs_raw = case.get("addrs")
        addrs = resolve_extract_value(addrs_raw, required=True)
        body = {"addrs": addrs}

        sep(f" 测试用例: {case['name']}")
        print_request("POST", url, json=body, headers=headers)
        res = http.send_request(
            "post",
            url,
            json=body,
            headers=headers,
            case_name=case["name"],
            log_level="none",
        )
        print_response(res)
        self._assert_and_report(case, res)


class TestBt04BatchAggrPoint(_BatchTerminalHelpers):
    """POST /api/monitor/terminals/batch/aggr-point-details — 聚合点批量查询（消费 {{batch_addrs}}）"""

    @pytest.mark.parametrize("case", _TEST_DATA["batch_aggr_point_cases"])
    def test_batch_aggr_point(self, base_url, auth_headers, case):
        """根据聚合点批量查询设备详细信息"""
        url = f"{base_url}/api/monitor/terminals/batch/aggr-point-details"
        headers = {**auth_headers, "Content-Type": "application/json"}
        addrs_raw = case.get("addrs")
        addrs = resolve_extract_value(addrs_raw, required=True)
        body = {
            "addrs": addrs,
            "page": case.get("page", 1),
            "pageSize": case.get("pageSize", 100),
        }

        sep(f" 测试用例: {case['name']}")
        print_request("POST", url, json=body, headers=headers)
        res = http.send_request(
            "post",
            url,
            json=body,
            headers=headers,
            case_name=case["name"],
            log_level="none",
        )
        print_response(res)
        self._assert_and_report(case, res)


class TestBt05BatchLngLat(_BatchTerminalHelpers):
    """POST /api/monitor/terminals/batch/lnglat-details — 经纬度批量查询"""

    @pytest.mark.parametrize("case", _TEST_DATA["batch_lnglat_cases"])
    def test_batch_lnglat(self, base_url, auth_headers, case):
        """根据经纬度批量查询设备详细信息"""
        url = f"{base_url}/api/monitor/terminals/batch/lnglat-details"
        headers = {**auth_headers, "Content-Type": "application/json"}
        body = {
            "points": case.get("points") or [],
            "page": case.get("page", 1),
            "pageSize": case.get("pageSize", 100),
        }
        addr_val = case.get("addr")
        if addr_val:
            body["addr"] = addr_val

        sep(f" 测试用例: {case['name']}")
        print_request("POST", url, json=body, headers=headers)
        res = http.send_request(
            "post",
            url,
            json=body,
            headers=headers,
            case_name=case["name"],
            log_level="none",
        )
        print_response(res)
        self._assert_and_report(case, res)


class TestBt06BatchMoveGroup(_BatchTerminalHelpers):
    """PUT /api/monitor/terminals/batch/move-group — 批量移动分组（消费 {{batch_addrs}} + group_fixture）"""

    @pytest.mark.parametrize("case", _TEST_DATA["batch_move_group_cases"])
    def test_batch_move_group(self, base_url, auth_headers, group_fixture, case):
        """批量移动分组"""
        url = f"{base_url}/api/monitor/terminals/batch/move-group"
        headers = {**auth_headers, "Content-Type": "application/json"}
        addrs_raw = case.get("addrs")
        addrs = resolve_extract_value(addrs_raw, required=True)

        ng_raw = case.get("newGroupId")
        if "{{one_id}}" in str(ng_raw):
            new_gid = group_fixture.get("one_id")
        else:
            new_gid = ng_raw

        body = {"addrs": addrs, "newGroupId": new_gid}

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


class TestBt07BatchExport(_BatchTerminalHelpers):
    """POST /api/monitor/terminals/batch/export — 批量导出设备（消费 {{batch_addrs}}）"""

    @pytest.mark.parametrize("case", _TEST_DATA["batch_export_cases"])
    def test_batch_export(self, base_url, auth_headers, case):
        """批量导出设备信息（成功为二进制流或 JSON 错误）"""
        url = f"{base_url}/api/monitor/terminals/batch/export"
        headers = {**auth_headers, "Content-Type": "application/json", "Time-Zone": "Asia/Shanghai","time-zone-utc": "+08:00"}
        addrs_raw = case.get("addrs")
        addrs = resolve_extract_value(addrs_raw, required=True)
        addr_list = [a.strip() for a in str(addrs).split(",") if a.strip()] if addrs else []

        sep(f" 测试用例: {case['name']}")
        key("请求方法", "POST")
        key("请求地址", url)
        key("请求体", addr_list)
        key("请求头", {k: ("******" if k.lower() == "authorization" else v) for k, v in headers.items()})
        res = http.send_request(
            "post",
            url,
            json=addr_list,
            headers=headers,
            case_name=case["name"],
            log_level="none",
        )
        print_response(res)
        self._assert_export_response(case, res, addr_list=addr_list)


class TestBt08BatchDelete(_BatchTerminalHelpers):
    """DELETE /api/monitor/terminals/batch — 批量解绑设备（消费 {{batch_addrs}}，置于最后防数据自毁）"""

    @pytest.mark.parametrize("case", _TEST_DATA["batch_delete_cases"])
    def test_batch_delete(self, base_url, auth_headers, case):
        """批量解绑设备"""
        url = f"{base_url}/api/monitor/terminals/batch"
        headers = {**auth_headers, "Content-Type": "application/json"}
        addrs_raw = case.get("addrs")
        addrs = resolve_extract_value(addrs_raw, required=True)
        body = {"addrs": addrs}

        sep(f" 测试用例: {case['name']}")
        print_request("DELETE", url, json=body, headers=headers)
        res = http.send_request(
            "delete",
            url,
            json=body,
            headers=headers,
            case_name=case["name"],
            log_level="none",
        )
        print_response(res)
        self._assert_and_report(case, res)
