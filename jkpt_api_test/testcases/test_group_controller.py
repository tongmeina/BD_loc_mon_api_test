# testcases/test_group_controller.py
# 分组管理接口 — S3 拆类范式（一接口一 TestClass，allure 按接口分组）
#
# 类序即执行序：AddL1 → AddL2 → AddL3 → List → Update → Sort → Delete
# 依赖声明（extract 链，L1→L2→L3 层级造数，顺序刚性）：
#   TestGr01AddGroupL1   正向提取 one_id → extract.yaml
#   TestGr02AddGroupL2   消费 {{one_id}}，提取 two_id
#   TestGr03AddGroupL3   消费 {{two_id}}，提取 three_id
#   TestGr04GetGroups    正向提取 parent_group_ids（全部分组 id 降序串）
#   TestGr05UpdateGroup  消费 {{one_id}}
#   TestGr06SortGroups   消费 {{parent_group_ids}}
#   TestGr07DeleteGroup  消费 {{three_id}}（只删三级，一二三级由 conftest 级联清理）
# ⚠️ conftest 依赖：group_fixture（session 级）在 conftest 内自建 L1/L2/L3，
#    本文件测试群与 fixture 群是两套，session 末统一删除——拆类不影响该机制。
# YAML 映射：add_group_l1_cases→TestGr01 / add_group_l2_cases→TestGr02 / add_group_l3_cases→TestGr03
#           get_groups_cases→TestGr04 / update_group_cases→TestGr05
#           sort_groups_cases→TestGr06 / delete_group_cases→TestGr07
import jsonpath
import pytest
import time
from common.requests_util import BaseRequest
from common.yaml_util import read_yaml, write_yaml, resolve_extract_value
from common.logger_util import sep, print_request, print_response
from common.case_report_util import assert_response

_jsonpath_parse = jsonpath.jsonpath
http = BaseRequest()

_TEST_DATA = read_yaml("./yaml/test_group_controller.yaml")


class _GroupHelpers:
    """不被 pytest 收集；供 7 个接口类复用断言。"""

    def _assert_and_report(self, case, response, biz_context=None):
        """统一断言并输出报告"""
        return assert_response(
            case,
            response,
            biz_context=biz_context or {"请求用例": case["name"]},
        )

    @staticmethod
    def _resolve_group_name(raw):
        name = raw or ""
        if isinstance(name, str) and "{int(time.time())}" in name:
            name = name.replace("{int(time.time())}", str(int(time.time())))
        return name


class TestGr01AddGroupL1(_GroupHelpers):
    """POST /api/monitor/groups (parentId=0) — 添加一级分组（提取 one_id）"""

    @pytest.mark.parametrize("case", _TEST_DATA["add_group_l1_cases"])
    def test_add_group_level1(self, base_url, auth_headers, case):
        """添加分组-一级分组"""
        url = f"{base_url}/api/monitor/groups"
        headers = {**auth_headers}

        parent_id = resolve_extract_value(case.get("parentId"))

        group_name = case.get("groupName", "")

        params = {
            "groupName": group_name,
            "parentId": parent_id
        }

        sep(f" 测试用例: {case['name']}")
        print_request("POST", url, params=params, headers=headers)
        res = http.send_request(
            "post", url,
            params=params,
            headers=headers,
            case_name=case["name"],
            log_level="none"
        )
        print_response(res)
        json_data = self._assert_and_report(
            case,
            res,
            biz_context={"请求参数": params},
        )
        code = json_data["code"]
        if code == 0:
            one_id = _jsonpath_parse(json_data, "$.data.id")
            if one_id:
                write_yaml("./extract.yaml", {"one_id": one_id[0]}, mode="append")


class TestGr02AddGroupL2(_GroupHelpers):
    """POST /api/monitor/groups — 添加二级分组（消费 {{one_id}}，提取 two_id）"""

    @pytest.mark.parametrize("case", _TEST_DATA["add_group_l2_cases"])
    def test_add_group_level2(self, base_url, auth_headers, case):
        """添加分组-二级分组"""
        url = f"{base_url}/api/monitor/groups"
        headers = {**auth_headers}

        parent_id = resolve_extract_value(case.get("parentId"), required=True)

        group_name = case.get("groupName", "")

        params = {
            "groupName": group_name,
            "parentId": parent_id
        }

        sep(f" 测试用例: {case['name']}")
        print_request("POST", url, params=params, headers=headers)
        res = http.send_request(
            "post", url,
            params=params,
            headers=headers,
            case_name=case["name"],
            log_level="none"
        )
        print_response(res)
        json_data = self._assert_and_report(
            case,
            res,
            biz_context={"请求参数": params},
        )
        code = json_data["code"]
        if code == 0:
            two_id = _jsonpath_parse(json_data, "$.data.id")
            if two_id:
                write_yaml("./extract.yaml", {"two_id": two_id[0]}, mode="append")


class TestGr03AddGroupL3(_GroupHelpers):
    """POST /api/monitor/groups — 添加三级分组（消费 {{two_id}}，提取 three_id）"""

    @pytest.mark.parametrize("case", _TEST_DATA["add_group_l3_cases"])
    def test_add_group_level3(self, base_url, auth_headers, case):
        """添加分组-三级分组"""
        url = f"{base_url}/api/monitor/groups"
        headers = {**auth_headers}

        parent_id = resolve_extract_value(case.get("parentId"), required=True)

        group_name = case.get("groupName", "")

        params = {
            "groupName": group_name,
            "parentId": parent_id
        }

        sep(f" 测试用例: {case['name']}")
        print_request("POST", url, params=params, headers=headers)
        res = http.send_request(
            "post", url,
            params=params,
            headers=headers,
            case_name=case["name"],
            log_level="none"
        )
        print_response(res)
        json_data = self._assert_and_report(
            case,
            res,
            biz_context={"请求参数": params},
        )
        code = json_data["code"]
        if code == 0:
            three_id = _jsonpath_parse(json_data, "$.data.id")
            if three_id:
                write_yaml("./extract.yaml", {"three_id": three_id[0]}, mode="append")


class TestGr04GetGroups(_GroupHelpers):
    """GET /api/monitor/groups — 获取分组列表（正向提取 parent_group_ids 降序串）"""

    @pytest.mark.parametrize("case", _TEST_DATA["get_groups_cases"])
    def test_get_groups(self, base_url, auth_headers, case):
        """获取设备分组信息"""
        url = f"{base_url}/api/monitor/groups"

        headers = {} if case.get("no_auth") else {**auth_headers}

        params = {
            "account": "",
            "include": "true",
            "queryType": "ALL",
            "terminalType": ""
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

        json_data = self._assert_and_report(
            case,
            res,
            biz_context={"请求参数": params},
        )

        # 正向用例：提取所有分组ID，降序拼接写入extract.yaml
        if case["name"] == "获取设备分组信息-正向":
            code = json_data["code"]
            if code == 0:
                all_ids = _jsonpath_parse(json_data, "$.data[*].id")
                if all_ids:
                    sorted_ids_desc = sorted(all_ids, reverse=True)
                    group_ids_str = ",".join(str(i) for i in sorted_ids_desc)
                    write_yaml("./extract.yaml", {"parent_group_ids": group_ids_str}, mode="append")


class TestGr05UpdateGroup(_GroupHelpers):
    """PUT /api/monitor/groups/{id} — 编辑分组名称（消费 {{one_id}}）"""

    @pytest.mark.parametrize("case", _TEST_DATA["update_group_cases"])
    def test_update_group(self, base_url, auth_headers, case):
        """编辑分组名称"""
        group_id = resolve_extract_value(case.get("groupId"), required=True)
        url = f"{base_url}/api/monitor/groups/{group_id}"
        headers = {**auth_headers}
        group_name = self._resolve_group_name(case.get("groupName", ""))

        if group_name:  # groupName 有值
            params = {"groupName": group_name}
        else:  # groupName 为空或不存在
            params = {}

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


class TestGr06SortGroups(_GroupHelpers):
    """PUT /api/monitor/groups — 分组排序（消费 {{parent_group_ids}}）"""

    @pytest.mark.parametrize("case", _TEST_DATA["sort_groups_cases"])
    def test_sort_groups(self, base_url, auth_headers, case):
        """分组排序"""
        url = f"{base_url}/api/monitor/groups"
        headers = {**auth_headers}

        group_ids = resolve_extract_value(case.get("groupIds"), required=True)

        if group_ids:
            json_data = {"groupIds": group_ids}
        else:
            json_data = {}

        sep(f" 测试用例: {case['name']}")
        print_request("PUT", url, json=json_data, headers=headers)
        res = http.send_request(
            "put", url,
            json=json_data,
            headers=headers,
            case_name=case["name"],
            log_level="none"
        )
        print_response(res)

        self._assert_and_report(case, res)


class TestGr07DeleteGroup(_GroupHelpers):
    """DELETE /api/monitor/groups/{id} — 删除分组（消费 {{three_id}}，只删三级）"""

    @pytest.mark.parametrize("case", _TEST_DATA["delete_group_cases"])
    def test_delete_group(self, base_url, auth_headers, case):
        """删除分组"""
        group_id = resolve_extract_value(case.get("groupId"), required=True)
        url = f"{base_url}/api/monitor/groups/{group_id}"
        headers = {**auth_headers}

        sep(f" 测试用例: {case['name']}")
        print_request("DELETE", url, headers=headers)
        res = http.send_request(
            "delete", url,
            headers=headers,
            case_name=case["name"],
            log_level="none"
        )
        print_response(res)

        self._assert_and_report(case, res)
