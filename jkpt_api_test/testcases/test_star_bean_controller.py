# testcases/test_star_bean_controller.py
# 星豆接口：Sb01 换算 / Sb02 套餐列表 / Sb03 充值下单 / Sb04 流水分页
# 计划：plan/star-bean-tests.plan.md；现网基线 §5（2026-08-18 实测）
# buy 限频：同账号连续下单触发 999，冷却钟见 common.buy_cooldown_util（与商城/订单共享）

import jsonpath
import pytest

from common.buy_cooldown_util import mark_bought, wait_buy_cooldown
from common.case_report_util import assert_response
from common.cleanup import register_unpaid_order_no
from common.requests_util import BaseRequest
from common.yaml_util import (
    is_extract_placeholder,
    read_yaml,
    resolve_extract_value,
    write_yaml,
)

_jsonpath_parse = jsonpath.jsonpath
_TEST_DATA = read_yaml("./yaml/test_star_bean_controller.yaml")


class _SbHelpers:
    """共享逻辑；不以 Test 开头，pytest 不收集。"""

    @staticmethod
    def build_headers(auth_headers, case):
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers.pop("Authorization", None)
        return headers


class TestSb01Calculate:
    """GET /api/monitor/star-bean/calculate — 自定义金额换算"""

    @pytest.mark.parametrize("case", _TEST_DATA["star_bean_calculate_cases"])
    def test_calculate(self, base_url, auth_headers, case):
        headers = _SbHelpers.build_headers(auth_headers, case)
        params = {}
        if "amount" in case:
            params["amount"] = case["amount"]
        res = BaseRequest().send_request(
            "get", f"{base_url}/api/monitor/star-bean/calculate",
            params=params, headers=headers,
            case_name=case["name"], log_level="none",
        )
        json_data = assert_response(
            case,
            res,
            biz_context={"请求参数": params},
        )
        code = json_data["code"]
        # 正向：结构 + 守恒公式（§5 实测 starBeans == amount × exchangeRatio）
        if code == 0:
            data = _jsonpath_parse(json_data, "$.data")[0]
            assert isinstance(data.get("starBeans"), int), f"starBeans 非 int: {data}"
            assert isinstance(data.get("exchangeRatio"), int), f"exchangeRatio 非 int: {data}"
            expected_beans = case["amount"] * data["exchangeRatio"]
            assert data["starBeans"] == expected_beans, (
                f"换算不守恒: starBeans={data['starBeans']} != {case['amount']} × "
                f"{data['exchangeRatio']} = {expected_beans}"
            )
            # 基线 case（amount=1）写换算比率，供 Sb03 联动断言
            if case.get("amount") == 1 and not resolve_extract_value(
                "{{sb_exchange_ratio}}", required=False
            ):
                write_yaml(
                    "./extract.yaml",
                    {"sb_exchange_ratio": data["exchangeRatio"]},
                    mode="append",
                )


class TestSb02PackageActive:
    """GET /api/monitor/star-bean/package/active — 星豆套餐列表（购买）"""

    @pytest.mark.parametrize("case", _TEST_DATA["star_bean_package_active_cases"])
    def test_package_active(self, base_url, auth_headers, case):
        headers = _SbHelpers.build_headers(auth_headers, case)
        res = BaseRequest().send_request(
            "get", f"{base_url}/api/monitor/star-bean/package/active",
            headers=headers,
            case_name=case["name"], log_level="none",
        )
        json_data = assert_response(case, res, biz_context={})
        code = json_data["code"]
        # 正向：结构校验 + extract 写入（空列表合法，仅锁 code）
        if code == 0:
            packages = _jsonpath_parse(json_data, "$.data[*]") or []
            for p in packages:
                assert p.get("id"), f"套餐缺 id: {p}"
                assert isinstance(p.get("price"), (int, float)) and p["price"] >= 0, \
                    f"price 非法（负价红线）: {p}"
                assert isinstance(p.get("beanCount"), int) and p["beanCount"] >= 0, \
                    f"beanCount 非法: {p}"
                assert p.get("status") in (0, 1), f"status 越界: {p}"
            # status==0 出现在购买列表 → 直接 fail（§5：现网全为 1，出现即口径变化）
            disabled = [p for p in packages if p.get("status") == 0]
            assert not disabled, f"已禁用套餐出现在购买列表（口径变化，需回填 §5）: {disabled}"
            # 只写一次：status==1 中 sort 最小者
            if packages and not resolve_extract_value(
                "{{star_bean_package_id}}", required=False
            ):
                active = [p for p in packages if p.get("status") == 1]
                if active:
                    chosen = min(active, key=lambda p: p.get("sort", 0))
                    write_yaml(
                        "./extract.yaml",
                        {
                            "star_bean_package_id": chosen["id"],
                            "star_bean_package_price": chosen["price"],
                            "star_bean_package_beans": chosen["beanCount"],
                        },
                        mode="append",
                    )


class TestSb03Buy:
    """POST /api/monitor/star-bean/buy — 星豆充值下单（只验下单，不支付不 cancel）"""

    @pytest.mark.parametrize("case", _TEST_DATA["star_bean_buy_cases"])
    def test_buy(self, base_url, auth_headers, case):
        headers = _SbHelpers.build_headers(auth_headers, case)
        body = {}
        if "amount" in case:
            body["amount"] = case["amount"]
        pkg = case.get("starBeanPackageId")
        if is_extract_placeholder(pkg):
            pkg = resolve_extract_value(pkg, required=True)
        if pkg is not None:
            body["starBeanPackageId"] = pkg
        apply_cooldown = not case.get("no_auth")
        if apply_cooldown:
            wait_buy_cooldown()
        try:
            res = BaseRequest().send_request(
                "post", f"{base_url}/api/monitor/star-bean/buy",
                json=body, headers=headers,
                case_name=case["name"], log_level="none",
            )
            json_data = assert_response(
                case,
                res,
                biz_context={"请求参数": body},
            )
            code = json_data["code"]
            if code != 0:
                return
            data = _jsonpath_parse(json_data, "$.data")[0]

            # ---- 正向主断言：待支付订单生成 ----
            order_no = data.get("orderNo")
            assert order_no, f"orderNo 为空: {data}"
            assert data.get("orderCreateTime") and data.get("orderExpireTime"), \
                f"订单时间缺失: {data}"
            assert data["orderExpireTime"] > data["orderCreateTime"], \
                f"过期时间早于创建时间: {data}"
            assert isinstance(data.get("price"), (int, float)) and data["price"] > 0, \
                f"price 非法（0 元充值红线）: {data}"
            assert isinstance(data.get("starBeanNum"), int) and data["starBeanNum"] > 0, \
                f"starBeanNum 非法（0 豆充值红线）: {data}"

            # ---- 一致性断言（分通道）----
            if "amount" in case:
                # 自定义金额：与 calculate 同引擎（§5 实测口径一致）
                ratio = resolve_extract_value("{{sb_exchange_ratio}}", required=False)
                if ratio is None:
                    key_log = "sb_exchange_ratio 缺失，联动断言跳过（主断言已过）"
                else:
                    assert data["starBeanNum"] == case["amount"] * ratio, (
                        f"换算不守恒: starBeanNum={data['starBeanNum']} != "
                        f"{case['amount']} × {ratio}"
                    )
                    key_log = f"联动一致: {case['amount']} × {ratio} = {data['starBeanNum']}"
            else:
                # 固定套餐：与 package/active 同元素一致
                exp_price = resolve_extract_value(
                    "{{star_bean_package_price}}", required=False
                )
                exp_beans = resolve_extract_value(
                    "{{star_bean_package_beans}}", required=False
                )
                if exp_price is None or exp_beans is None:
                    key_log = "套餐 extract 缺失，套餐一致性断言跳过（主断言已过）"
                else:
                    assert float(data["price"]) == float(exp_price), \
                        f"price 不一致: {data['price']} != 套餐 {exp_price}"
                    assert data["starBeanNum"] == exp_beans, \
                        f"starBeanNum 不一致: {data['starBeanNum']} != 套餐 {exp_beans}"
                    key_log = f"套餐一致: price={data['price']} beans={data['starBeanNum']}"

            # ---- extract last-wins 只留最后一张；登记表两条都记 ----
            write_yaml(
                "./extract.yaml", {"star_bean_order_no": order_no}, mode="append"
            )
            register_unpaid_order_no(order_no)
            print(f"\n  [buy] orderNo={order_no} | {key_log}")
        finally:
            if apply_cooldown:
                mark_bought()


class TestSb04TransactionPage:
    """GET /api/monitor/star-bean/transaction/page — 星豆使用明细分页"""

    _VALID_TYPES = {"COMMUNICATION", "CREATE_GROUP", "INVITE_MEMBER",
                    "RECHARGE", "REFUND"}

    @pytest.mark.parametrize("case", _TEST_DATA["star_bean_transaction_page_cases"])
    def test_transaction_page(self, base_url, auth_headers, case):
        headers = _SbHelpers.build_headers(auth_headers, case)
        params = {}
        for k in ("type", "page", "pageSize"):
            if k in case:
                params[k] = case[k]
        res = BaseRequest().send_request(
            "get", f"{base_url}/api/monitor/star-bean/transaction/page",
            params=params, headers=headers,
            case_name=case["name"], log_level="none",
        )
        json_data = assert_response(
            case,
            res,
            biz_context={"请求参数": params},
        )
        code = json_data["code"]
        if code != 0:
            return
        # 结构：$.data.items / total / totalPage（OAS 已给，探针 P3/P7 复核）
        data = _jsonpath_parse(json_data, "$.data")[0]
        assert isinstance(data.get("items"), list), f"items 非 list: {data.keys()}"
        assert isinstance(data.get("total"), int) and data["total"] >= 0, \
            f"total 非法: {data.get('total')}"
        assert isinstance(data.get("totalPage"), int) and data["totalPage"] >= 0, \
            f"totalPage 非法: {data.get('totalPage')}"
        # type 过滤语义：传了合法 type 则所有元素 transactionType 必须一致
        if case.get("type") in self._VALID_TYPES:
            mismatched = [it for it in data["items"]
                          if it.get("transactionType") != case["type"]]
            assert not mismatched, \
                f"type 过滤失效: {[it.get('id') for it in mismatched[:3]]}"
        # 元素结构
        for it in data["items"]:
            assert it.get("id"), f"流水缺 id: {it}"
            assert isinstance(it.get("amount"), int) and it["amount"] != 0, \
                f"amount 非法（0 变动不是流水）: {it}"
            assert isinstance(it.get("balanceAfter"), int) and it["balanceAfter"] >= 0, \
                f"balanceAfter 非法（负余额红线）: {it}"
