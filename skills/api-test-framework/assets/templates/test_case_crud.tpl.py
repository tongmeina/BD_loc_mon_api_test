"""
test_xxx.py — 多接口 + 有状态模板（模式B′）
适用: 同一文件多个接口；用 fixture + extract.yaml，不要单类切片。
从 api-test-framework Skill 生成

Allure Suites 四层：文件 → 类（最后一层文件夹）→ 方法 → parametrize 叶子。
一个 YAML *_cases ↔ 一个 Test0N* 类 ↔ 一个方法 ↔ 一次 parametrize("case", …)。
类名前缀 Test01/02/03 仅为排序占位，项目适配层可换成自己的字母表（不要照抄 TestEc）。
parametrize 不要 ids=；不要 @allure.title(case["name"])。
清理用 module fixture，不要只挂在最后一个 Test 类。
"""

import jsonpath
import pytest
import time
from common.case_report_util import assert_response
from common.requests_util import BaseRequest
from common.yaml_util import read_yaml, write_yaml, resolve_extract_value

_jsonpath_parse = jsonpath.jsonpath
http = BaseRequest()
_TEST_DATA = read_yaml("./yaml/test_xxx.yaml")
_first_id_extracted = False


class _XxxHelpers:
    """不以 Test 开头，pytest 不收集。"""

    def _headers(self, auth_headers, case):
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers.pop("Authorization", None)
        return headers


@pytest.fixture(scope="module", autouse=True)
def _cleanup_xxx(base_url, auth_headers):
    """module 级收尾：-k 跳过删除类时仍能跑。按项目替换为真实清理。"""
    yield
    # eid = resolve_extract_value("{{created_id}}", required=False)
    # if eid:
    #     http.send_request("delete", f"{base_url}/api/xxx/{eid}",
    #                       headers=auth_headers, case_name="teardown-del", log_level="none")


class Test01CreateXxx(_XxxHelpers):
    """POST /api/xxx — 创建；正向成功后写入 created_id（只写一次）"""

    @pytest.mark.parametrize("case", _TEST_DATA["create_xxx_cases"])
    def test_create(self, base_url, auth_headers, case):
        global _first_id_extracted
        name_field = case.get("name_field", "")
        if "{int(time.time())}" in str(name_field):
            name_field = name_field.replace("{int(time.time())}", str(int(time.time())))

        url = f"{base_url}/api/xxx"
        payload = {"field1": name_field}
        res = http.send_request(
            method="post", url=url, json=payload,
            headers=self._headers(auth_headers, case),
            case_name=case["name"], log_level="simple",
        )
        json_data = assert_response(
            case,
            res,
            biz_context={"请求参数": payload},
        )
        code = json_data["code"]

        if code == 0 and not _first_id_extracted:
            created_id = _jsonpath_parse(json_data, "$.data.id")
            if created_id:
                write_yaml("./extract.yaml", {"created_id": created_id[0]}, mode="append")
                _first_id_extracted = True


class Test02UpdateXxx(_XxxHelpers):
    """PUT /api/xxx/{id} — 编辑；消费 {{created_id}}"""

    @pytest.mark.parametrize("case", _TEST_DATA["update_xxx_cases"])
    def test_update(self, base_url, auth_headers, case, group_fixture):
        resource_id = resolve_extract_value(case.get("id"), required=False)
        if resource_id is None and "编辑成功" in case.get("name", ""):
            resource_id = resolve_extract_value("{{created_id}}", required=True)
        if "编辑非空资源" in case.get("name", "") and isinstance(group_fixture, dict):
            resource_id = group_fixture.get("one_id") or resource_id

        name_field = case.get("name_field", "")
        if "{int(time.time())}" in str(name_field):
            name_field = name_field.replace("{int(time.time())}", str(int(time.time())))

        url = f"{base_url}/api/xxx/{resource_id}"
        payload = {"id": resource_id, "field1": name_field}
        res = http.send_request(
            method="put", url=url, json=payload,
            headers=self._headers(auth_headers, case),
            case_name=case["name"], log_level="simple",
        )
        assert_response(
            case,
            res,
            biz_context={"请求参数": payload},
        )


class Test03DeleteXxx(_XxxHelpers):
    """DELETE /api/xxx/{id} — 删除断言；兜底删除仍走模块 _cleanup_xxx"""

    @pytest.mark.parametrize("case", _TEST_DATA["delete_xxx_cases"])
    def test_delete(self, base_url, auth_headers, case, group_fixture):
        case_name = case.get("name", "")
        resource_id = resolve_extract_value(case.get("id"), required=False)
        if "删除成功-资源为空" in case_name:
            resource_id = resolve_extract_value("{{created_id}}", required=True)
        elif "删除失败-资源非空" in case_name and isinstance(group_fixture, dict):
            resource_id = group_fixture.get("one_id") or resource_id
        if resource_id is None:
            pytest.skip("依赖的资源ID不存在，请先执行创建正向用例")

        url = f"{base_url}/api/xxx/{resource_id}"
        res = http.send_request(
            method="delete", url=url, params={"id": resource_id},
            headers=self._headers(auth_headers, case),
            case_name=case["name"], log_level="simple",
        )
        assert_response(
            case,
            res,
            biz_context={"请求参数": {"id": resource_id}},
        )
