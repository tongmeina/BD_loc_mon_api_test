# testcases/test_alarm_settings_controller.py
# 报警通知设置管理接口 — S3 拆类范式（一接口一 TestClass，allure 按接口分组）
#
# 类序即执行序：List → Edit（Edit 依赖 List 提取的 extract 键，见下）
# 依赖声明（extract 链）：
#   TestAs01AlarmSettingsList  正向提取 id + 四开关原值 → extract.yaml
#     alarm_setting_id / alarm_setting_original
#   TestAs02AlarmSettingsEdit  消费上述两键（快照→取反→断言→还原）
# YAML 映射：list_alarm_settings_cases → TestAs01 / edit_alarm_settings_cases → TestAs02
import jsonpath
import pytest
from common.requests_util import BaseRequest
from common.yaml_util import read_yaml, write_yaml, resolve_extract_value, is_extract_placeholder
from common.logger_util import sep, key, print_request, print_response
from common.case_report_util import assert_response

_jsonpath_parse = jsonpath.jsonpath
http = BaseRequest()

# 四开关字段名（与 AlarmSettingRespDto 对齐）
_SWITCH_FIELDS = ["alarmVoice", "emailNoti", "popupWindow", "smsNoti"]

_TEST_DATA = read_yaml("./yaml/test_alarm_settings_controller.yaml")


class _AlarmSettingsHelpers:
    """不被 pytest 收集；供接口类复用断言。"""

    def _assert_and_report(self, case, response, biz_context=None):
        return assert_response(
            case,
            response,
            biz_context=biz_context or {"请求用例": case["name"]},
        )


class TestAs01AlarmSettingsList(_AlarmSettingsHelpers):
    """GET /api/monitor/alarm-settings — 获取报警通知设置列表"""

    @pytest.mark.parametrize("case", _TEST_DATA["list_alarm_settings_cases"])
    def test_list_alarm_settings(self, base_url, auth_headers, case):
        """获取列表；正向提取 id + 四开关原值写入 extract.yaml"""
        url = f"{base_url}/api/monitor/alarm-settings"
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
        json_data = self._assert_and_report(
            case,
            res,
            biz_context={"请求地址": url, "请求头已脱敏": True},
        )
        code = json_data["code"]

        # 正向：提取 id + 四开关快照写入 extract.yaml（供 TestAs02 消费）
        if code == 0 and case.get("name") == "报警通知设置-列表-正向":
            items = _jsonpath_parse(json_data, "$.data[*]")
            if not items:
                pytest.fail("报警通知设置列表为空，无法继续编辑链路")
            first = items[0]
            sid = first.get("id")
            if sid:
                snapshot = {f: first.get(f) for f in _SWITCH_FIELDS}
                write_yaml(
                    "./extract.yaml",
                    {"alarm_setting_id": sid, "alarm_setting_original": snapshot},
                    mode="append",
                )
                key("alarm_setting_id", sid)
                key("四开关快照", snapshot)



class TestAs02AlarmSettingsEdit(_AlarmSettingsHelpers):
    """PUT /api/monitor/alarm-settings/{id} — 编辑报警通知设置

    依赖 TestAs01 提取的 {{alarm_setting_id}} / {{alarm_setting_original}}。
    正向：快照→取反→断言→还原。
    """

    @pytest.mark.parametrize("case", _TEST_DATA["edit_alarm_settings_cases"])
    def test_edit_alarm_settings(self, base_url, auth_headers, case):
        """编辑报警通知设置；正向：快照→取反→断言→还原"""
        raw_id = case.get("setting_id")
        tid = resolve_extract_value(raw_id, required=is_extract_placeholder(raw_id))

        headers = {} if case.get("no_auth") else {**auth_headers}

        # ---------- 取原始快照 ----------
        orig_snapshot = None
        if not case.get("no_auth") and not case.get("setting_id", "").startswith("0000"):
            try:
                extract_data = read_yaml("./extract.yaml")
                orig_snapshot = extract_data.get("alarm_setting_original")
            except Exception:
                orig_snapshot = None

        # ---------- 构造 params ----------
        omit_alarm_voice = case.get("omit_alarm_voice", False)
        omit_email_noti = case.get("omit_email_noti", False)

        params = {}
        for f in _SWITCH_FIELDS:
            if f == "alarmVoice" and omit_alarm_voice:
                continue
            if f == "emailNoti" and omit_email_noti:
                continue
            # 若有快照则取反，否则默认 true
            if orig_snapshot is not None:
                params[f] = not orig_snapshot.get(f)
            else:
                params[f] = True

        url = f"{base_url}/api/monitor/alarm-settings/{tid}"

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
        json_data = self._assert_and_report(
            case,
            res,
            biz_context={"请求参数": params},
        )
        code = json_data["code"]

        # ---------- 正向：还原 ----------
        if (
            code == 0
            and case.get("name") == "报警通知设置-编辑-正向"
            and orig_snapshot is not None
        ):
            restore_params = {f: orig_snapshot.get(f) for f in _SWITCH_FIELDS}
            sep(" 还原四开关 ")
            print_request("PUT", url, params=restore_params, headers=headers)
            restore_res = http.send_request(
                "put",
                url,
                params=restore_params,
                headers=headers,
                case_name="报警通知设置-编辑-正向-还原",
                log_level="none",
            )
            assert_response(
                {
                    "name": "报警通知设置-编辑-正向-还原",
                    "expected": {"code": 0},
                },
                restore_res,
                biz_context={"alarm_setting_id": tid, "还原参数": restore_params},
            )
            key("还原结果", "成功")
