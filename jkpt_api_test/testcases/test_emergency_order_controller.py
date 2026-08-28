# testcases/test_emergency_order_controller.py
# 应急套餐订单 — page / detail / cancel / delete
# 计划：plan/emergency-combo-order-tests.plan.md §5（2026-08-18 探针）
# lifecycle 单 helper 自造，Eo03 cancel → Eo04 delete；禁止 register_unpaid_order_no
# buy 限频走 common.buy_cooldown_util（与商城/星豆共享钟）

import jsonpath
import pytest

from common.buy_cooldown_util import mark_bought, wait_buy_cooldown
from common.case_report_util import assert_response
from common.logger_util import key, print_request, print_response, sep
from common.requests_util import BaseRequest, parse_response_json
from common.yaml_util import (
    is_extract_placeholder,
    read_yaml,
    resolve_extract_value,
    write_yaml,
)

_jsonpath_parse = jsonpath.jsonpath
http = BaseRequest()
_TEST_DATA = read_yaml("./yaml/test_emergency_order_controller.yaml")
_PAGE_EXTRACTED = False
_COMBO_LIFECYCLE_BOUGHT = False
_STAR_BEAN_LIFECYCLE_BOUGHT = False


def _jp_first(data, expr):
    found = _jsonpath_parse(data, expr)
    if found:
        return found[0]
    return None


def _page_items(json_data):
    data = json_data.get("data")
    if not isinstance(data, dict):
        return []
    items = data.get("items")
    return items if isinstance(items, list) else []


class _EoHelpers:
    """共享逻辑；不以 Test 开头，pytest 不收集。"""

    @staticmethod
    def resolve_addr(raw, rescue_sat_terminal):
        if isinstance(raw, str) and raw.strip() == "{{rescue_sat_terminal}}":
            return rescue_sat_terminal
        return raw

    @staticmethod
    def _headers(auth_headers, case):
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}
        return headers

    @staticmethod
    def resolve_order_no(raw, required=False):
        if is_extract_placeholder(raw):
            return resolve_extract_value(raw, required=required)
        return raw

    def _post_buy(self, url, *, json, headers, case_name):
        wait_buy_cooldown()
        try:
            res = http.send_request(
                "post", url, json=json, headers=headers,
                case_name=case_name, log_level="none",
            )
            return parse_response_json(res, context=case_name)
        finally:
            mark_bought()

    @staticmethod
    def _pick_daily_combo(mall_json):
        dailies = _jp_first(mall_json, "$.data.dailyPackages") or []
        priced = [
            p for p in dailies
            if isinstance(p, dict) and p.get("id") is not None
            and isinstance(p.get("price"), (int, float))
        ]
        if not priced:
            return None
        priced.sort(key=lambda p: p["price"])
        return priced[0]

    def ensure_lifecycle_order(self, base_url, auth_headers, rescue_sat_terminal):
        global _COMBO_LIFECYCLE_BOUGHT
        existing = resolve_extract_value("{{eo_lifecycle_order_no}}", required=False)
        if existing or _COMBO_LIFECYCLE_BOUGHT:
            return
        combo_id = resolve_extract_value("{{combo_mall_id}}", required=False)
        if combo_id is None:
            mall_url = f"{base_url}/api/monitor/emergency/combo/mall"
            params = {"packageType": "COMBINATION", "terminalType": "TT_RESCUE_STICK"}
            res = http.send_request(
                "get", mall_url, params=params, headers=auth_headers,
                case_name="lifecycle-mall", log_level="none",
            )
            mall_json = parse_response_json(res, context="lifecycle-mall")
            if mall_json["code"] != 0:
                pytest.skip(f"lifecycle GET mall 失败: {mall_json}")
            chosen = self._pick_daily_combo(mall_json)
            if not chosen:
                pytest.skip("无救援棒日包，无法造套餐生命周期单")
            combo_id = chosen["id"]
        url = f"{base_url}/api/monitor/emergency/combo/buy"
        body = {
            "terminalType": "TT_RESCUE_STICK",
            "addrs": [rescue_sat_terminal],
            "emergencyComboId": combo_id,
        }
        json_data = self._post_buy(
            url, json=body, headers=auth_headers, case_name="lifecycle-combo-buy",
        )
        code = json_data["code"]
        if code == 999:
            json_data = self._post_buy(
                url, json=body, headers=auth_headers, case_name="lifecycle-combo-buy-retry",
            )
            code = json_data["code"]
        if code == 999:
            pytest.skip(f"套餐 lifecycle buy 过于频繁: {json_data.get('msg')}")
        if code != 0:
            pytest.skip(f"套餐 lifecycle buy 失败: {json_data}")
        order_no = _jp_first(json_data, "$.data.orderNo")
        if not order_no:
            pytest.skip("套餐 lifecycle buy 未返回 orderNo")
        write_yaml("./extract.yaml", {"eo_lifecycle_order_no": order_no}, mode="append")
        _COMBO_LIFECYCLE_BOUGHT = True
        key("extract eo_lifecycle_order_no", order_no)

    def ensure_lifecycle_star_bean_order(self, base_url, auth_headers):
        global _STAR_BEAN_LIFECYCLE_BOUGHT
        existing = resolve_extract_value("{{eo_lifecycle_star_bean_order_no}}", required=False)
        if existing or _STAR_BEAN_LIFECYCLE_BOUGHT:
            return
        url = f"{base_url}/api/monitor/star-bean/buy"
        body = {"amount": 1}
        json_data = self._post_buy(
            url, json=body, headers=auth_headers, case_name="lifecycle-star-bean-buy",
        )
        code = json_data["code"]
        if code == 999:
            json_data = self._post_buy(
                url, json=body, headers=auth_headers,
                case_name="lifecycle-star-bean-buy-retry",
            )
            code = json_data["code"]
        if code == 999:
            pytest.skip(f"星豆 lifecycle buy 过于频繁: {json_data.get('msg')}")
        if code != 0:
            pytest.skip(f"星豆 lifecycle buy 失败: {json_data}")
        order_no = _jp_first(json_data, "$.data.orderNo")
        if not order_no:
            pytest.skip("星豆 lifecycle buy 未返回 orderNo")
        write_yaml(
            "./extract.yaml",
            {"eo_lifecycle_star_bean_order_no": order_no},
            mode="append",
        )
        _STAR_BEAN_LIFECYCLE_BOUGHT = True
        key("extract eo_lifecycle_star_bean_order_no", order_no)


class TestEo01Page(_EoHelpers):
    """GET /api/monitor/order/page"""

    @pytest.mark.parametrize("case", _TEST_DATA["emergency_order_page_cases"])
    def test_order_page(self, base_url, auth_headers, case):
        url = f"{base_url}/api/monitor/order/page"
        headers = self._headers(auth_headers, case)
        params = {}
        for key_name in ("orderStatus", "page", "pageSize"):
            if key_name in case:
                params[key_name] = case[key_name]
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
            items = _page_items(json_data)
            assert isinstance(json_data.get("data"), dict), f"[{case['name']}] data 不是 dict"
            assert isinstance(items, list), f"[{case['name']}] $.data.items 不是 list"
            want_status = case.get("orderStatus")
            if want_status and items:
                bad = [it for it in items if it.get("orderStatus") != want_status]
                assert not bad, f"[{case['name']}] 状态过滤不严: {bad[:3]}"
            self._maybe_extract_page_order(case, json_data, items)

    @staticmethod
    def _maybe_extract_page_order(case, json_data, items):
        global _PAGE_EXTRACTED
        if _PAGE_EXTRACTED:
            return
        if case.get("orderStatus") != "UNPAID":
            return
        if json_data["code"] != 0 or not items:
            return
        combo = [it for it in items if it.get("productType") == "COMMUNICATION_COMBO"]
        chosen = combo[0] if combo else items[0]
        order_no = chosen.get("orderNo")
        if not order_no:
            return
        write_yaml("./extract.yaml", {"eo_page_order_no": order_no}, mode="append")
        _PAGE_EXTRACTED = True
        key("extract eo_page_order_no", order_no)


class TestEo02Detail(_EoHelpers):
    """GET /api/monitor/order/detail"""

    @pytest.mark.parametrize("case", _TEST_DATA["emergency_order_detail_cases"])
    def test_order_detail(self, base_url, auth_headers, case):
        url = f"{base_url}/api/monitor/order/detail"
        headers = self._headers(auth_headers, case)
        raw_no = case.get("orderNo")
        params = {}
        if "orderNo" in case:
            params["orderNo"] = self.resolve_order_no(
                raw_no, required=is_extract_placeholder(raw_no),
            )
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
            assert data.get("orderNo") == params.get("orderNo"), (
                f"[{case['name']}] orderNo 不一致: {data.get('orderNo')}"
            )
            assert data.get("orderStatus"), f"[{case['name']}] 缺 orderStatus"
            if raw_no == "{{combo_order_no}}":
                assert data.get("orderStatus") == "UNPAID", (
                    f"[{case['name']}] 商城单应为 UNPAID: {data.get('orderStatus')}"
                )
                if data.get("productType"):
                    assert data["productType"] == "COMMUNICATION_COMBO", (
                        f"[{case['name']}] productType={data.get('productType')}"
                    )
            expire = data.get("orderExpireTime")
            assert expire, f"[{case['name']}] 缺 orderExpireTime"
            combos = data.get("emergencyUserCombo")
            if combos:
                assert combos[0].get("addr"), f"[{case['name']}] emergencyUserCombo[0].addr 空"


class TestEo03Cancel(_EoHelpers):
    """POST /api/monitor/order/cancel"""

    @pytest.mark.parametrize("case", _TEST_DATA["emergency_order_cancel_cases"])
    def test_order_cancel(self, base_url, auth_headers, rescue_sat_terminal, case):
        raw_no = case.get("orderNo")
        if raw_no == "{{eo_lifecycle_order_no}}" and not case.get("no_auth"):
            if case["expected"]["code"] == 0:
                self.ensure_lifecycle_order(base_url, auth_headers, rescue_sat_terminal)
        if raw_no == "{{eo_lifecycle_star_bean_order_no}}" and case["expected"]["code"] == 0:
            self.ensure_lifecycle_star_bean_order(base_url, auth_headers)

        url = f"{base_url}/api/monitor/order/cancel"
        headers = self._headers(auth_headers, case)
        params = {}
        if "orderNo" in case:
            params["orderNo"] = self.resolve_order_no(
                raw_no, required=is_extract_placeholder(raw_no),
            )
        sep(f" 测试用例: {case['name']}")
        print_request("POST", url, params=params, headers=headers)
        res = http.send_request(
            "post", url, params=params, headers=headers,
            case_name=case["name"], log_level="none",
        )
        print_response(res)
        json_data = assert_response(
            case,
            res,
            biz_context={"请求参数": params},
        )
        if json_data["code"] == 0 and params.get("orderNo"):
            self._assert_cancelled(base_url, auth_headers, params["orderNo"], case["name"])

    def _assert_cancelled(self, base_url, auth_headers, order_no, case_name):
        url = f"{base_url}/api/monitor/order/detail"
        params = {"orderNo": order_no}
        res = http.send_request(
            "get", url, params=params, headers=auth_headers,
            case_name=f"{case_name}-查取消后", log_level="none",
        )
        json_data = assert_response(
            {"name": f"{case_name}-查取消后", "expected": {"code": 0}},
            res,
            biz_context={"请求参数": params},
        )
        status = _jp_first(json_data, "$.data.orderStatus")
        assert status == "CANCELLED", f"[{case_name}] cancel 后 status={status}"
        key("cancel后状态", status)


class TestEo04Delete(_EoHelpers):
    """DELETE /api/monitor/order/delete — 删已取消的 lifecycle 单（未支付也可删，本批走 03 后删）"""

    @pytest.mark.parametrize("case", _TEST_DATA["emergency_order_delete_cases"])
    def test_order_delete(self, base_url, auth_headers, case):
        url = f"{base_url}/api/monitor/order/delete"
        headers = self._headers(auth_headers, case)
        raw_no = case.get("orderNo")
        params = {}
        if "orderNo" in case:
            params["orderNo"] = self.resolve_order_no(
                raw_no, required=is_extract_placeholder(raw_no),
            )
        sep(f" 测试用例: {case['name']}")
        print_request("DELETE", url, params=params, headers=headers)
        res = http.send_request(
            "delete", url, params=params, headers=headers,
            case_name=case["name"], log_level="none",
        )
        print_response(res)
        json_data = assert_response(
            case,
            res,
            biz_context={"请求参数": params},
        )
        if json_data["code"] == 0 and params.get("orderNo"):
            self._assert_gone(base_url, auth_headers, params["orderNo"], case["name"])

    def _assert_gone(self, base_url, auth_headers, order_no, case_name):
        url = f"{base_url}/api/monitor/order/detail"
        params = {"orderNo": order_no}
        res = http.send_request(
            "get", url, params=params, headers=auth_headers,
            case_name=f"{case_name}-查删除后", log_level="none",
        )
        json_data = assert_response(
            {"name": f"{case_name}-查删除后", "expected": {"code": 999}},
            res,
            biz_context={"请求参数": params},
        )
        key("delete后detail", f"code={json_data['code']} msg={json_data.get('msg')}")
