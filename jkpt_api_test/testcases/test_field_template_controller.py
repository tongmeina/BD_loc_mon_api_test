# testcases/test_field_template_controller.py
# 字段模板管理接口 — S3 拆类范式（一接口一 TestClass，allure 按接口分组）
#
# 类序即执行序：List → Add → Update → SaveFields → Delete
# 依赖声明（extract 链）：
#   TestFt02FieldTemplateAdd    正向提取 field_template_id → extract.yaml
#   TestFt03/04/05              消费 {{field_template_id}}（编辑名/存字段/删模板）
# YAML 映射：list_field_templates_cases→TestFt01 / add_field_template_cases→TestFt02
#           update_field_template_cases→TestFt03 / save_fields_cases→TestFt04
#           delete_field_template_cases→TestFt05
import jsonpath
import pytest
import time
from common.requests_util import BaseRequest
from common.yaml_util import read_yaml, write_yaml, resolve_extract_value, is_extract_placeholder
from common.logger_util import sep, print_request, print_response
from common.case_report_util import assert_response

_jsonpath_parse = jsonpath.jsonpath
http = BaseRequest()

_TEST_DATA = read_yaml("./yaml/test_field_template_controller.yaml")


class _FieldTemplateHelpers:
    """不被 pytest 收集；供 5 个接口类复用断言/取名。"""

    @staticmethod
    def _resolve_template_name(raw):
        name = raw or ""
        if isinstance(name, str) and "{int(time.time())}" in name:
            name = name.replace("{int(time.time())}", str(int(time.time())))
        return name

    def _assert_and_report(self, case, response, biz_context=None):
        return assert_response(
            case,
            response,
            biz_context=biz_context or {"请求用例": case["name"]},
        )


class TestFt01FieldTemplateList(_FieldTemplateHelpers):
    """GET /api/monitor/field-templates — 获取字段模板列表"""

    @pytest.mark.parametrize("case", _TEST_DATA["list_field_templates_cases"])
    def test_list_field_templates(self, base_url, auth_headers, case):
        """获取字段模板列表"""
        url = f"{base_url}/api/monitor/field-templates"
        headers = {} if case.get("no_auth") else {**auth_headers}

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
        self._assert_and_report(case, res)


class TestFt02FieldTemplateAdd(_FieldTemplateHelpers):
    """POST /api/monitor/field-templates — 新增字段模板（正向提取 field_template_id）"""

    @pytest.mark.parametrize("case", _TEST_DATA["add_field_template_cases"])
    def test_add_field_template(self, base_url, auth_headers, case):
        """新增模板；正向成功写入 extract.yaml 的 field_template_id"""
        url = f"{base_url}/api/monitor/field-templates"
        headers = {**auth_headers}
        tname = self._resolve_template_name(case.get("templateName"))

        params = {"name": tname}

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
        json_data = self._assert_and_report(
            case,
            res,
            biz_context={"请求参数": params},
        )
        code = json_data["code"]
        if code == 0 and case.get("name") == "字段模板-创建-正向":
            tid = _jsonpath_parse(json_data, "$.data.id")
            if tid:
                write_yaml("./extract.yaml", {"field_template_id": tid[0]}, mode="append")


class TestFt03FieldTemplateUpdate(_FieldTemplateHelpers):
    """PUT /api/monitor/field-templates/{id} — 编辑模板名称（消费 {{field_template_id}}）"""

    @pytest.mark.parametrize("case", _TEST_DATA["update_field_template_cases"])
    def test_update_field_template(self, base_url, auth_headers, case):
        """修改模板名称（query: name）"""
        raw_id = case.get("templateId")
        tid = resolve_extract_value(raw_id, required=is_extract_placeholder(raw_id))
        url = f"{base_url}/api/monitor/field-templates/{tid}"
        headers = {**auth_headers}
        tname = self._resolve_template_name(case.get("templateName"))

        params = {"name": tname}

        sep(f" 测试用例: {case['name']}")
        print_request("PUT", url, params=params, headers=headers)
        res = http.send_request(
            "put",
            url,
            params=params,
            headers=headers,
            case_name=case["name"],
            log_level="none",
        )
        print_response(res)
        self._assert_and_report(case, res)


class TestFt04FieldTemplateSaveFields(_FieldTemplateHelpers):
    """POST /api/monitor/field-templates/{id}/fields — 保存模板字段名列表（消费 {{field_template_id}}）"""

    @pytest.mark.parametrize("case", _TEST_DATA["save_fields_cases"])
    def test_save_fields(self, base_url, auth_headers, case):
        """写入/覆盖该模板下字段名（query: fields）；非删模板"""
        raw_id = case.get("templateId")
        tid = resolve_extract_value(raw_id, required=is_extract_placeholder(raw_id))
        url = f"{base_url}/api/monitor/field-templates/{tid}/fields"
        headers = {**auth_headers}

        if case.get("omit_fields_query"):
            req_params = None
            log_params = {}
        else:
            fields = case.get("fields") or []
            req_params = [("fields", f) for f in fields]
            log_params = {"fields": fields}

        sep(f" 测试用例: {case['name']}")
        print_request("POST", url, params=log_params, headers=headers)
        res = http.send_request(
            "post",
            url,
            params=req_params,
            headers=headers,
            case_name=case["name"],
            log_level="none",
        )
        print_response(res)
        self._assert_and_report(case, res)


class TestFt05FieldTemplateDelete(_FieldTemplateHelpers):
    """DELETE /api/monitor/field-templates/{id} — 删除字段模板（消费 {{field_template_id}}）"""

    @pytest.mark.parametrize("case", _TEST_DATA["delete_field_template_cases"])
    def test_delete_field_template(self, base_url, auth_headers, case):
        """删除整张模板；非 /fields 保存、非删单个字段名接口"""
        raw_id = case.get("templateId")
        tid = resolve_extract_value(raw_id, required=is_extract_placeholder(raw_id))
        url = f"{base_url}/api/monitor/field-templates/{tid}"
        headers = {**auth_headers}

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
