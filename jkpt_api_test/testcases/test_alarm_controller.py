# testcases/test_alarm_controller.py
# 报警管理接口 — S3 拆类范式（一接口一 TestClass，allure 按接口分组）
#
# 类序即执行序：Seed(造数) → List → History → Latest → Handle → BatchHandle → BatchHandleIds → BatchInfo
# 依赖声明：
#   TestAl00SeedProtocolAlarms  前置造数（bd 协议给 msg+bd 设备写报警，降低查询空数据概率）
#   TestAl04AlarmHandle         正向自提取 alarm_single_id（无需外部 extract 预置）
#   TestAl06AlarmBatchHandleIds 正向自提取 alarm_batch_ids（两设备最新报警合并去重）
#   其余查询类接口相互独立，均消费 msg_test_terminal 造数
# YAML 映射：alarm_list_cases→TestAl01 / alarm_history_cases→TestAl02 / alarm_latest_cases→TestAl03
#           alarm_handle_cases→TestAl04 / alarm_batch_handle_cases→TestAl05
#           alarm_batch_handle_ids_cases→TestAl06 / alarm_batch_info_cases→TestAl07
import time

import jsonpath
import requests
import pytest

from common.case_report_util import assert_response, report_extra_and_assert
from common.logger_util import key, print_request, print_response, sep
from common.requests_util import BaseRequest, parse_response_json
from common.yaml_util import read_yaml, write_yaml, resolve_extract_value

_jsonpath_parse = jsonpath.jsonpath
http = BaseRequest()

_TEST_DATA = read_yaml("./yaml/test_alarm_controller.yaml")


class _AlarmHelpers:
    """不被 pytest 收集；供 7 个接口类复用造数/查询/断言。"""

    # ---------- 辅助 ----------
    @staticmethod
    def _resolve_addr(yaml_value, msg_test_terminal):
        if isinstance(yaml_value, str) and yaml_value.strip() == "{{msg_test_terminal}}":
            return msg_test_terminal
        return yaml_value if yaml_value is not None else ""

    def _build_query_params(self, headers, addr, case):
        auth = headers.get("Authorization") or ""
        params = {"Authorization": auth, "addr": addr}
        alarm_type = case.get("alarm_type", case.get("alarmType"))
        if alarm_type is not None:
            params["alarmType"] = alarm_type
        self._add_pagination(params, case)
        return params

    @staticmethod
    def _build_pagination(headers, case):
        auth = headers.get("Authorization") or ""
        params = {"Authorization": auth}
        if "page" in case:
            params["page"] = case.get("page", 1)
        if "page_size" in case or "pageSize" in case:
            params["pageSize"] = case.get("page_size", case.get("pageSize", 100))
        return params

    @staticmethod
    def _add_pagination(params, case):
        if "page" in case:
            params["page"] = case.get("page", 1)
        if "page_size" in case or "pageSize" in case:
            params["pageSize"] = case.get("page_size", case.get("pageSize", 100))

    def _no_auth_headers(self, auth_headers):
        headers = {**auth_headers}
        return {k: v for k, v in headers.items() if k.lower() != "authorization"}

    @staticmethod
    def _seed_alarm_for_addr(bd_client, from_addr, case_name):
        # 13 报文可能按终端/秒去重；跨批次留出时间并使用唯一坐标。
        time.sleep(1.1)
        nonce = (time.time_ns() // 1_000_000) % 10000
        offset = nonce / 1_000_000
        r = bd_client.send_alarm_13(
            from_addr=from_addr,
            lon=113.466203 + offset,
            lat=23.170439 + offset,
            phone="13250703582",
            case_name=case_name,
        )
        if not r.success:
            pytest.fail(f"协议造数失败 from_addr={from_addr}: code={r.code}, msg={r.msg}")

    @staticmethod
    def _seed_alarm_for_two_terminals(bd_client, msg_addr, bd_addr, case_name):
        time.sleep(1.1)
        nonce = (time.time_ns() // 1_000_000) % 10000
        offset = nonce / 1_000_000
        r = bd_client.send_alarm_13_batch(
            from_addrs=[msg_addr, bd_addr],
            lon=113.466203 + offset,
            lat=23.170439 + offset,
            phone="13250703582",
            case_name=case_name,
        )
        if not r.success:
            pytest.fail(f"批量协议造数失败: code={r.code}, msg={r.msg}")

    @staticmethod
    def _get_alarm_json(url, params, headers, context):
        """报警查询遇到远端瞬断时允许一次重试，避免把传输抖动误判为业务失败。"""
        for attempt in range(2):
            try:
                response = http.send_request(
                    "get",
                    url,
                    params=params,
                    headers=headers,
                    case_name=context,
                    log_level="none",
                )
                return parse_response_json(response, context=context)
            except requests.exceptions.ConnectionError:
                if attempt == 1:
                    raise
                time.sleep(0.5)

    @staticmethod
    def _query_alarm_items(base_url, headers, addr, page=1, page_size=50):
        # 优先查 history 接口，按设备维度更稳定，返回的是 AlarmInfoRespDto 列表
        url = f"{base_url}/api/monitor/alarms/{addr}"
        params = {
            "Authorization": headers.get("Authorization") or "",
            "page": page,
            "pageSize": page_size,
        }
        data = _AlarmHelpers._get_alarm_json(
            url,
            params,
            headers,
            context=f"查询报警列表-{addr}",
        )
        items = _jsonpath_parse(data, "$.data.items[*]")
        if items:
            return items
        records = _jsonpath_parse(data, "$.data.records[*]")
        if records:
            return records
        data_list = _jsonpath_parse(data, "$.data[*]")
        if data_list:
            return data_list

        # 回退到 /alarms 查询：部分环境下历史接口短时可能查不到最新入库
        fallback_url = f"{base_url}/api/monitor/alarms"
        fallback_params = {
            "Authorization": headers.get("Authorization") or "",
            "addr": addr,
            "page": page,
            "pageSize": page_size,
        }
        d2 = _AlarmHelpers._get_alarm_json(
            fallback_url,
            fallback_params,
            headers,
            context=f"查询报警列表回退-{addr}",
        )
        items2 = _jsonpath_parse(d2, "$.data.items[*]")
        if items2:
            return items2
        records2 = _jsonpath_parse(d2, "$.data.records[*]")
        return records2 if records2 else []

    @staticmethod
    def _is_unhandled_alarm(item):
        """根据真实报警 DTO 判断未处理；无法判断时返回 None，禁止猜测。"""
        if not isinstance(item, dict):
            return None

        def state_from_value(value):
            if isinstance(value, bool):
                return not value
            if isinstance(value, int) and not isinstance(value, bool):
                return value == 0
            if isinstance(value, dict):
                for field_name in ("name", "value", "label", "status"):
                    if field_name in value:
                        state = state_from_value(value[field_name])
                        if state is not None:
                            return state
                return None
            if isinstance(value, str):
                normalized = value.strip().lower()
                compact = normalized.replace("_", "").replace("-", "")
                if any(marker in compact for marker in (
                    "unhandled", "unprocessed", "nothandle", "未处理", "new", "pending", "待处理", "unread"
                )):
                    return True
                if any(marker in compact for marker in (
                    "handled", "processed", "已处理", "done", "complete", "completed", "处理完"
                )):
                    return False
            return None

        for key_name in ("handleStatus", "status", "handled"):
            if key_name in item:
                state = state_from_value(item.get(key_name))
                if state is not None:
                    return state

        # AlarmInfoRespDto 使用 handleTimeStr；有处理时间即代表已处理。
        for key_name in ("handleTimeStr", "handleTime", "handledTime"):
            if key_name in item:
                value = item.get(key_name)
                if value not in (None, ""):
                    return False
                if value == "" and key_name == "handleTimeStr":
                    return True

        # 只有显式空字符串才能作为“未处理”辅助证据；None 代表未知。
        if "handleResult" in item:
            return True if item.get("handleResult") == "" else None
        return None

    def _extract_single_alarm_id_with_retry(
        self, base_url, headers, addr, bd_client, retry_seed_addr
    ):
        # 先查询 + 短轮询，再补造一次并重查，尽量降低异步入库导致的空ID概率
        for _ in range(3):
            items = self._query_alarm_items(base_url, headers, addr)
            ids = [i.get("id") for i in items if isinstance(i, dict) and i.get("id") is not None]
            unhandled_ids = [
                i.get("id")
                for i in items
                if isinstance(i, dict)
                and i.get("id") is not None
                and self._is_unhandled_alarm(i)
            ]
            if unhandled_ids:
                return unhandled_ids[0]
            if ids:
                return ids[0]
            latest_id = self._query_latest_alarm_id(base_url, headers, addr)
            if latest_id is not None:
                return latest_id
            global_ids = self._query_global_alarm_ids(base_url, headers)
            if global_ids:
                return global_ids[0]
            time.sleep(0.8)

        self._seed_alarm_for_addr(
            bd_client=bd_client,
            from_addr=retry_seed_addr,
            case_name="单条处理-兜底补造",
        )
        items = self._query_alarm_items(base_url, headers, addr)
        ids = [i.get("id") for i in items if isinstance(i, dict) and i.get("id") is not None]
        if not ids:
            latest_id = self._query_latest_alarm_id(base_url, headers, addr)
            if latest_id is not None:
                return latest_id
            global_ids = self._query_global_alarm_ids(base_url, headers)
            if global_ids:
                return global_ids[0]
        if not ids:
            pytest.fail("alarms/{id} 无法提取报警ID（补造后仍为空）")
        return ids[0]

    @staticmethod
    def _query_latest_alarm_data(base_url, headers, addr):
        url = f"{base_url}/api/monitor/alarms/latest/{addr}"
        data = _AlarmHelpers._get_alarm_json(
            url,
            None,
            headers,
            context=f"查询最新报警-{addr}",
        )
        latest = data.get("data")
        return latest if isinstance(latest, dict) else None

    @staticmethod
    def _query_latest_alarm_id(base_url, headers, addr):
        latest = _AlarmHelpers._query_latest_alarm_data(base_url, headers, addr)
        if latest is not None and latest.get("id") not in (None, ""):
            return latest["id"]
        if latest is None:
            return None
        direct = _jsonpath_parse(latest, "$.id")
        if direct:
            return direct[0]
        deep = _jsonpath_parse(latest, "$..id")
        if not deep:
            return None
        for v in deep:
            if isinstance(v, (int, str)) and str(v).strip():
                return v
        return None

    @staticmethod
    def _query_global_alarm_ids(base_url, headers):
        url = f"{base_url}/api/monitor/alarms"
        params = {
            "Authorization": headers.get("Authorization") or "",
            "page": 1,
            "pageSize": 50,
        }
        r = http.send_request(
            "get",
            url,
            params=params,
            headers=headers,
            case_name="查询全局报警列表兜底",
            log_level="none",
        )
        data = parse_response_json(r, context="查询全局报警列表兜底")
        ids = _jsonpath_parse(data, "$.data.items[*].id")
        if ids:
            return ids
        ids = _jsonpath_parse(data, "$.data.records[*].id")
        if ids:
            return ids
        return []

    def _extract_batch_alarm_ids_with_retry(
        self, base_url, headers, addr, need_count, bd_client, msg_addr, bd_addr
    ):
        def collect_unhandled_ids():
            # 批量场景从 msg/bd 两设备合并收集，去重后取未处理ID
            msg_items = self._query_alarm_items(base_url, headers, msg_addr)
            bd_items = self._query_alarm_items(base_url, headers, bd_addr)
            merged = []
            seen = set()
            for i in [*msg_items, *bd_items]:
                if not isinstance(i, dict):
                    continue
                _id = i.get("id")
                if _id is None or _id in seen:
                    continue
                seen.add(_id)
                if self._is_unhandled_alarm(i):
                    merged.append(_id)
            return merged

        for _ in range(3):
            unhandled_ids = collect_unhandled_ids()
            if len(unhandled_ids) >= need_count:
                return unhandled_ids[:need_count]
            time.sleep(0.8)

        self._seed_alarm_for_two_terminals(
            bd_client=bd_client,
            msg_addr=msg_addr,
            bd_addr=bd_addr,
            case_name="批量处理-兜底补造",
        )
        ids = collect_unhandled_ids()
        if len(ids) < need_count:
            pytest.fail(f"batch-handle/ids 提取ID不足: 需要{need_count}条，实际{len(ids)}条")
        return ids[:need_count]

    def _wait_for_new_alarm_ids(
        self,
        base_url,
        headers,
        address,
        previous_ids,
        minimum_count=1,
        attempts=10,
        interval_seconds=1.0,
    ):
        previous_id_strings = {str(alarm_id) for alarm_id in previous_ids}
        for _ in range(attempts):
            items = self._query_alarm_items(base_url, headers, address)
            new_ids = [
                item.get("id")
                for item in items
                if isinstance(item, dict)
                and item.get("id") not in (None, "")
                and str(item.get("id")) not in previous_id_strings
            ]
            if len(new_ids) >= minimum_count:
                return new_ids
            # history 索引可能滞后；latest 接口先看到本轮唯一报警时也可作为 ID 证据。
            latest_id = self._query_latest_alarm_id(base_url, headers, address)
            if (
                latest_id is not None
                and str(latest_id) not in previous_id_strings
            ):
                return [latest_id]
            time.sleep(interval_seconds)
        pytest.fail(
            f"协议造数后未发现新报警ID: address={address}, "
            f"minimum_count={minimum_count}"
        )

    def _assert_and_report(self, case, response, biz_context=None):
        return assert_response(
            case,
            response,
            biz_context=biz_context or {"请求用例": case["name"]},
        )

    @staticmethod
    def _extract_page_items(json_data):
        data = json_data.get("data")
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return None
        for field_name in ("items", "records"):
            if field_name in data:
                return data[field_name]
        return None

    def _assert_page_structure(self, case, json_data):
        if case.get("scenario") != "positive":
            return
        items = self._extract_page_items(json_data)
        item_ids = [
            item.get("id")
            for item in items or []
            if isinstance(item, dict)
        ]
        report_extra_and_assert(
            "报警分页结构",
            [
                {
                    "项": "data 分页列表",
                    "期望": "list",
                    "实际": type(items).__name__,
                    "通过": isinstance(items, list),
                },
                {
                    "项": "报警记录 id",
                    "期望": "非空",
                    "实际": item_ids[:5],
                    "通过": bool(item_ids) and all(
                        item_id not in (None, "") for item_id in item_ids
                    ),
                },
            ],
            summary=f"分页结构有效，记录数={len(items or [])}",
        )

    @staticmethod
    def _assert_latest_structure(case, json_data):
        if case.get("scenario") != "positive":
            return
        latest_alarm = json_data.get("data")
        report_extra_and_assert(
            "最新报警结构",
            [
                {
                    "项": "data 类型",
                    "期望": "dict",
                    "实际": type(latest_alarm).__name__,
                    "通过": isinstance(latest_alarm, dict),
                },
                {
                    "项": "报警 id",
                    "期望": "非空",
                    "实际": latest_alarm.get("id") if isinstance(latest_alarm, dict) else None,
                    "通过": isinstance(latest_alarm, dict)
                    and latest_alarm.get("id") not in (None, ""),
                },
            ],
            summary="最新报警结构有效",
        )

    @staticmethod
    def _assert_batch_info_structure(case, json_data):
        if case.get("scenario") != "positive":
            return
        batch_info = json_data.get("data")
        report_extra_and_assert(
            "报警类型统计结构",
            [
                {
                    "项": "data 类型",
                    "期望": "list",
                    "实际": type(batch_info).__name__,
                    "通过": isinstance(batch_info, list),
                }
            ],
            summary=f"报警类型统计结构有效，类型数={len(batch_info or [])}",
        )

    def _find_alarm_by_id(self, base_url, headers, addresses, alarm_id):
        for address in addresses:
            for item in self._query_alarm_items(base_url, headers, address):
                if isinstance(item, dict) and str(item.get("id")) == str(alarm_id):
                    return item
            latest = self._query_latest_alarm_data(base_url, headers, address)
            if isinstance(latest, dict) and str(latest.get("id")) == str(alarm_id):
                return latest
        return None

    def _wait_for_unhandled_alarm(
        self,
        base_url,
        headers,
        addresses,
        alarm_id,
        attempts=6,
        interval_seconds=1.0,
    ):
        """处理前确认目标报警可判定为未处理，避免误处理历史记录。"""
        last_item = None
        last_state = None
        for attempt in range(1, attempts + 1):
            last_item = self._find_alarm_by_id(
                base_url,
                headers,
                addresses,
                alarm_id,
            )
            last_state = self._is_unhandled_alarm(last_item)
            if last_state is True:
                key("处理前状态轮询次数", attempt)
                return last_item
            if attempt < attempts:
                time.sleep(interval_seconds)
        report_extra_and_assert(
            "报警处理前置状态",
            [
                {
                    "项": "目标报警",
                    "期望": f"id={alarm_id} 可确认未处理",
                    "实际": {
                        "状态": last_state,
                        "记录": last_item,
                    },
                    "通过": False,
                }
            ],
            summary="报警处理前状态有效",
        )
        return None

    @staticmethod
    def _handled_evidence(item, expected_handle_result):
        if not isinstance(item, dict):
            return False, {"原因": "目标报警不存在"}
        handle_result = item.get("handleResult")
        handle_status = item.get("handleStatus")

        def handled_status(value):
            if isinstance(value, bool):
                return value
            if isinstance(value, int) and not isinstance(value, bool):
                return value > 0
            if isinstance(value, dict):
                for field_name in ("name", "value", "label", "status"):
                    if field_name in value:
                        result = handled_status(value[field_name])
                        if result is not None:
                            return result
                return None
            if isinstance(value, str):
                normalized = value.strip().lower()
                compact = normalized.replace("_", "").replace("-", "")
                if any(marker in compact for marker in (
                    "unhandled", "unprocessed", "nothandle", "未处理", "new", "pending", "待处理", "unread"
                )):
                    return False
                if any(marker in compact for marker in (
                    "handled", "processed", "已处理", "done", "complete", "completed", "处理完"
                )):
                    return True
            return None

        status_state = handled_status(handle_status)
        if status_state is True:
            return True, {
                "handleStatus": handle_status,
                "handleResult": handle_result,
            }
        if status_state is False:
            return False, {
                "handleStatus": handle_status,
                "handleResult": handle_result,
            }
        if item.get("handled") is True:
            return True, {"handled": True, "handleResult": handle_result}
        for key_name in ("handleTimeStr", "handleTime", "handledTime"):
            if item.get(key_name):
                return True, {
                    key_name: item.get(key_name),
                    "handleResult": handle_result,
                }

        # 仅当响应完全没有状态/时间字段时，才兼容以处理结果作为唯一证据。
        has_state_fields = any(
            key_name in item
            for key_name in ("handleStatus", "handled", "status", "handleTimeStr", "handleTime", "handledTime")
        )
        if (
            not has_state_fields
            and expected_handle_result
            and handle_result == expected_handle_result
        ):
            return True, {"handleResult": handle_result, "兼容证据": "无状态字段"}
        return False, {
            "handleStatus": handle_status,
            "handled": item.get("handled"),
            "handleTimeStr": item.get("handleTimeStr"),
            "handleResult": handle_result,
        }

    def _wait_for_handled_alarm(
        self,
        base_url,
        headers,
        addresses,
        alarm_id,
        expected_handle_result,
        attempts=6,
        interval_seconds=1.0,
    ):
        last_item = None
        last_evidence = {"原因": "尚未查询"}
        for attempt in range(1, attempts + 1):
            last_item = self._find_alarm_by_id(
                base_url,
                headers,
                addresses,
                alarm_id,
            )
            handled, last_evidence = self._handled_evidence(
                last_item,
                expected_handle_result,
            )
            if handled:
                key("后置验证轮询次数", attempt)
                return
            if attempt < attempts:
                time.sleep(interval_seconds)
        report_extra_and_assert(
            "报警处理后置状态",
            [
                {
                    "项": "目标报警",
                    "期望": f"id={alarm_id} 已处理",
                    "实际": last_evidence,
                    "通过": False,
                }
            ],
            summary="报警处理状态已落地",
        )


class TestAl00SeedProtocolAlarms(_AlarmHelpers):
    """前置造数：bd 协议给 msg+bd 设备写报警（非接口用例，降低后续查询空数据概率）"""

    def test_seed_protocol_alarms(
        self, bd_client, msg_test_terminal, bd_test_terminal, base_url
    ):
        """前置造数：先给 msg+bd 设备写入报警，减少后续查询空数据概率"""
        case_name = "报警前置造数-msg+bd"
        result = bd_client.send_alarm_13_batch(
            from_addrs=[msg_test_terminal, bd_test_terminal],
            phone="13250703582",
            case_name=case_name,
        )
        sep(f" 测试用例: {case_name}")
        print_request("POST", f"{base_url}/api/datas/bd", json=result.request_body)
        print_response_info = {
            "code": result.code,
            "msg": result.msg,
            "success": result.success,
            "status_code": result.status_code,
        }
        key("前置造数结果", str(print_response_info))
        assert result.success, f"前置造数失败：code={result.code}, msg={result.msg}"


class TestAl01AlarmList(_AlarmHelpers):
    """GET /api/monitor/alarms — 分页查询所有设备的报警信息"""

    @pytest.mark.parametrize("case", _TEST_DATA["alarm_list_cases"])
    def test_alarm_list(self, base_url, auth_headers, msg_test_terminal, case):
        """分页查询报警列表"""
        url = f"{base_url}/api/monitor/alarms"
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers = self._no_auth_headers(headers)

        addr = self._resolve_addr(case.get("addr"), msg_test_terminal)
        params = self._build_query_params(headers, addr, case)

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
        json_data = self._assert_and_report(
            case,
            res,
            biz_context={"请求参数": params},
        )
        self._assert_page_structure(case, json_data)


class TestAl02AlarmHistory(_AlarmHelpers):
    """GET /api/monitor/alarms/{addr} — 分页查询设备历史报警信息"""

    @pytest.mark.parametrize("case", _TEST_DATA["alarm_history_cases"])
    def test_alarm_history(self, base_url, auth_headers, msg_test_terminal, case):
        """查询设备历史报警"""
        addr = self._resolve_addr(case.get("addr"), msg_test_terminal)
        url = f"{base_url}/api/monitor/alarms/{addr}"
        headers = {**auth_headers}
        params = self._build_pagination(headers, case)

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
        json_data = self._assert_and_report(
            case,
            res,
            biz_context={"设备地址": addr, "请求参数": params},
        )
        self._assert_page_structure(case, json_data)


class TestAl03AlarmLatest(_AlarmHelpers):
    """GET /api/monitor/alarms/latest/{addr} — 获取最新一条报警"""

    @pytest.mark.parametrize("case", _TEST_DATA["alarm_latest_cases"])
    def test_alarm_latest(self, base_url, auth_headers, msg_test_terminal, case):
        """获取最新报警"""
        addr = self._resolve_addr(case.get("addr"), msg_test_terminal)
        url = f"{base_url}/api/monitor/alarms/latest/{addr}"
        headers = {**auth_headers}

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
            biz_context={"设备地址": addr},
        )
        self._assert_latest_structure(case, json_data)


class TestAl04AlarmHandle(_AlarmHelpers):
    """PUT /api/monitor/alarms/{id} — 处理报警（正向自提取 alarm_single_id）"""

    @pytest.mark.parametrize("case", _TEST_DATA["alarm_handle_cases"])
    def test_alarm_handle(
        self, base_url, auth_headers, bd_client, msg_test_terminal, case
    ):
        """处理报警"""
        handle_result = case.get("handle_result", case.get("handleResult", ""))
        headers = {**auth_headers}

        if case.get("scenario") == "positive":
            existing_ids = [
                item.get("id")
                for item in self._query_alarm_items(
                    base_url,
                    headers,
                    msg_test_terminal,
                )
                if isinstance(item, dict) and item.get("id") not in (None, "")
            ]
            self._seed_alarm_for_addr(
                bd_client=bd_client,
                from_addr=msg_test_terminal,
                case_name=f"{case['name']}-seed",
            )
            alarm_id = self._wait_for_new_alarm_ids(
                base_url,
                headers,
                msg_test_terminal,
                existing_ids,
            )[0]
            write_yaml("./extract.yaml", {"alarm_single_id": alarm_id}, mode="append")
            alarm_id = resolve_extract_value("{{alarm_single_id}}", required=True)
        else:
            alarm_id = resolve_extract_value(case.get("id"), required=True)

        if case.get("scenario") == "positive":
            self._wait_for_unhandled_alarm(
                base_url,
                headers,
                [msg_test_terminal],
                alarm_id,
            )

        url = f"{base_url}/api/monitor/alarms/{alarm_id}"
        params = {"handleResult": handle_result}

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
        self._assert_and_report(
            case,
            res,
            biz_context={"报警 ID": alarm_id, "处理结果": handle_result},
        )
        if case.get("scenario") == "positive":
            self._wait_for_handled_alarm(
                base_url,
                headers,
                [msg_test_terminal],
                alarm_id,
                handle_result,
            )


class TestAl05AlarmBatchHandle(_AlarmHelpers):
    """PUT /api/monitor/alarms/batch-handle — 按类型批量处理报警"""

    @pytest.mark.parametrize("case", _TEST_DATA["alarm_batch_handle_cases"])
    def test_alarm_batch_handle(
        self, base_url, auth_headers, bd_client, msg_test_terminal, case
    ):
        """按类型批量处理报警"""
        url = f"{base_url}/api/monitor/alarms/batch-handle"
        headers = {**auth_headers}
        alarm_type = case.get("alarmTypes", "")
        handle_result = case.get("handle_result", case.get("handleResult", "批量已处理"))

        target_alarm_ids = []
        if case.get("scenario") == "positive":
            existing_ids = [
                item.get("id")
                for item in self._query_alarm_items(
                    base_url,
                    headers,
                    msg_test_terminal,
                )
                if isinstance(item, dict) and item.get("id") not in (None, "")
            ]
            self._seed_alarm_for_addr(
                bd_client=bd_client,
                from_addr=msg_test_terminal,
                case_name=f"{case['name']}-seed",
            )
            target_alarm_ids = self._wait_for_new_alarm_ids(
                base_url,
                headers,
                msg_test_terminal,
                existing_ids,
            )
            for target_alarm_id in target_alarm_ids:
                self._wait_for_unhandled_alarm(
                    base_url,
                    headers,
                    [msg_test_terminal],
                    target_alarm_id,
                )

        body = {"alarmTypes": alarm_type, "handleResult": handle_result}

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
        self._assert_and_report(
            case,
            res,
            biz_context={"报警类型": alarm_type, "处理结果": handle_result},
        )
        if case.get("scenario") == "positive":
            for target_alarm_id in target_alarm_ids:
                self._wait_for_handled_alarm(
                    base_url,
                    headers,
                    [msg_test_terminal],
                    target_alarm_id,
                    handle_result,
                )


class TestAl06AlarmBatchHandleIds(_AlarmHelpers):
    """PUT /api/monitor/alarms/batch-handle/ids — 按 ID 批量处理（正向自提取 alarm_batch_ids）"""

    @pytest.mark.parametrize("case", _TEST_DATA["alarm_batch_handle_ids_cases"])
    def test_alarm_batch_handle_ids(
        self, base_url, auth_headers, bd_client, msg_test_terminal, bd_test_terminal, case
    ):
        """按 ID 批量处理报警"""
        url = f"{base_url}/api/monitor/alarms/batch-handle/ids"
        headers = {**auth_headers}
        handle_result = case.get("handle_result", case.get("handleResult", "批量已处理"))

        if case.get("scenario") == "positive":
            existing_msg_ids = [
                item.get("id")
                for item in self._query_alarm_items(
                    base_url,
                    headers,
                    msg_test_terminal,
                )
                if isinstance(item, dict) and item.get("id") not in (None, "")
            ]
            existing_bd_ids = [
                item.get("id")
                for item in self._query_alarm_items(
                    base_url,
                    headers,
                    bd_test_terminal,
                )
                if isinstance(item, dict) and item.get("id") not in (None, "")
            ]
            self._seed_alarm_for_two_terminals(
                bd_client=bd_client,
                msg_addr=msg_test_terminal,
                bd_addr=bd_test_terminal,
                case_name=f"{case['name']}-seed-batch",
            )
            new_msg_ids = self._wait_for_new_alarm_ids(
                base_url,
                headers,
                msg_test_terminal,
                existing_msg_ids,
            )
            new_bd_ids = self._wait_for_new_alarm_ids(
                base_url,
                headers,
                bd_test_terminal,
                existing_bd_ids,
            )
            ids = [new_msg_ids[0], new_bd_ids[0]]
            if len({str(alarm_id) for alarm_id in ids}) < 2:
                ids = self._extract_batch_alarm_ids_with_retry(
                    base_url=base_url,
                    headers=headers,
                    addr=bd_test_terminal,
                    need_count=2,
                    bd_client=bd_client,
                    msg_addr=msg_test_terminal,
                    bd_addr=bd_test_terminal,
                )
            write_yaml("./extract.yaml", {"alarm_batch_ids": ids}, mode="append")
            ids = resolve_extract_value("{{alarm_batch_ids}}", required=True)
            if not isinstance(ids, list):
                pytest.fail(f"alarm_batch_ids 解析结果不是列表: {ids}")
            for target_alarm_id in ids[:2]:
                self._wait_for_unhandled_alarm(
                    base_url,
                    headers,
                    [msg_test_terminal, bd_test_terminal],
                    target_alarm_id,
                )
            # Apifox 契约：字段必须是 idStr（逗号拼接），不是 ids
            payload = {
                "idStr": ",".join([str(x) for x in ids[:2]]),
                "handleResult": handle_result,
            }
        else:
            raw_ids = case.get("ids", [])
            payload = {
                "idStr": ",".join([str(x) for x in raw_ids]) if isinstance(raw_ids, list) else str(raw_ids),
                "handleResult": handle_result,
            }

        sep(f" 测试用例: {case['name']}")
        print_request("PUT", url, json=payload, headers=headers)
        res = http.send_request(
            "put",
            url,
            json=payload,
            headers=headers,
            case_name=case["name"],
            log_level="none",
        )
        print_response(res)
        self._assert_and_report(
            case,
            res,
            biz_context={"请求体": payload},
        )
        if case.get("scenario") == "positive":
            for target_alarm_id in ids[:2]:
                self._wait_for_handled_alarm(
                    base_url,
                    headers,
                    [msg_test_terminal, bd_test_terminal],
                    target_alarm_id,
                    handle_result,
                )


class TestAl07AlarmBatchInfo(_AlarmHelpers):
    """GET /api/monitor/alarms/batch-info — 获取报警类型及设备数量"""

    @pytest.mark.parametrize("case", _TEST_DATA["alarm_batch_info_cases"])
    def test_alarm_batch_info(self, base_url, auth_headers, case):
        """获取报警类型统计"""
        url = f"{base_url}/api/monitor/alarms/batch-info"
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers = self._no_auth_headers(headers)

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
        self._assert_batch_info_structure(case, json_data)
