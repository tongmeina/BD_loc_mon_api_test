# testcases/test_intercom_group_controller.py
# 对讲群批 1：Ig01–Ig10；批 2：Ig04 重复邀请 / Ig11–12 通知 / Ig13 换群 / Ig14 满员
# 计划：plan/intercom-group-tests.plan.md；现网基线 §5
# 群收尾：用例内 close+delete 即清理；registry 兜底中断遗留（消费完成即注销）
# 扩展断言：信封走 send_case → assert_case 公共兼容链；成功一行结论，失败才打对照表（grilling 共识）
import time

import jsonpath
import pytest

from common.case_report_util import (
    assert_case as _assert_case,
    case_headers,
    report_extra as _report_extra,
    report_extra_and_assert as _report_extra_and_assert,
    send_case,
)
from common.cleanup import (
    register_intercom_group,
    intercom_group,
    register_cleanup,
    register_glht_inventory,
    rescue_chat,
)
from common.logger_util import key
from common.rescue_platform_client import generate_rescue_sn
from common.requests_util import BaseRequest, parse_response_json
from common.star_bean_util import latest_balance, latest_entry
from common.yaml_util import (
    read_yaml,
    write_yaml,
    resolve_extract_value,
    is_extract_placeholder,
)

_jsonpath_parse = jsonpath.jsonpath
_TEST_DATA = read_yaml("./yaml/test_intercom_group_controller.yaml")

# 探针 §5 默认；Ig01 正向成功后用现网 cost 覆盖
_COST = {
    "createGroupDeductEnabled": True,
    "createGroupDeductBeans": 20,
    "inviteMemberDeductEnabled": True,
    "inviteMemberDeductBeans": 10,
}


def _jp_first(data, expr):
    found = _jsonpath_parse(data, expr)
    if found:
        return found[0]
    return None


class _IgHelpers:
    """共享逻辑；不以 Test 开头，pytest 不收集。"""

    headers = staticmethod(case_headers)

    @staticmethod
    def resolve_addr(raw, rescue_sat_terminal=None, bd_test_terminal=None,
                     rescue_sat_terminal_b=None, rescue_sat_terminal_b2=None):
        if not isinstance(raw, str):
            return raw
        token = raw.strip()
        if token == "{{rescue_sat_terminal}}":
            return rescue_sat_terminal
        if token == "{{rescue_sat_terminal_b}}":
            return rescue_sat_terminal_b
        if token == "{{rescue_sat_terminal_b2}}":
            return rescue_sat_terminal_b2
        if token == "{{bd_test_terminal}}":
            return bd_test_terminal
        return raw

    @staticmethod
    def replace_ts(value):
        """YAML 占位 {ts} → HHMMSS。群名上限 15：前缀最多 9 字 + 6 位。"""
        if isinstance(value, str) and "{ts}" in value:
            return value.replace("{ts}", time.strftime("%H%M%S"))
        return value

    @staticmethod
    def resolve_gid(case, *, required):
        """正向/需真群：解析 {{ig_group_id}}；负向字面量原样返回；缺值且 required 则 skip。"""
        gid = case.get("intercomGroupId")
        if is_extract_placeholder(gid):
            return resolve_extract_value(gid, required=required)
        return gid

    send = staticmethod(send_case)
    assert_case = staticmethod(_assert_case)
    report_extra = staticmethod(_report_extra)
    report_extra_and_assert = staticmethod(_report_extra_and_assert)

    latest_bean_entry = staticmethod(latest_entry)
    global_balance = staticmethod(latest_balance)

    @staticmethod
    def wait_new_deduction(http, base_url, auth_headers, ttype, beans, before, label,
                           timeout=8, interval=1):
        """轮询流水落账；只在最终一次 report_extra（避免轮询贴多份 Allure）。"""
        started = time.time()
        deadline = started + timeout
        attempt = 0
        last_amount = last_bal = None
        while time.time() < deadline:
            attempt += 1
            after = _IgHelpers.latest_bean_entry(http, base_url, auth_headers, ttype)
            if after is not None:
                last_amount, last_bal = after
            else:
                last_amount, last_bal = None, None
            ok = (
                after is not None
                and last_amount == -beans
                and (before is None or last_bal == before - beans)
            )
            if ok:
                _IgHelpers.report_extra(
                    "扣豆对账", [], ok=True,
                    summary=f"扣豆 {before}→{last_bal}（{last_amount} {ttype}）",
                )
                return
            key(f"{label} 等待落账", f"第{attempt}次 amount={last_amount} bal={last_bal}")
            time.sleep(interval)
        waited = round(time.time() - started, 1)
        _IgHelpers.report_extra("扣豆对账", _IgHelpers._deduct_rows(
            ttype, beans, before, last_amount, last_bal,
            f"第 {attempt} 次 / 等待 {waited}s（未命中）",
        ), ok=False)
        raise AssertionError(
            f"{label}: 流水未按期望落账 type={ttype} amount={last_amount} "
            f"balanceAfter={last_bal} 基线={before} beans={beans}"
        )

    @staticmethod
    def _deduct_rows(ttype, beans, before, amount, bal, hit):
        expect_bal = None if before is None else before - beans
        return [
            {"项": "type", "期望": ttype, "实际": ttype, "通过": True},
            {"项": "扣前余额", "期望": before, "实际": before, "通过": True},
            {"项": "amount", "期望": -beans, "实际": amount,
             "通过": amount == -beans},
            {"项": "balanceAfter", "期望": expect_bal, "实际": bal,
             "通过": before is None or bal == expect_bal},
            {"项": "命中", "期望": "轮询命中", "实际": hit,
             "通过": "未命中" not in str(hit)},
        ]

    @staticmethod
    def report_deduct_skipped(reason):
        _IgHelpers.report_extra("扣豆对账", [
            {"项": "扣费开关", "期望": "关闭则跳过流水", "实际": reason, "通过": True},
        ], ok=True, summary="扣费开关关闭，跳过流水")

    @staticmethod
    def ensure_b2_group(http, base_url, auth_headers):
        """批 2 二号群：与主链 ig_group_id 隔离，躲过 Ig10 删主群。"""
        gid = resolve_extract_value("{{ig_group_id_b2}}", required=False)
        if gid:
            return gid
        name = _IgHelpers.replace_ts("IG_B2_{ts}")
        return _IgHelpers.create_intercom_group(
            http, base_url, auth_headers, name, extract_key="ig_group_id_b2",
        )

    @staticmethod
    def create_intercom_group(http, base_url, auth_headers, name, extract_key=None):
        res = http.send_request(
            "put", f"{base_url}/api/monitor/intercom/group/create",
            params={"intercomGroupName": name}, headers=auth_headers,
            case_name=f"建对讲群 {name}", log_level="none",
        )
        data = parse_response_json(res, context=f"建对讲群 {name}")
        code = data["code"]
        gid = _jp_first(data, "$.data.id")
        if code != 0 or not gid:
            raise AssertionError(f"建对讲群失败: {data}")
        if extract_key:
            write_yaml("./extract.yaml", {extract_key: gid}, mode="append")
            key(f"extract {extract_key}", gid)
        register_intercom_group(gid)
        return gid

    @staticmethod
    def list_member_addrs(http, base_url, auth_headers, gid):
        res = http.send_request(
            "get", f"{base_url}/api/monitor/intercom/group/terminal/list",
            params={"intercomGroupId": gid}, headers=auth_headers,
            case_name="查群成员", log_level="none",
        )
        data = parse_response_json(res, context="查群成员")
        addrs = _jsonpath_parse(data, "$.data[*].addr") or []
        return addrs if addrs is not False else []

    @staticmethod
    def provision_rescue_stick(http, base_url, auth_headers, group_id):
        """A token 入库+添加到指定监控分组。收尾走 session terminals cleaner。"""
        time.sleep(0.05)
        sn = generate_rescue_sn()
        r = http.send_request(
            "get", f"{base_url}/api/monitor/mock-in-storage",
            params={
                "Authorization": auth_headers.get("Authorization"),
                "addr": sn, "sn": sn, "name": "救援测试",
                "remark": "天通救援棒-tmn",
                "terminalType": "TT_RESCUE_STICK", "useScope": "STEAMER",
            },
            headers=auth_headers, case_name=f"满员造棒入库 {sn}", log_level="none",
        )
        data = parse_response_json(r, context=f"满员造棒入库 {sn}")
        if data["code"] != 0:
            raise AssertionError(f"满员造棒入库失败: {data}")
        register_cleanup(f"rescue_chat_{sn}", [sn], rescue_chat.cleaner, tier=100)
        register_glht_inventory(sn)
        r = http.send_request(
            "post", f"{base_url}/api/monitor/groups/{group_id}/terminals",
            json={
                "sn": sn, "remark": "天通救援棒-tmn", "groupId": group_id,
                "terminalType": "TT_RESCUE_STICK", "useScope": "STEAMER",
                "fromAddr": "", "trackColor": "#141323", "trackSize": 5,
                "groupCallNumber": "", "ipAddress": "",
                "gatewayParam": {}, "fieldJson": "",
            },
            headers=auth_headers, case_name=f"满员造棒添加 {sn}", log_level="none",
        )
        data = parse_response_json(r, context=f"满员造棒添加 {sn}")
        if data["code"] != 0:
            raise AssertionError(f"满员造棒添加失败: {data}")
        return sn

    @staticmethod
    def notice_items(http, base_url, headers, **params):
        res = http.send_request(
            "get", f"{base_url}/api/monitor/intercom/message/invitation/notice/list",
            params=params or {"page": 1, "pageSize": 20},
            headers=headers, case_name="邀请通知列表", log_level="none",
        )
        return parse_response_json(res, context="邀请通知列表")

    @staticmethod
    def find_pending_notice(http, base_url, headers_b, group_id, addr):
        data = _IgHelpers.notice_items(
            http, base_url, headers_b, status="PENDING", page=1, pageSize=50,
        )
        items = _jsonpath_parse(data, "$.data.items[*]") or []
        return next(
            (it for it in items
             if str(it.get("groupId")) == str(group_id) and it.get("addr") == addr),
            None,
        )


@pytest.fixture(scope="session", autouse=True)
def _ig_star_bean_gate(base_url, auth_headers):
    """余额闸门：<300 豆则本文件全 skip（满员造数约 70 豆余量）。"""
    bal = _IgHelpers.global_balance(BaseRequest(), base_url, auth_headers)
    key("A账号星豆余额", bal)
    if bal is not None and bal < 300:
        pytest.skip(f"A 账号星豆 {bal} < 300，请充值后再跑对讲群用例")


class TestIg01Cost:
    """GET /intercom/group/cost — 扣费信息"""

    @pytest.mark.parametrize("case", _TEST_DATA["intercom_cost_cases"])
    def test_cost(self, base_url, auth_headers, case):
        url = f"{base_url}/api/monitor/intercom/group/cost"
        json_data = _IgHelpers.send(
            BaseRequest(), "get", url, case, _IgHelpers.headers(auth_headers, case),
        )
        code, _ = _IgHelpers.assert_case(case, json_data, {"请求参数": {}})
        if code != 0:
            return
        data = _jp_first(json_data, "$.data") or {}
        beans_c = data.get("createGroupDeductBeans")
        beans_i = data.get("inviteMemberDeductBeans")
        en_c = data.get("createGroupDeductEnabled")
        en_i = data.get("inviteMemberDeductEnabled")
        _IgHelpers.report_extra_and_assert("cost 四值", [
            {"项": "createGroupDeductBeans", "期望": "int ≥ 0", "实际": beans_c,
             "通过": isinstance(beans_c, int) and beans_c >= 0},
            {"项": "createGroupDeductEnabled", "期望": "bool", "实际": en_c,
             "通过": isinstance(en_c, bool)},
            {"项": "inviteMemberDeductBeans", "期望": "int ≥ 0", "实际": beans_i,
             "通过": isinstance(beans_i, int) and beans_i >= 0},
            {"项": "inviteMemberDeductEnabled", "期望": "bool", "实际": en_i,
             "通过": isinstance(en_i, bool)},
        ], f"扣费：创建 {beans_c}/{'开' if en_c else '关'}，邀请 {beans_i}/{'开' if en_i else '关'}")
        _COST.update({
            "createGroupDeductEnabled": en_c,
            "createGroupDeductBeans": beans_c,
            "inviteMemberDeductEnabled": en_i,
            "inviteMemberDeductBeans": beans_i,
        })


class TestIg02Create:
    """PUT /intercom/group/create — 创建对讲群（扣豆 + registry 注册）"""

    @pytest.mark.parametrize("case", _TEST_DATA["intercom_create_cases"])
    def test_create(self, base_url, auth_headers, case):
        http = BaseRequest()
        url = f"{base_url}/api/monitor/intercom/group/create"
        params = {}
        if "intercomGroupName" in case:
            params["intercomGroupName"] = _IgHelpers.replace_ts(case["intercomGroupName"])
        before = None
        if not case.get("no_auth"):
            before = _IgHelpers.global_balance(http, base_url, auth_headers)
        json_data = _IgHelpers.send(
            http, "put", url, case, _IgHelpers.headers(auth_headers, case), params=params,
        )
        code, _ = _IgHelpers.assert_case(case, json_data, {"请求参数": params})
        if code != 0:
            return
        data = _jp_first(json_data, "$.data") or {}
        gid = data.get("id")
        req_name = params.get("intercomGroupName")
        _IgHelpers.report_extra_and_assert("创建响应字段", [
            {"项": "id", "期望": "非空", "实际": gid, "通过": bool(gid)},
            {"项": "groupName", "期望": req_name, "实际": data.get("groupName"),
             "通过": data.get("groupName") == req_name},
            {"项": "status", "期望": 1, "实际": data.get("status"),
             "通过": data.get("status") == 1},
            {"项": "webAccount", "期望": "非空", "实际": data.get("webAccount"),
             "通过": bool(data.get("webAccount"))},
            {"项": "starBeanInsufficient", "期望": False, "实际": data.get("starBeanInsufficient"),
             "通过": data.get("starBeanInsufficient") is False},
        ], f"建群 {data.get('groupName')} status={data.get('status')}")
        if not resolve_extract_value("{{ig_group_id}}", required=False):
            write_yaml("./extract.yaml", {"ig_group_id": gid}, mode="append")
        register_intercom_group(gid)
        if _COST["createGroupDeductEnabled"]:
            _IgHelpers.wait_new_deduction(
                http, base_url, auth_headers, "CREATE_GROUP",
                _COST["createGroupDeductBeans"], before, "创建群扣豆",
            )
        else:
            _IgHelpers.report_deduct_skipped("createGroupDeductEnabled=false")


class TestIg03Update:
    """PUT /intercom/group/update — 改群名"""

    @pytest.mark.parametrize("case", _TEST_DATA["intercom_update_cases"])
    def test_update(self, base_url, auth_headers, case):
        http = BaseRequest()
        url = f"{base_url}/api/monitor/intercom/group/update"
        gid = _IgHelpers.resolve_gid(case, required=True)
        params = {}
        if gid is not None:
            params["intercomGroupId"] = gid
        if "intercomGroupName" in case:
            params["intercomGroupName"] = _IgHelpers.replace_ts(case["intercomGroupName"])
        json_data = _IgHelpers.send(
            http, "put", url, case, _IgHelpers.headers(auth_headers, case), params=params,
        )
        code, _ = _IgHelpers.assert_case(case, json_data, {"请求参数": params})
        if code != 0:
            return
        real_gid = resolve_extract_value("{{ig_group_id}}", required=False)
        if params.get("intercomGroupId") != real_gid:
            return
        r2 = http.send_request(
            "get", f"{base_url}/api/monitor/intercom/group/remainder",
            params={"intercomGroupId": params["intercomGroupId"]},
            headers=auth_headers, case_name="改名复核", log_level="none",
        )
        remainder_data = parse_response_json(r2, context="改名复核")
        name_now = _jp_first(remainder_data, "$.data.groupName")
        _IgHelpers.report_extra_and_assert("改名复核", [
            {"项": "remainder.groupName", "期望": params["intercomGroupName"],
             "实际": name_now, "通过": name_now == params["intercomGroupName"]},
        ], f"群名已改为 {name_now}")


class TestIg04Invite:
    """POST /intercom/group/invitation — 邀请（A 支路直入群 / B 支路发通知）"""

    @pytest.mark.parametrize("case", _TEST_DATA["intercom_invite_cases"])
    def test_invite(self, base_url, auth_headers, rescue_sat_terminal, bd_test_terminal,
                    case, request):
        http = BaseRequest()
        url = f"{base_url}/api/monitor/intercom/group/invitation"
        scene = case.get("scene")
        branch_b = case.get("branch") == "B"
        sn_b = sn_b2 = None
        if branch_b or any(
            isinstance(it, dict) and it.get("addr") == "{{rescue_sat_terminal_b}}"
            for it in (case.get("addrInfos") or [])
        ):
            sn_b = request.getfixturevalue("rescue_sat_terminal_b")
        if any(
            isinstance(it, dict) and it.get("addr") == "{{rescue_sat_terminal_b2}}"
            for it in (case.get("addrInfos") or [])
        ):
            sn_b2 = request.getfixturevalue("rescue_sat_terminal_b2")
        if sn_b:
            em = (case.get("expected") or {}).get("error_msg")
            if isinstance(em, str) and "{{rescue_sat_terminal_b}}" in em:
                case = {**case, "expected": {**case["expected"],
                        "error_msg": em.replace("{{rescue_sat_terminal_b}}", str(sn_b))}}
        if branch_b or scene == "dup_pending":
            gid = _IgHelpers.ensure_b2_group(http, base_url, auth_headers)
        else:
            gid = _IgHelpers.resolve_gid(case, required=not case.get("no_auth"))
            if gid is None and not case.get("no_auth"):
                gid = resolve_extract_value("{{ig_group_id}}", required=True)
        body = {"force": case.get("force", False)}
        if gid is not None:
            body["intercomGroupId"] = gid
        addr_infos = []
        for item in case.get("addrInfos") or []:
            if isinstance(item, dict):
                addr_infos.append({
                    "addr": _IgHelpers.resolve_addr(
                        item.get("addr"), rescue_sat_terminal, bd_test_terminal,
                        sn_b, sn_b2,
                    )
                })
        body["addrInfos"] = addr_infos
        before = None
        expect_deduct = case.get("expect_deduct", case["expected"]["code"] == 0)
        if not case.get("no_auth") and addr_infos and (
            case["expected"]["code"] == 0 or case.get("expect_deduct") is False
        ):
            before = _IgHelpers.global_balance(http, base_url, auth_headers)
        json_data = _IgHelpers.send(
            http, "post", url, case, _IgHelpers.headers(auth_headers, case), json=body,
        )
        code, _ = _IgHelpers.assert_case(case, json_data, {"请求参数": body})
        if case.get("expect_deduct") is False:
            invited = [a.get("addr") for a in addr_infos]
            after = _IgHelpers.global_balance(http, base_url, auth_headers)
            rows = [
                {"项": "余额未变", "期望": before, "实际": after,
                 "通过": after == before},
            ]
            if scene == "dup_in_group":
                r2 = http.send_request(
                    "get", f"{base_url}/api/monitor/intercom/group/terminal/list",
                    params={"intercomGroupId": gid}, headers=auth_headers,
                    case_name="重复邀后查成员", log_level="none",
                )
                member_data = parse_response_json(r2, context="重复邀后查成员")
                listed = _jsonpath_parse(member_data, "$.data[*].addr") or []
                rows.append({
                    "项": "仍在本群", "期望": invited, "实际": listed,
                    "通过": all(a in listed for a in invited),
                })
            if scene == "dup_pending":
                send = http.send_request(
                    "get", f"{base_url}/api/monitor/intercom/message/send/invitation/list",
                    params={"intercomGroupId": gid, "status": "PENDING",
                            "page": 1, "pageSize": 50},
                    headers=auth_headers, case_name="重复邀后发送列表", log_level="none",
                )
                send_data = parse_response_json(send, context="邀请发送列表")
                sitems = _jsonpath_parse(send_data, "$.data.items[*]") or []
                pending = [it for it in sitems if it.get("addr") in invited]
                nid = resolve_extract_value("{{ig_invite_notice_id}}", required=False)
                rows.append({
                    "项": "PENDING 条数", "期望": 1, "实际": len(pending),
                    "通过": len(pending) == 1,
                })
                if nid:
                    rows.append({
                        "项": "通知 id 沿用", "期望": nid,
                        "实际": (pending[0].get("id") if pending else None),
                        "通过": bool(pending) and pending[0].get("id") == nid,
                    })
            _IgHelpers.report_extra_and_assert(
                "重复邀请不扣费", rows,
                f"重复邀请 code={code} 余额 {before}→{after}",
            )
            return
        if code != 0:
            return
        data = _jp_first(json_data, "$.data") or {}
        members = data.get("groupMembers") or []
        invited = [a.get("addr") for a in addr_infos]
        got = [m.get("addr") for m in members]
        expect_confirm = (0, 1) if branch_b else (1,)
        rows = [
            {"项": "confirm", "期望": "0 或 1" if branch_b else 1,
             "实际": data.get("confirm"),
             "通过": data.get("confirm") in expect_confirm},
            {"项": "starBeanInsufficient", "期望": False,
             "实际": data.get("starBeanInsufficient"),
             "通过": data.get("starBeanInsufficient") is False},
        ]
        if branch_b:
            rows.append({
                "项": "groupMembers", "期望": "可空（现网 confirm=1 仍空）",
                "实际": got, "通过": True,
            })
        else:
            rows.append({
                "项": "groupMembers 含 addr", "期望": invited, "实际": got,
                "通过": all(addr in got for addr in invited),
            })
        if branch_b:
            _IgHelpers.report_extra_and_assert(
                "邀请响应字段", rows,
                f"邀请 confirm={data.get('confirm')}（B支路）",
            )
        else:
            _IgHelpers.report_extra_and_assert(
                "邀请响应字段", rows,
                f"邀请入群 confirm={data.get('confirm')}，含 {','.join(str(a) for a in invited)}",
            )
        r2 = http.send_request(
            "get", f"{base_url}/api/monitor/intercom/group/terminal/list",
            params={"intercomGroupId": gid}, headers=auth_headers,
            case_name="邀请后查成员", log_level="none",
        )
        member_data = parse_response_json(r2, context="成员列表复核")
        listed = _jsonpath_parse(member_data, "$.data[*].addr") or []
        if branch_b:
            send = http.send_request(
                "get", f"{base_url}/api/monitor/intercom/message/send/invitation/list",
                params={"intercomGroupId": gid, "page": 1, "pageSize": 50},
                headers=auth_headers, case_name="B邀后A发送列表", log_level="none",
            )
            send_data = parse_response_json(send, context="B邀后A发送列表")
            sitems = _jsonpath_parse(send_data, "$.data.items[*]") or []
            pending = next(
                (it for it in sitems if it.get("addr") in invited), None,
            )
            _IgHelpers.report_extra_and_assert("成员或发送列表", [
                {"项": "list 含 B 或 send-list 有记录",
                 "期望": invited,
                 "实际": {"list": listed, "send": (pending or {}).get("id")},
                 "通过": all(a in listed for a in invited) or pending is not None},
            ], f"B邀请已见 {','.join(str(a) for a in invited)}（list或发送）")
            if pending and not resolve_extract_value("{{ig_invite_notice_id}}", required=False):
                write_yaml("./extract.yaml", {"ig_invite_notice_id": pending["id"]}, mode="append")
                key("extract ig_invite_notice_id", pending["id"])
        else:
            _IgHelpers.report_extra_and_assert("成员列表复核", [
                {"项": "list 含 addr", "期望": invited, "实际": listed,
                 "通过": all(addr in listed for addr in invited)},
            ], f"list 含 {','.join(str(a) for a in invited)}")
        if expect_deduct and _COST["inviteMemberDeductEnabled"]:
            _IgHelpers.wait_new_deduction(
                http, base_url, auth_headers, "INVITE_MEMBER",
                _COST["inviteMemberDeductBeans"] * len(invited), before, "邀请扣豆",
            )
        elif expect_deduct:
            _IgHelpers.report_deduct_skipped("inviteMemberDeductEnabled=false")


class TestIg05TerminalList:
    """GET /intercom/group/terminal/list — 群成员列表（写 ig_member_id）"""

    @pytest.mark.parametrize("case", _TEST_DATA["intercom_terminal_list_cases"])
    def test_terminal_list(self, base_url, auth_headers, case):
        url = f"{base_url}/api/monitor/intercom/group/terminal/list"
        gid = _IgHelpers.resolve_gid(case, required=not case.get("no_auth"))
        params = {}
        if gid is not None:
            params["intercomGroupId"] = gid
        json_data = _IgHelpers.send(
            BaseRequest(), "get", url, case, _IgHelpers.headers(auth_headers, case),
            params=params,
        )
        code, _ = _IgHelpers.assert_case(case, json_data, {"请求参数": params})
        if code != 0:
            return
        real_gid = resolve_extract_value("{{ig_group_id}}", required=False)
        if gid != real_gid:
            return
        members = _jsonpath_parse(json_data, "$.data[*]") or []
        missing = [m for m in members if not (m.get("id") and m.get("addr"))]
        mine = next((m for m in members if m.get("myTerminal") is True), None)
        _IgHelpers.report_extra_and_assert("成员结构", [
            {"项": "data 为 list 且非空", "期望": "非空 list",
             "实际": f"len={len(members)}", "通过": isinstance(members, list) and len(members) > 0},
            {"项": "每条有 id、addr", "期望": "均有", "实际": f"缺 {len(missing)} 条",
             "通过": not missing},
            {"项": "存在 myTerminal==true", "期望": "有", "实际": (mine or {}).get("id"),
             "通过": mine is not None},
        ], f"成员 {len(members)} 人，myTerminal={(mine or {}).get('id')}")
        if members and not resolve_extract_value("{{ig_member_id}}", required=False):
            if mine:
                write_yaml("./extract.yaml", {"ig_member_id": mine["id"]}, mode="append")
                key("extract ig_member_id", mine["id"])


class TestIg06Remainder:
    """GET /intercom/group/remainder — 剩余额度与状态"""

    @pytest.mark.parametrize("case", _TEST_DATA["intercom_remainder_cases"])
    def test_remainder(self, base_url, auth_headers, case):
        url = f"{base_url}/api/monitor/intercom/group/remainder"
        gid = _IgHelpers.resolve_gid(case, required=not case.get("no_auth"))
        params = {}
        if gid is not None:
            params["intercomGroupId"] = gid
        json_data = _IgHelpers.send(
            BaseRequest(), "get", url, case, _IgHelpers.headers(auth_headers, case),
            params=params,
        )
        code, _ = _IgHelpers.assert_case(case, json_data, {"请求参数": params})
        if code != 0:
            return
        data = _jp_first(json_data, "$.data") or {}
        voice = data.get("allRemainingVoiceNumber")
        pos = data.get("allRemainingPositionNumber")
        _IgHelpers.report_extra_and_assert("额度与状态", [
            {"项": "groupName", "期望": "非空", "实际": data.get("groupName"),
             "通过": bool(data.get("groupName"))},
            {"项": "status", "期望": "0 或 1", "实际": data.get("status"),
             "通过": data.get("status") in (0, 1)},
            {"项": "maxMembers", "期望": "int > 0", "实际": data.get("maxMembers"),
             "通过": isinstance(data.get("maxMembers"), int) and data["maxMembers"] > 0},
            {"项": "allRemainingVoiceNumber", "期望": "int ≥ 0", "实际": voice,
             "通过": isinstance(voice, int) and voice >= 0},
            {"项": "allRemainingPositionNumber", "期望": "int ≥ 0", "实际": pos,
             "通过": isinstance(pos, int) and pos >= 0},
            {"项": "isOwner", "期望": True, "实际": data.get("isOwner"),
             "通过": data.get("isOwner") is True},
            {"项": "exited", "期望": False, "实际": data.get("exited"),
             "通过": data.get("exited") is False},
        ], f"status={data.get('status')} 语音={voice} 位置={pos} 群主")


class TestIg07Nickname:
    """PUT /intercom/member/update/nickname — 改自己设备昵称

    OAS：query `intercomGroupMemberId` + `newNickname`（不是 memberId/nickname，也不是 json）。
    """

    @pytest.mark.parametrize("case", _TEST_DATA["intercom_nickname_cases"])
    def test_nickname(self, base_url, auth_headers, case):
        http = BaseRequest()
        url = f"{base_url}/api/monitor/intercom/member/update/nickname"
        mid = case.get("intercomGroupMemberId")
        if is_extract_placeholder(mid):
            mid = resolve_extract_value(mid, required=True)
        params = {}
        if mid is not None:
            params["intercomGroupMemberId"] = mid
        if "newNickname" in case:
            params["newNickname"] = _IgHelpers.replace_ts(case["newNickname"])
        json_data = _IgHelpers.send(
            http, "put", url, case, _IgHelpers.headers(auth_headers, case), params=params,
        )
        code, _ = _IgHelpers.assert_case(case, json_data, {"请求参数": params})
        if code != 0:
            return
        gid = resolve_extract_value("{{ig_group_id}}", required=False)
        r2 = http.send_request(
            "get", f"{base_url}/api/monitor/intercom/group/terminal/list",
            params={"intercomGroupId": gid}, headers=auth_headers,
            case_name="昵称复核", log_level="none",
        )
        member_data = parse_response_json(r2, context="昵称复核")
        members = _jsonpath_parse(member_data, "$.data[*]") or []
        target = next((m for m in members if m.get("id") == mid), None)
        nick_now = (target.get("avatarInfo") or {}).get("nickname") if target else None
        _IgHelpers.report_extra_and_assert("昵称复核", [
            {"项": "成员 id 命中", "期望": mid, "实际": (target or {}).get("id"),
             "通过": target is not None},
            {"项": "avatarInfo.nickname", "期望": params.get("newNickname"), "实际": nick_now,
             "通过": nick_now == params.get("newNickname")},
        ], f"昵称已改为 {nick_now}")


class TestIg08AddrRemove:
    """GET /intercom/group/addr/remove — 移除设备（不退豆）"""

    @pytest.mark.parametrize("case", _TEST_DATA["intercom_addr_remove_cases"])
    def test_addr_remove(self, base_url, auth_headers, rescue_sat_terminal, case):
        http = BaseRequest()
        url = f"{base_url}/api/monitor/intercom/group/addr/remove"
        gid = _IgHelpers.resolve_gid(case, required=not case.get("no_auth"))
        params = {}
        if gid is not None:
            params["intercomGroupId"] = gid
        addr = _IgHelpers.resolve_addr(case.get("addr"), rescue_sat_terminal)
        if addr is not None:
            params["addr"] = addr
        json_data = _IgHelpers.send(
            http, "get", url, case, _IgHelpers.headers(auth_headers, case), params=params,
        )
        code, _ = _IgHelpers.assert_case(case, json_data, {"请求参数": params})
        if code != 0 or addr != rescue_sat_terminal:
            return
        r2 = http.send_request(
            "get", f"{base_url}/api/monitor/intercom/group/terminal/list",
            params={"intercomGroupId": gid}, headers=auth_headers,
            case_name="移除复核", log_level="none",
        )
        member_data = parse_response_json(r2, context="成员列表复核")
        listed = _jsonpath_parse(member_data, "$.data[*].addr") or []
        _IgHelpers.report_extra_and_assert("移除复核", [
            {"项": "addr 不在 list", "期望": f"{addr} 不在", "实际": listed,
             "通过": addr not in listed},
        ], f"已移除 {addr}")


class TestIg09Close:
    """PUT /intercom/group/close — 关闭群聊

    YAML 序：路人 → 群主正向 → 假群/无 token → 重复关闭 → 被邀请人（独立群+B棒3）。
    路人/被邀请人按 scene 才拉 B token，不给所有 close 叶子注入 B。
    """

    @pytest.mark.parametrize("case", _TEST_DATA["intercom_close_cases"])
    def test_close(self, base_url, auth_headers, case, request):
        http = BaseRequest()
        url = f"{base_url}/api/monitor/intercom/group/close"
        scene = case.get("scene")
        if scene == "not_owner_invitee":
            sn_b3 = request.getfixturevalue("rescue_sat_terminal_b3")
            gid = _IgHelpers.create_intercom_group(
                http, base_url, auth_headers, _IgHelpers.replace_ts("IG_CL_{ts}"),
            )
            inv = http.send_request(
                "post", f"{base_url}/api/monitor/intercom/group/invitation",
                json={"intercomGroupId": gid, "addrInfos": [{"addr": sn_b3}], "force": False},
                headers=auth_headers, case_name="关群-邀B新棒", log_level="none",
            )
            inv_data = parse_response_json(inv, context="前置邀请")
            if inv_data["code"] != 0:
                raise AssertionError(f"关群前置邀请失败: {inv_data}")
        else:
            gid = _IgHelpers.resolve_gid(case, required=False)
        params = {}
        if gid is not None:
            params["intercomGroupId"] = gid
        close_headers = auth_headers
        if scene in ("not_owner_stranger", "not_owner_invitee"):
            close_headers = request.getfixturevalue("auth_headers_b")
        json_data = _IgHelpers.send(
            http, "put", url, case, _IgHelpers.headers(close_headers, case), params=params,
        )
        _IgHelpers.assert_case(case, json_data, {"请求参数": params})
        expect_status = case.get("expect_status")
        if expect_status is None:
            return
        r2 = http.send_request(
            "get", f"{base_url}/api/monitor/intercom/group/remainder",
            params={"intercomGroupId": gid}, headers=auth_headers,
            case_name="关群复核", log_level="none",
        )
        remainder_data = parse_response_json(r2, context="关群复核")
        status_now = _jp_first(remainder_data, "$.data.status")
        _IgHelpers.report_extra_and_assert("关群复核", [
            {"项": "remainder.status", "期望": expect_status, "实际": status_now,
             "通过": status_now == expect_status},
        ], f"关后 status={status_now}（期望 {expect_status}）")


class TestIg10Delete:
    """DELETE /intercom/group/delete — 删除对讲群（注销 cleaner）"""

    @pytest.mark.parametrize("case", _TEST_DATA["intercom_delete_cases"])
    def test_delete(self, base_url, auth_headers, case):
        url = f"{base_url}/api/monitor/intercom/group/delete"
        gid = _IgHelpers.resolve_gid(case, required=False)
        params = {}
        if gid is not None:
            params["intercomGroupId"] = gid
        json_data = _IgHelpers.send(
            BaseRequest(), "delete", url, case, _IgHelpers.headers(auth_headers, case),
            params=params,
        )
        code, _ = _IgHelpers.assert_case(case, json_data, {"请求参数": params})
        if code == 0 and gid:
            intercom_group.unregister(gid)


class TestIg11InviteNotice:
    """邀请通知域三 GET：notice/list（B）/ pending/count（B）/ send/invitation/list（A）"""

    @pytest.mark.parametrize("case", _TEST_DATA["intercom_notice_list_cases"])
    def test_notice_list(self, base_url, auth_headers_b, rescue_sat_terminal_b, case):
        http = BaseRequest()
        url = f"{base_url}/api/monitor/intercom/message/invitation/notice/list"
        params = {"page": 1, "pageSize": 50}
        if case.get("status"):
            params["status"] = case["status"]
        json_data = _IgHelpers.send(
            http, "get", url, case, _IgHelpers.headers(auth_headers_b, case), params=params,
        )
        code, _ = _IgHelpers.assert_case(case, json_data, {"请求参数": params})
        if code != 0:
            return
        gid = resolve_extract_value("{{ig_group_id_b2}}", required=True)
        items = _jsonpath_parse(json_data, "$.data.items[*]") or []
        hit = next(
            (it for it in items
             if str(it.get("groupId")) == str(gid)
             and it.get("addr") == rescue_sat_terminal_b),
            None,
        )
        _IgHelpers.report_extra_and_assert("通知列表", [
            {"项": "B收件箱含本次邀请", "期望": rescue_sat_terminal_b,
             "实际": (hit or {}).get("addr"), "通过": hit is not None},
            {"项": "status", "期望": "PENDING",
             "实际": (hit or {}).get("status"),
             "通过": (hit or {}).get("status") == "PENDING"},
        ], f"B收件箱含 {rescue_sat_terminal_b} status={(hit or {}).get('status')}")
        if hit and not resolve_extract_value("{{ig_invite_notice_id}}", required=False):
            write_yaml("./extract.yaml", {"ig_invite_notice_id": hit["id"]}, mode="append")
            key("extract ig_invite_notice_id", hit["id"])

    @pytest.mark.parametrize("case", _TEST_DATA["intercom_pending_count_cases"])
    def test_pending_count(self, base_url, auth_headers_b, case):
        url = f"{base_url}/api/monitor/intercom/message/invitation/pending/count"
        json_data = _IgHelpers.send(
            BaseRequest(), "get", url, case, _IgHelpers.headers(auth_headers_b, case),
        )
        code, _ = _IgHelpers.assert_case(case, json_data, {"请求参数": {}})
        if code != 0:
            return
        cnt = _jp_first(json_data, "$.data")
        _IgHelpers.report_extra_and_assert("待确认数量", [
            {"项": "data", "期望": "int ≥ 1", "实际": cnt,
             "通过": isinstance(cnt, int) and cnt >= 1},
        ], f"待确认数量 {cnt}")

    @pytest.mark.parametrize("case", _TEST_DATA["intercom_send_invitation_list_cases"])
    def test_send_list(self, base_url, auth_headers, rescue_sat_terminal_b, case):
        url = f"{base_url}/api/monitor/intercom/message/send/invitation/list"
        gid = case.get("intercomGroupId")
        if is_extract_placeholder(gid):
            gid = resolve_extract_value(gid, required=not case.get("no_auth"))
        params = {"page": 1, "pageSize": 50}
        if gid is not None:
            params["intercomGroupId"] = gid
        if case.get("status"):
            params["status"] = case["status"]
        json_data = _IgHelpers.send(
            BaseRequest(), "get", url, case, _IgHelpers.headers(auth_headers, case),
            params=params,
        )
        code, _ = _IgHelpers.assert_case(case, json_data, {"请求参数": params})
        if code != 0:
            return
        items = _jsonpath_parse(json_data, "$.data.items[*]") or []
        hit = next((it for it in items if it.get("addr") == rescue_sat_terminal_b), None)
        _IgHelpers.report_extra_and_assert("我发送的邀请", [
            {"项": "含 B棒 addr", "期望": rescue_sat_terminal_b,
             "实际": (hit or {}).get("addr"), "通过": hit is not None},
            {"项": "status", "期望": "PENDING", "实际": (hit or {}).get("status"),
             "通过": (hit or {}).get("status") == "PENDING"},
        ], f"发送列表含 {rescue_sat_terminal_b} status={(hit or {}).get('status')}")


class TestIg12InviteHandler:
    """PUT /intercom/message/invitation/handler — B 处理邀请（同意真闭环 / 拒绝锁码）"""

    @pytest.mark.parametrize("case", _TEST_DATA["intercom_invite_handler_cases"])
    def test_handler(self, base_url, auth_headers, auth_headers_b, case, request):
        http = BaseRequest()
        url = f"{base_url}/api/monitor/intercom/message/invitation/handler"
        action = case.get("action")
        nid = case.get("invitationNoticeId")
        if action == "reject":
            sn_b2 = request.getfixturevalue("rescue_sat_terminal_b2")
            gid = _IgHelpers.ensure_b2_group(http, base_url, auth_headers)
            inv = http.send_request(
                "post", f"{base_url}/api/monitor/intercom/group/invitation",
                json={"intercomGroupId": gid, "addrInfos": [{"addr": sn_b2}], "force": False},
                headers=auth_headers, case_name="拒绝支路补邀请", log_level="none",
            )
            inv_data = parse_response_json(inv, context="前置邀请")
            if inv_data["code"] != 0:
                raise AssertionError(f"拒绝支路补邀请失败: {inv_data}")
            notice = None
            for _ in range(5):
                send = http.send_request(
                    "get", f"{base_url}/api/monitor/intercom/message/send/invitation/list",
                    params={"intercomGroupId": gid, "status": "PENDING", "page": 1, "pageSize": 50},
                    headers=auth_headers, case_name="拒绝支路A发送列表", log_level="none",
                )
                send_data = parse_response_json(send, context="邀请发送列表")
                sitems = _jsonpath_parse(send_data, "$.data.items[*]") or []
                notice = next((it for it in sitems if it.get("addr") == sn_b2), None)
                if notice:
                    break
                notice = _IgHelpers.find_pending_notice(
                    http, base_url, auth_headers_b, gid, sn_b2,
                )
                if notice:
                    break
                time.sleep(1)
            if not notice:
                raise AssertionError("拒绝支路未找到 PENDING 通知（A send-list / B notice）")
            nid = notice["id"]
        elif is_extract_placeholder(nid):
            nid = resolve_extract_value(nid, required=True)
        params = {}
        if case.get("handlerType"):
            params["handlerType"] = case["handlerType"]
        if nid is not None:
            params["invitationNoticeId"] = nid
        json_data = _IgHelpers.send(
            http, "put", url, case, _IgHelpers.headers(auth_headers_b, case), params=params,
        )
        code, _ = _IgHelpers.assert_case(case, json_data, {"请求参数": params})
        if code != 0:
            return
        gid = resolve_extract_value("{{ig_group_id_b2}}", required=False)
        if case.get("handlerType") == "AGREED" and gid:
            sn_b = request.getfixturevalue("rescue_sat_terminal_b")
            r2 = http.send_request(
                "get", f"{base_url}/api/monitor/intercom/group/terminal/list",
                params={"intercomGroupId": gid}, headers=auth_headers,
                case_name="同意后成员复核", log_level="none",
            )
            member_data = parse_response_json(r2, context="同意后成员复核")
            listed = _jsonpath_parse(member_data, "$.data[*].addr") or []
            _IgHelpers.report_extra_and_assert("同意闭环", [
                {"项": "A侧 list 含 B addr", "期望": sn_b, "实际": listed,
                 "通过": sn_b in listed},
            ], f"同意闭环 list 含 {sn_b}")
            r3 = http.send_request(
                "put", url, params=params, headers=auth_headers_b,
                case_name="重复同意(探针口径)", log_level="none",
            )
            repeat_data = parse_response_json(r3, context="重复同意(探针口径)")
            c3 = repeat_data["code"]
            _IgHelpers.report_extra_and_assert("重复处理", [
                {"项": "code", "期望": "非0", "实际": c3, "通过": c3 not in (0, None)},
            ], f"重复处理 code={c3}")
            key("重复同意返回", f"code={c3} msg={repeat_data.get('msg')}" )
        if case.get("handlerType") == "REJECTED":
            _IgHelpers.report_extra_and_assert("拒绝只锁码", [
                {"项": "code", "期望": 0, "实际": code, "通过": code == 0},
                {"项": "退费流水", "期望": "不写死方向（§9.1）",
                 "实际": "仅记录，见计划 §5", "通过": True},
            ], "拒绝成功，退费不锁流水")


class TestIg13SwitchGroup:
    """真换群：他人棒先 pending 再同意才退原群；自己棒 force=false 不换 / force=true 静默换。"""

    def test_switch_other_agree(self, base_url, auth_headers, auth_headers_b,
                                rescue_sat_terminal_b):
        http = BaseRequest()
        old = resolve_extract_value("{{ig_group_id_b2}}", required=True)
        sn = rescue_sat_terminal_b
        listed_old = _IgHelpers.list_member_addrs(http, base_url, auth_headers, old)
        if sn not in listed_old:
            pytest.skip(f"B棒不在二号群，无法测换群: list={listed_old}")
        gid_new = _IgHelpers.create_intercom_group(
            http, base_url, auth_headers, _IgHelpers.replace_ts("IG_SW_{ts}"),
        )
        before = _IgHelpers.global_balance(http, base_url, auth_headers)
        inv = http.send_request(
            "post", f"{base_url}/api/monitor/intercom/group/invitation",
            json={"intercomGroupId": gid_new, "addrInfos": [{"addr": sn}], "force": False},
            headers=auth_headers, case_name="换群-邀他人棒", log_level="none",
        )
        data = parse_response_json(inv, context="换群-邀他人棒")
        code = data["code"]
        confirm = _jp_first(data, "$.data.confirm")
        listed_new = _IgHelpers.list_member_addrs(http, base_url, auth_headers, gid_new)
        listed_old2 = _IgHelpers.list_member_addrs(http, base_url, auth_headers, old)
        send = http.send_request(
            "get", f"{base_url}/api/monitor/intercom/message/send/invitation/list",
            params={"intercomGroupId": gid_new, "status": "PENDING", "page": 1, "pageSize": 50},
            headers=auth_headers, case_name="换群-发送列表", log_level="none",
        )
        send_data = parse_response_json(send, context="换群-发送列表")
        pending = next(
            (it for it in (_jsonpath_parse(send_data, "$.data.items[*]") or [])
             if it.get("addr") == sn),
            None,
        )
        _IgHelpers.report_extra_and_assert("他人棒换群-邀请", [
            {"项": "code", "期望": 0, "实际": code, "通过": code == 0},
            {"项": "新群尚无此棒", "期望": f"{sn} 不在", "实际": listed_new,
             "通过": sn not in listed_new},
            {"项": "旧群仍有此棒", "期望": sn, "实际": listed_old2,
             "通过": sn in listed_old2},
            {"项": "新 PENDING", "期望": "有", "实际": (pending or {}).get("id"),
             "通过": pending is not None},
            {"项": "confirm", "期望": "0 或 1", "实际": confirm,
             "通过": confirm in (0, 1)},
        ], f"换群邀请 code={code} confirm={confirm} pending={(pending or {}).get('id')}")
        if _COST["inviteMemberDeductEnabled"]:
            _IgHelpers.wait_new_deduction(
                http, base_url, auth_headers, "INVITE_MEMBER",
                _COST["inviteMemberDeductBeans"], before, "换群邀请扣豆",
            )
        nid = pending["id"]
        handler = http.send_request(
            "put", f"{base_url}/api/monitor/intercom/message/invitation/handler",
            params={"handlerType": "AGREED", "invitationNoticeId": nid},
            headers=auth_headers_b, case_name="换群-B同意", log_level="none",
        )
        h = parse_response_json(handler, context="换群-B同意")
        hcode = h["code"]
        listed_new2 = _IgHelpers.list_member_addrs(http, base_url, auth_headers, gid_new)
        listed_old3 = _IgHelpers.list_member_addrs(http, base_url, auth_headers, old)
        _IgHelpers.report_extra_and_assert("他人棒换群-同意", [
            {"项": "handler code", "期望": 0, "实际": hcode, "通过": hcode == 0},
            {"项": "新群含此棒", "期望": sn, "实际": listed_new2, "通过": sn in listed_new2},
            {"项": "旧群已退出", "期望": f"{sn} 不在", "实际": listed_old3,
             "通过": sn not in listed_old3},
        ], f"同意后新群有棒、旧群已退")

    def test_switch_own_force(self, base_url, auth_headers, rescue_sat_terminal):
        http = BaseRequest()
        sn = rescue_sat_terminal
        g1 = _IgHelpers.create_intercom_group(
            http, base_url, auth_headers, _IgHelpers.replace_ts("IG_OA_{ts}"),
        )
        before_g1 = _IgHelpers.global_balance(http, base_url, auth_headers)
        inv1 = http.send_request(
            "post", f"{base_url}/api/monitor/intercom/group/invitation",
            json={"intercomGroupId": g1, "addrInfos": [{"addr": sn}], "force": False},
            headers=auth_headers, case_name="自己棒入G1", log_level="none",
        )
        inv1_data = parse_response_json(inv1, context="自己棒入G1")
        if inv1_data["code"] != 0:
            raise AssertionError(f"自己棒入G1失败: {inv1_data}")
        if _COST["inviteMemberDeductEnabled"]:
            _IgHelpers.wait_new_deduction(
                http, base_url, auth_headers, "INVITE_MEMBER",
                _COST["inviteMemberDeductBeans"], before_g1, "自己棒入G1扣豆",
            )
        g2 = _IgHelpers.create_intercom_group(
            http, base_url, auth_headers, _IgHelpers.replace_ts("IG_OB_{ts}"),
        )
        before = _IgHelpers.global_balance(http, base_url, auth_headers)
        inv_f = http.send_request(
            "post", f"{base_url}/api/monitor/intercom/group/invitation",
            json={"intercomGroupId": g2, "addrInfos": [{"addr": sn}], "force": False},
            headers=auth_headers, case_name="自己棒force假", log_level="none",
        )
        jf = parse_response_json(inv_f, context="自己棒force假")
        after_f = _IgHelpers.global_balance(http, base_url, auth_headers)
        _IgHelpers.report_extra_and_assert("自己棒 force=false", [
            {"项": "code", "期望": 0, "实际": jf["code"],
             "通过": jf["code"] == 0},
            {"项": "confirm", "期望": 0, "实际": _jp_first(jf, "$.data.confirm"),
             "通过": _jp_first(jf, "$.data.confirm") == 0},
            {"项": "仍在G1", "期望": sn, "实际": _IgHelpers.list_member_addrs(
                http, base_url, auth_headers, g1),
             "通过": sn in _IgHelpers.list_member_addrs(http, base_url, auth_headers, g1)},
            {"项": "未入G2", "期望": f"{sn} 不在", "实际": _IgHelpers.list_member_addrs(
                http, base_url, auth_headers, g2),
             "通过": sn not in _IgHelpers.list_member_addrs(http, base_url, auth_headers, g2)},
            {"项": "不扣豆", "期望": before, "实际": after_f, "通过": after_f == before},
        ], f"force=false confirm=0 留原群 余额{before}→{after_f}")
        before_t = _IgHelpers.global_balance(http, base_url, auth_headers)
        inv_t = http.send_request(
            "post", f"{base_url}/api/monitor/intercom/group/invitation",
            json={"intercomGroupId": g2, "addrInfos": [{"addr": sn}], "force": True},
            headers=auth_headers, case_name="自己棒force真", log_level="none",
        )
        jt = parse_response_json(inv_t, context="自己棒force真")
        g1_after = _IgHelpers.list_member_addrs(http, base_url, auth_headers, g1)
        g2_after = _IgHelpers.list_member_addrs(http, base_url, auth_headers, g2)
        _IgHelpers.report_extra_and_assert("自己棒 force=true", [
            {"项": "code", "期望": 0, "实际": jt["code"],
             "通过": jt["code"] == 0},
            {"项": "confirm", "期望": 1, "实际": _jp_first(jt, "$.data.confirm"),
             "通过": _jp_first(jt, "$.data.confirm") == 1},
            {"项": "已退G1", "期望": f"{sn} 不在", "实际": g1_after,
             "通过": sn not in g1_after},
            {"项": "已入G2", "期望": sn, "实际": g2_after, "通过": sn in g2_after},
        ], f"force=true 静默换群 confirm={_jp_first(jt, '$.data.confirm')}")
        if _COST["inviteMemberDeductEnabled"]:
            _IgHelpers.wait_new_deduction(
                http, base_url, auth_headers, "INVITE_MEMBER",
                _COST["inviteMemberDeductBeans"], before_t, "自己棒换群扣豆",
            )


class TestIg14FullGroup:
    """独立群邀满 remainder.maxMembers 后再邀一台：拦截且不扣费。"""

    @pytest.mark.parametrize("case", _TEST_DATA["intercom_full_invite_cases"])
    def test_full_invite(self, base_url, auth_headers, group_fixture, case):
        http = BaseRequest()
        gid = _IgHelpers.create_intercom_group(
            http, base_url, auth_headers, _IgHelpers.replace_ts("IG_FU_{ts}"),
        )
        rem = http.send_request(
            "get", f"{base_url}/api/monitor/intercom/group/remainder",
            params={"intercomGroupId": gid}, headers=auth_headers,
            case_name="满员群额度", log_level="none",
        )
        remainder_data = parse_response_json(rem, context="满员群额度")
        cap = _jp_first(remainder_data, "$.data.maxMembers")
        if not isinstance(cap, int) or cap < 1:
            pytest.skip(f"maxMembers 不可用: {cap}")
        one_id = group_fixture["one_id"]
        fill = []
        for _ in range(cap):
            fill.append(_IgHelpers.provision_rescue_stick(
                http, base_url, auth_headers, one_id,
            ))
        extra = _IgHelpers.provision_rescue_stick(http, base_url, auth_headers, one_id)
        for sn in fill:
            before_i = _IgHelpers.global_balance(http, base_url, auth_headers)
            inv = http.send_request(
                "post", f"{base_url}/api/monitor/intercom/group/invitation",
                json={"intercomGroupId": gid, "addrInfos": [{"addr": sn}], "force": False},
                headers=auth_headers, case_name=f"满员填入 {sn}", log_level="none",
            )
            fill_data = parse_response_json(inv, context=f"满员填入 {sn}")
            if fill_data["code"] != 0:
                raise AssertionError(f"满员填入失败 {sn}: {fill_data}")
            if _COST["inviteMemberDeductEnabled"]:
                _IgHelpers.wait_new_deduction(
                    http, base_url, auth_headers, "INVITE_MEMBER",
                    _COST["inviteMemberDeductBeans"], before_i, f"满员填入扣豆 {sn}",
                )
        listed = _IgHelpers.list_member_addrs(http, base_url, auth_headers, gid)
        em = (case.get("expected") or {}).get("error_msg") or ""
        case = {**case, "expected": {**case["expected"],
                "error_msg": em.replace("{maxMembers}", str(cap))}}
        before = _IgHelpers.global_balance(http, base_url, auth_headers)
        body = {"intercomGroupId": gid, "addrInfos": [{"addr": extra}], "force": False}
        json_data = _IgHelpers.send(
            http, "post", f"{base_url}/api/monitor/intercom/group/invitation",
            case, _IgHelpers.headers(auth_headers, case), json=body,
        )
        code, _ = _IgHelpers.assert_case(case, json_data, {"请求参数": body})
        after = _IgHelpers.global_balance(http, base_url, auth_headers)
        listed2 = _IgHelpers.list_member_addrs(http, base_url, auth_headers, gid)
        _IgHelpers.report_extra_and_assert("满员拦截", [
            {"项": "maxMembers", "期望": "int≥1", "实际": cap, "通过": True},
            {"项": "填入后人数", "期望": cap, "实际": len(listed),
             "通过": len(listed) == cap},
            {"项": "超员后人数", "期望": cap, "实际": len(listed2),
             "通过": len(listed2) == cap and extra not in listed2},
            {"项": "余额未变", "期望": before, "实际": after, "通过": after == before},
            {"项": "code", "期望": 1001, "实际": code, "通过": code == 1001},
        ], f"满员拦截 cap={cap} code={code} 余额{before}→{after}")


