# testcases/test_terminal_controller.py
# 设备管理接口 — S3 拆类范式（一接口一 TestClass，allure 按接口分组）
#
# 类序即执行序：Add → Update → BatchAdd → Follow → Move → List → EnumAdd
# 依赖声明（extract 链）：
#   TestTm01AddTerminal     首个成功提取 devices_addr（类级标记防重复）→ extract.yaml
#   TestTm02/04/05          消费 {{devices_addr}}（编辑/关注/移动分组）
#   TestTm03BatchAddTerminals 提取 addrList（SN 批量添加成功的 addr 串）
#   TestTm07AddTerminalByEnum  枚举入库+添加（terminal_type_enum_cases fixture，无 YAML expected）
#   groupId 全部走 group_fixture（three_id/two_id/one_id，fixture 依赖非 extract）
# YAML 映射：add_terminal_cases→TestTm01 / update_terminal_cases→TestTm02 / batch_add_terminals_cases→TestTm03
#           follow_terminal_cases→TestTm04 / move_terminal_cases→TestTm05
#           list_terminals_cases→TestTm06 / (枚举走 fixture)→TestTm07
import jsonpath
import pytest

from common.case_report_util import assert_response
from common.cleanup import register_glht_inventory
from common.logger_util import print_request, print_response, sep
from common.requests_util import BaseRequest
from common.yaml_util import read_yaml, resolve_extract_value, write_yaml

_jsonpath_parse = jsonpath.jsonpath
http = BaseRequest()

_TEST_DATA = read_yaml("./yaml/test_terminal_controller.yaml")


class _TerminalHelpers:
    """不被 pytest 收集；供 7 个接口类复用断言/取组。"""

    @staticmethod
    def _resolve_group_id(case_value, fixture_value):
        placeholder = f"{{{{{fixture_value[0]}}}}}" if False else None  # noqa: 保留占位说明
        return fixture_value if case_value and str(fixture_value) in str(case_value) else case_value

    def _assert_and_report_res(self, res, case_name):
        """接受 Response 对象的断言（枚举用例无 YAML expected）"""
        enum_case = {
            "name": case_name,
            "expected": {"code": 0, "msg": "成功"},
        }
        return assert_response(enum_case, res)

    def _assert_and_report(self, case, res):
        """统一断言并输出报告"""
        return assert_response(case, res)


class TestTm01AddTerminal(_TerminalHelpers):
    """POST /api/monitor/groups/{groupId}/terminals — 添加单个设备（提取 devices_addr）"""

    _first_addr_extracted = False  # 控制只提取第一个成功的设备地址

    @pytest.mark.parametrize("case", _TEST_DATA["add_terminal_cases"])
    def test_add_terminal(self, base_url, auth_headers, group_fixture, case):
        """添加单个设备"""
        group_id = group_fixture.get("three_id") if "{{three_id}}" in str(case.get("groupId")) else case.get("groupId")
        url = f"{base_url}/api/monitor/groups/{group_id}/terminals"
        headers = {**auth_headers, "Content-Type": "application/json"}

        terminal_data = {
            "addr": case.get("addr", ""),
            "remark": case.get("remark", ""),
            "useScope": case.get("useScope", "ANIMAL"),
            "sn": case.get("sn", ""),
            "password": case.get("password", ""),
            "trackColor": case.get("trackColor", "#141323"),
            "trackSize": case.get("trackSize", 5),
            "gatewayParam": case.get("gatewayParam"),
            "fieldJson": case.get("fieldJson", {}),
            "fields": case.get("fields", [])
        }

        sep(f" 测试用例: {case['name']}")
        print_request("POST", url, json=terminal_data, headers=headers)
        res = http.send_request(
            "post", url,
            json=terminal_data,
            headers=headers,
            case_name=case["name"],
            log_level="none"
        )
        print_response(res)

        # 成功时提取 addr 供后续编辑用例使用
        json_data = self._assert_and_report(case, res)
        code = json_data["code"]
        if code == 0 and not TestTm01AddTerminal._first_addr_extracted:
            terminal_addr = _jsonpath_parse(json_data, "$.data.addr")
            if terminal_addr:
                write_yaml("./extract.yaml", {"devices_addr": terminal_addr[0]}, mode="append")
                TestTm01AddTerminal._first_addr_extracted = True


class TestTm02UpdateTerminal(_TerminalHelpers):
    """PUT /api/monitor/groups/{groupId}/terminals — 编辑设备（消费 {{devices_addr}}）"""

    @pytest.mark.parametrize("case", _TEST_DATA["update_terminal_cases"])
    def test_update_terminal(self, base_url, auth_headers, group_fixture, case):
        """编辑设备"""
        group_id = group_fixture.get("three_id") if "{{three_id}}" in str(case.get("groupId")) else case.get("groupId")
        url = f"{base_url}/api/monitor/groups/{group_id}/terminals"
        headers = {**auth_headers, "Content-Type": "application/json"}

        devices_addr = resolve_extract_value("{{devices_addr}}", required=True)

        terminal_data = {
            "addr": devices_addr,
            "remark": case.get("remark", ""),
            "useScope": case.get("useScope", "ANIMAL"),
            "sn": case.get("sn", ""),
            "password": case.get("password", ""),
            "trackColor": case.get("trackColor", "#141323"),
            "trackSize": case.get("trackSize", 5),
            "gatewayParam": case.get("gatewayParam"),
            "fieldJson": case.get("fieldJson", {}),
            "fields": case.get("fields", [])
        }

        sep(f" 测试用例: {case['name']}")
        print_request("PUT", url, json=terminal_data, headers=headers)
        res = http.send_request(
            "put", url,
            json=terminal_data,
            headers=headers,
            case_name=case["name"],
            log_level="none"
        )
        print_response(res)

        self._assert_and_report(case, res)


class TestTm03BatchAddTerminals(_TerminalHelpers):
    """POST /api/monitor/groups/{groupId}/terminals/batch — 手动 SN 批量添加（提取 addrList）"""

    @pytest.mark.parametrize("case", _TEST_DATA["batch_add_terminals_cases"])
    def test_batch_add_terminals(self, base_url, auth_headers, group_fixture, case):
        """手动输入SN码批量添加"""
        group_id = group_fixture.get("two_id") if "{{two_id}}" in str(case.get("groupId")) else case.get("groupId")
        url = f"{base_url}/api/monitor/groups/{group_id}/terminals/batch"
        headers = {**auth_headers, "Content-Type": "application/json"}

        items = []
        yaml_items = case.get("item", [])
        for yaml_item in yaml_items:

            items.append({
                "sn": yaml_item.get("sn", ""),
                "remark": yaml_item.get("remark", ""),
                "password": yaml_item.get("password", "")
            })

        batch_data = {
            "useScope": case.get("useScope", "TRAIN"),
            "item": items,
            "gatewayParam": case.get("gatewayParam")
        }

        sep(f" 测试用例: {case['name']}")
        print_request("POST", url, json=batch_data, headers=headers)
        res = http.send_request(
            "post", url,
            json=batch_data,
            headers=headers,
            case_name=case["name"],
            log_level="none"
        )
        print_response(res)

        json_data = self._assert_and_report(case, res)
        code = json_data["code"]
        if code == 0:
            added_terminals = _jsonpath_parse(json_data, "$.data.addedTerminals")
            if added_terminals and len(added_terminals) > 0:
                addrs = [t.get("addr") for t in added_terminals if isinstance(t, dict)]
                if addrs:
                    write_yaml("./extract.yaml", {"addrList": ",".join(addrs)}, mode="append")


class TestTm04FollowTerminal(_TerminalHelpers):
    """PUT .../terminals/{addr}/follow — 关注/收藏设备（消费 {{devices_addr}}）"""

    @pytest.mark.parametrize("case", _TEST_DATA["follow_terminal_cases"])
    def test_follow_terminal(self, base_url, auth_headers, group_fixture, case):
        """关注/收藏设备"""
        group_id = group_fixture.get("three_id") if "{{three_id}}" in str(case.get("groupId")) else case.get("groupId")
        devices_addr = resolve_extract_value("{{devices_addr}}", required=True)
        url = f"{base_url}/api/monitor/groups/{group_id}/terminals/{devices_addr}/follow"
        headers = {**auth_headers}

        sep(f" 测试用例: {case['name']}")
        print_request("PUT", url, headers=headers)
        res = http.send_request(
            "put", url,
            headers=headers,
            case_name=case["name"],
            log_level="none"
        )
        print_response(res)

        self._assert_and_report(case, res)


class TestTm05MoveTerminal(_TerminalHelpers):
    """PUT .../terminals/{addr}/move — 移动设备分组（消费 {{devices_addr}}）"""

    @pytest.mark.parametrize("case", _TEST_DATA["move_terminal_cases"])
    def test_move_terminal(self, base_url, auth_headers, group_fixture, case):
        """移动设备分组"""
        group_id = group_fixture.get("three_id") if "{{three_id}}" in str(case.get("groupId")) else case.get("groupId")
        new_group_id = group_fixture.get("one_id") if "{{one_id}}" in str(case.get("newGroupId")) else case.get("newGroupId")
        devices_addr = resolve_extract_value("{{devices_addr}}", required=True)
        url = f"{base_url}/api/monitor/groups/{group_id}/terminals/{devices_addr}/move"
        headers = {**auth_headers}

        params = {"newGroupId": new_group_id}

        sep(f" 测试用例: {case['name']}")
        print_request("PUT", url, params=params, headers=headers)
        res = http.send_request(
            "put", url,
            params=params,
            headers=headers,
            case_name=case["name"],
            log_level="none"
        )
        print_response(res)

        self._assert_and_report(case, res)


class TestTm06ListTerminals(_TerminalHelpers):
    """GET /api/monitor/groups/{groupId}/terminals — 分页获取分组下设备列表"""

    @pytest.mark.parametrize("case", _TEST_DATA["list_terminals_cases"])
    def test_list_terminals(self, base_url, auth_headers, group_fixture, case):
        """分页获取分组下设备列表"""
        group_id = group_fixture.get("two_id") if "{{two_id}}" in str(case.get("groupId")) else case.get("groupId")
        url = f"{base_url}/api/monitor/groups/{group_id}/terminals"
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers.pop("Authorization", None)

        params = {
            "addr": case.get("addr", ""),
            "page": case.get("page", 1),
            "pageSize": case.get("pageSize", 100),
        }

        sep(f" 测试用例: {case['name']}")
        print_request("GET", url, params=params, headers=headers)
        res = http.send_request(
            "get", url,
            params=params,
            headers=headers,
            case_name=case["name"],
            log_level="none"
        )
        print_response(res)

        self._assert_and_report(case, res)


class TestTm07AddTerminalByEnum(_TerminalHelpers):
    """枚举 terminalType 入库 → 正式添加（terminal_type_enum_cases fixture，非 YAML 驱动）"""

    def test_add_terminal_by_enum(self, base_url, auth_headers, group_fixture, terminal_type_enum_cases):
        """每种 terminalType 入库 -> 正式添加（循环遍历枚举用例）"""
        group_id = group_fixture["three_id"]
        auth = auth_headers["Authorization"]

        for case in terminal_type_enum_cases:
            sep(f" 入库: {case['terminalType']} SN={case['sn']}")
            r_storage = http.send_request(
                "get",
                f"{base_url}/api/monitor/mock-in-storage",
                params={
                    "Authorization": auth,
                    "addr": case["sn"],
                    "sn": case["sn"],
                    "name": case["remark"],
                    "remark": case["remark"],
                    "terminalType": case["terminalType"],
                    "useScope": case["useScope"],
                },
                log_level="none",
            )
            print_response(r_storage)
            storage_case_name = f"入库 {case['terminalType']} SN={case['sn']}"
            storage_case = {
                "name": storage_case_name,
                "expected": {"code": 0},
            }
            try:
                assert_response(
                    storage_case,
                    r_storage,
                    biz_context={
                        "terminalType": case["terminalType"],
                        "SN": case["sn"],
                    },
                )
            except AssertionError as error:
                pytest.fail(
                    f"入库失败 [{case['terminalType']} SN={case['sn']}]: {error}"
                )
            register_glht_inventory(case["sn"])

            sep(f" 添加: {case['terminalType']} SN={case['sn']}")
            r_add = http.send_request(
                "post",
                f"{base_url}/api/monitor/groups/{group_id}/terminals",
                json={
                    "addr": "",
                    "remark": case["remark"],
                    "useScope": case["useScope"],
                    "sn": case["sn"],
                    "password": "",
                    "terminalType": case["terminalType"],
                    "trackColor": "#141323",
                    "trackSize": 5,
                    "gatewayParam": {
                        "colorCodeId": 1,
                        "gid": 0,
                        "radioRcvChn": "",
                        "radioSndChn": "",
                        "radioPower": 0,
                        "rxCss": "",
                        "txCss": "",
                        "width": 0,
                    },
                    "fieldJson": "",
                    "fields": [
                        {"name": "自定义字段1", "value": "自定义值1"},
                        {"name": "自定义字段2", "value": "自定义值2"},
                    ],
                },
                headers={**auth_headers, "Content-Type": "application/json"},
                case_name=f"枚举添加-{case['terminalType']}",
                log_level="none",
            )
            print_response(r_add)
            self._assert_and_report_res(r_add, f"枚举添加-{case['terminalType']}")
