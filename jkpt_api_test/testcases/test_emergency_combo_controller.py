# testcases/test_emergency_combo_controller.py
# 应急套餐商城 — S3 拆类（一接口一 TestClass）
#
# 类序：Mall → ComboInfo → Remaining → UsagePage → Buy
# extract：TestEcm01 正向日包写入 combo_mall_id / combo_mall_price（只写一次）
#           TestEcm02 无过滤写入 emergency_user_combo_id / emergency_user_combo_addr（只写一次）
#           TestEcm05 正向写入 combo_order_no（本文件不读）并登记待支付单
# YAML：emergency_combo_*_cases
# 计划：plan/emergency-combo-mall-tests.plan.md
import jsonpath
import pytest

from common.buy_cooldown_util import mark_bought, wait_buy_cooldown
from common.case_report_util import assert_response
from common.cleanup import register_unpaid_order_no
from common.logger_util import key, print_request, print_response, sep
from common.requests_util import BaseRequest
from common.yaml_util import (
    is_extract_placeholder,
    read_yaml,
    resolve_extract_value,
    write_yaml,
)

_jsonpath_parse = jsonpath.jsonpath
http = BaseRequest()
_TEST_DATA = read_yaml("./yaml/test_emergency_combo_controller.yaml")
_MALL_EXTRACTED = False
_INFO_COMBO_EXTRACTED = False


def _jp_first(data, expr):
    found = _jsonpath_parse(data, expr)
    if found:
        return found[0]
    return None


class _EcmHelpers:
    """共享逻辑；不以 Test 开头，pytest 不收集。"""

    @staticmethod
    def resolve_addr(raw, rescue_sat_terminal):
        if isinstance(raw, str) and raw.strip() == "{{rescue_sat_terminal}}":
            return rescue_sat_terminal
        return raw

    @staticmethod
    def resolve_addrs(raw_list, rescue_sat_terminal):
        if not isinstance(raw_list, list):
            return raw_list
        return [_EcmHelpers.resolve_addr(x, rescue_sat_terminal) for x in raw_list]

    @staticmethod
    def _headers(auth_headers, case):
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}
        return headers


class TestEcm01Mall(_EcmHelpers):
    """GET /emergency/combo/mall — 套餐商城列表"""

    @pytest.mark.parametrize("case", _TEST_DATA["emergency_combo_mall_cases"])
    def test_mall(self, base_url, auth_headers, case):
        url = f"{base_url}/api/monitor/emergency/combo/mall"
        headers = self._headers(auth_headers, case)
        params = {}
        if "packageType" in case:
            params["packageType"] = case["packageType"]
        if case.get("terminalType"):
            params["terminalType"] = case["terminalType"]

        sep(f" 测试用例: {case['name']}")
        print_request("GET", url, params=params, headers=headers)
        res = http.send_request(
            "get", url, params=params, headers=headers,
            case_name=case["name"], log_level="none",
        )
        print_response(res)
        json_data = assert_response(
            case,
            res,
            biz_context={"请求参数": params},
        )

        if json_data["code"] == 0 and not case.get("no_auth"):
            self._assert_mall_shape(case, json_data)
            self._maybe_write_mall_extract(case, json_data)


    @staticmethod
    def _assert_mall_shape(case, json_data):
        daily = _jp_first(json_data, "$.data.dailyPackages")
        monthly = _jp_first(json_data, "$.data.monthlyPackages")
        assert isinstance(daily, list), f"[{case['name']}] dailyPackages 不是 list: {type(daily)}"
        assert isinstance(monthly, list), f"[{case['name']}] monthlyPackages 不是 list: {type(monthly)}"
        for pkg in daily + monthly:
            if not pkg:
                continue
            assert pkg.get("id") is not None, f"[{case['name']}] 套餐缺 id"
            price = pkg.get("price")
            assert isinstance(price, (int, float)), f"[{case['name']}] price 非数字: {price!r}"
            assert price >= 0, f"[{case['name']}] price 为负: {price}"
            period = pkg.get("servicePeriod")
            assert period in (0, 1), f"[{case['name']}] servicePeriod 非法: {period}"

    @staticmethod
    def _maybe_write_mall_extract(case, json_data):
        global _MALL_EXTRACTED
        if _MALL_EXTRACTED:
            return
        if case.get("terminalType") != "TT_RESCUE_STICK":
            return
        dailies = _jp_first(json_data, "$.data.dailyPackages") or []
        priced = [
            p for p in dailies
            if isinstance(p, dict) and p.get("id") is not None and isinstance(p.get("price"), (int, float))
        ]
        if not priced:
            return
        priced.sort(key=lambda p: p["price"])
        chosen = priced[0]
        write_yaml(
            "./extract.yaml",
            {"combo_mall_id": chosen["id"], "combo_mall_price": chosen["price"]},
            mode="append",
        )
        _MALL_EXTRACTED = True
        key("extract combo_mall_id", chosen["id"])
        key("extract combo_mall_price", chosen["price"])


class TestEcm02ComboInfo(_EcmHelpers):
    """GET /emergency/combo/chat/item/info — 我的套餐信息（buy 之前，不验刚下的单）"""

    @pytest.mark.parametrize("case", _TEST_DATA["emergency_combo_info_cases"])
    def test_combo_info(self, base_url, auth_headers, rescue_sat_terminal, case):
        url = f"{base_url}/api/monitor/emergency/combo/chat/item/info"
        headers = self._headers(auth_headers, case)
        params = {}
        addr = _EcmHelpers.resolve_addr(case.get("addr"), rescue_sat_terminal)
        if addr:
            params["addr"] = addr
        if "status" in case:
            params["status"] = case["status"]

        sep(f" 测试用例: {case['name']}")
        print_request("GET", url, params=params, headers=headers)
        res = http.send_request(
            "get", url, params=params, headers=headers,
            case_name=case["name"], log_level="none",
        )
        print_response(res)
        json_data = assert_response(
            case,
            res,
            biz_context={"请求参数": params},
        )

        if json_data["code"] == 0 and not case.get("no_auth"):
            data = json_data.get("data")
            assert isinstance(data, list), f"[{case['name']}] data 不是 list: {type(data)}"
            if not data:
                key("账号无套餐记录", f"addr={params.get('addr', '')} status={params.get('status', '')}")
            elif addr:
                hit = [it for it in data if isinstance(it, dict) and it.get("addr") == addr]
                assert hit, f"[{case['name']}] 列表非空但没有 addr={addr}"
            if data and "status" in case:
                bad = [it.get("status") for it in data if isinstance(it, dict) and it.get("status") != case["status"]]
                assert not bad, f"[{case['name']}] 按 status={case['status']} 筛选仍出现 {bad[:5]}"
            self._maybe_write_info_extract(case, data)


    @staticmethod
    def _pick_latest_user_combo(items):
        candidates = [
            it for it in items
            if isinstance(it, dict) and it.get("emergencyUserComboId")
        ]
        if not candidates:
            return None
        in_use = [it for it in candidates if it.get("status") == 1]
        pool = in_use or candidates
        pool.sort(key=lambda it: it.get("activationTime") or "", reverse=True)
        return pool[0]

    @staticmethod
    def _maybe_write_info_extract(case, data):
        global _INFO_COMBO_EXTRACTED
        if _INFO_COMBO_EXTRACTED:
            return
        if case.get("addr") or "status" in case or case.get("no_auth"):
            return
        chosen = TestEcm02ComboInfo._pick_latest_user_combo(data)
        if not chosen:
            return
        combo_id = chosen["emergencyUserComboId"]
        combo_addr = chosen.get("addr") or ""
        write_yaml(
            "./extract.yaml",
            {
                "emergency_user_combo_id": combo_id,
                "emergency_user_combo_addr": combo_addr,
            },
            mode="append",
        )
        _INFO_COMBO_EXTRACTED = True
        key("extract emergency_user_combo_id", combo_id)
        key("extract emergency_user_combo_addr", combo_addr)
        key("extract combo status/activationTime", f"{chosen.get('status')} / {chosen.get('activationTime')}")


class TestEcm03Remaining(_EcmHelpers):
    """GET /emergency/combo/chat/item/remaining — 群聊套餐余量（不传 chatItemId）"""

    @pytest.mark.parametrize("case", _TEST_DATA["emergency_combo_remaining_cases"])
    def test_remaining(self, base_url, auth_headers, rescue_sat_terminal, case):
        url = f"{base_url}/api/monitor/emergency/combo/chat/item/remaining"
        headers = self._headers(auth_headers, case)
        params = {}
        addr = _EcmHelpers.resolve_addr(case.get("addr"), rescue_sat_terminal)
        if addr is not None:
            params["addr"] = addr

        sep(f" 测试用例: {case['name']}")
        print_request("GET", url, params=params, headers=headers)
        res = http.send_request(
            "get", url, params=params, headers=headers,
            case_name=case["name"], log_level="none",
        )
        print_response(res)
        json_data = assert_response(
            case,
            res,
            biz_context={"请求参数": params},
        )

        if json_data["code"] == 0 and not case.get("no_auth"):
            data = json_data.get("data") or {}
            assert isinstance(data, dict), f"[{case['name']}] data 不是对象: {type(data)}"
            for field in ("allRemainingVoiceNumber", "allRemainingPositionNumber", "latestInfo"):
                assert field in data, f"[{case['name']}] 缺字段 {field}"



class TestEcm04UsagePage(_EcmHelpers):
    """GET /emergency/combo/usage/page — 用量分页（真实 comboId 走 info extract）"""

    @pytest.mark.parametrize("case", _TEST_DATA["emergency_combo_usage_page_cases"])
    def test_usage_page(self, base_url, auth_headers, rescue_sat_terminal, case):
        url = f"{base_url}/api/monitor/emergency/combo/usage/page"
        headers = self._headers(auth_headers, case)
        params = {}
        addr = _EcmHelpers.resolve_addr(case.get("addr"), rescue_sat_terminal)
        if addr:
            params["addr"] = addr
        for key_name in ("page", "pageSize"):
            if key_name in case:
                params[key_name] = case[key_name]
        combo_id = case.get("emergencyUserComboId")
        if is_extract_placeholder(combo_id):
            combo_id = resolve_extract_value(combo_id, required=True)
        if combo_id is not None:
            params["emergencyUserComboId"] = combo_id

        sep(f" 测试用例: {case['name']}")
        print_request("GET", url, params=params, headers=headers)
        res = http.send_request(
            "get", url, params=params, headers=headers,
            case_name=case["name"], log_level="none",
        )
        print_response(res)
        json_data = assert_response(
            case,
            res,
            biz_context={"请求参数": params},
        )

        if json_data["code"] == 0 and not case.get("no_auth"):
            items = _jp_first(json_data, "$.data.items")
            assert isinstance(items, list), f"[{case['name']}] $.data.items 不是 list: {items!r}"
            if not items:
                key("用量明细空页", f"emergencyUserComboId={params.get('emergencyUserComboId', '')}")
            elif is_extract_placeholder(case.get("emergencyUserComboId")):
                expected_addr = resolve_extract_value("{{emergency_user_combo_addr}}", required=False)
                if expected_addr:
                    bad = [
                        it.get("addr") for it in items
                        if isinstance(it, dict) and it.get("addr") and it.get("addr") != expected_addr
                    ]
                    assert not bad, (
                        f"[{case['name']}] 按 comboId 筛选仍出现其它 addr: {bad[:5]}"
                    )



class TestEcm05Buy(_EcmHelpers):
    """POST /emergency/combo/buy — 只验待支付订单；不 payment、用例内不 cancel、不读 combo_order_no"""

    @pytest.mark.parametrize("case", _TEST_DATA["emergency_combo_buy_cases"])
    def test_buy(self, base_url, auth_headers, rescue_sat_terminal, case):
        url = f"{base_url}/api/monitor/emergency/combo/buy"
        headers = self._headers(auth_headers, case)
        addrs = _EcmHelpers.resolve_addrs(case.get("addrs"), rescue_sat_terminal)
        combo_id = case.get("emergencyComboId")
        if is_extract_placeholder(combo_id):
            combo_id = resolve_extract_value(combo_id, required=True)
        body = {"terminalType": case.get("terminalType") or "TT_RESCUE_STICK"}
        if addrs is not None:
            body["addrs"] = addrs
        if combo_id is not None:
            body["emergencyComboId"] = combo_id

        apply_cooldown = not case.get("no_auth") and bool(addrs)
        if apply_cooldown:
            wait_buy_cooldown()
        sep(f" 测试用例: {case['name']}")
        print_request("POST", url, json=body, headers=headers)
        try:
            res = http.send_request(
                "post", url, json=body, headers=headers,
                case_name=case["name"], log_level="none",
            )
            print_response(res)
        finally:
            if apply_cooldown:
                mark_bought()

        json_data = assert_response(
            case,
            res,
            biz_context={"请求参数": body},
        )
        if json_data["code"] == 0 and not case.get("no_auth"):
            order_no = _jp_first(json_data, "$.data.orderNo")
            assert order_no, f"[{case['name']}] 未返回 $.data.orderNo"
            write_yaml("./extract.yaml", {"combo_order_no": order_no}, mode="append")
            register_unpaid_order_no(order_no)
            key("extract combo_order_no", order_no)
            product_type = _jp_first(json_data, "$.data.productType")
            if product_type:
                assert product_type == "COMMUNICATION_COMBO", (
                    f"[{case['name']}] productType={product_type}"
                )
            pay = _jp_first(json_data, "$.data.payAmount")
            mall_price = resolve_extract_value("{{combo_mall_price}}", required=False)
            if mall_price is not None and pay is not None:
                assert abs(float(pay) - float(mall_price)) < 1e-9, (
                    f"[{case['name']}] payAmount={pay} != mall price={mall_price}"
                )
            self._assert_unpaid_visible(base_url, auth_headers, rescue_sat_terminal, case["name"])


    @staticmethod
    def _assert_unpaid_visible(base_url, auth_headers, sn, case_name):
        url = f"{base_url}/api/monitor/emergency/combo/chat/item/info"
        params = {"addr": sn, "status": 0}
        res = http.send_request(
            "get", url, params=params, headers=auth_headers,
            case_name=f"{case_name}-查未付款", log_level="none",
        )
        json_data = assert_response(
            {"name": f"{case_name}-查未付款", "expected": {"code": 0}},
            res,
            biz_context={"请求参数": params},
        )
        items = json_data.get("data") or []
        hit = [it for it in items if isinstance(it, dict) and it.get("addr") == sn and it.get("status") == 0]
        assert hit, f"[{case_name}] buy 后 info status=0 未见 addr={sn}"
        key("buy后未付款可见", f"addr={sn} count={len(hit)}")
