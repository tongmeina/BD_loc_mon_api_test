"""
test_xxx.py — 简单无状态接口模板（模式A）
适用: 单个接口（登录、单查询）。同一文件多个接口时改用 test_case_crud.tpl.py 的多类骨架。
从 api-test-framework Skill 生成

Allure Suites：一类 = 一个报告分组单元。单接口可以只有 Test01*。
parametrize 不要传 ids=；YAML name 只给日志/附件，不是树标题。
"""

import pytest
from common.case_report_util import assert_response
from common.requests_util import BaseRequest
from common.yaml_util import read_yaml

_TEST_DATA = read_yaml("./yaml/test_xxx.yaml")
http = BaseRequest()


class Test01Xxx:
    """POST /api/your/endpoint — 单接口示例（类名补零便于 Suites 排序）"""

    @pytest.mark.parametrize("case", _TEST_DATA["xxx_cases"])
    def test_xxx(self, base_url, auth_headers, case):
        url = f"{base_url}/api/your/endpoint"
        payload = {
            "field1": case["field1"],
            "field2": case["field2"],
        }

        headers = {**auth_headers}
        if case.get("no_auth"):
            headers.pop("Authorization", None)

        res = http.send_request(
            method="post",
            url=url,
            params=payload,
            headers=headers,
            case_name=case["name"],
            log_level="simple",
        )

        json_data = assert_response(
            case,
            res,
            biz_context={"请求参数": payload},
        )
        # 继续按领域需要断言 json_data；不要重复解析 $.code/$.msg。
