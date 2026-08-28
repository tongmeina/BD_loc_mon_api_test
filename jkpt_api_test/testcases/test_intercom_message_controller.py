# testcases/test_intercom_message_controller.py
"""对讲群消息域 4 口（message/page、receive/info、clear/unread、clear/all-unread）

计划：plan/intercom-message-tests.plan.md；现网基线 §6（2026-08-20 探针 S0~S6 实测）。

执行序锁死（类定义序 = 执行序，禁 pytest-xdist）：
    Im00 造数自检 → Im01 分页（读）→ Im02 接收列表（读）
    → Im03 清群未读（写）→ Im04 清所有未读（写）→ Im05 关群/删群后形态
读侧的未读断言必须早于 clear 系；Im05 会 close+delete 造数群（消费完即注销 cleaner）。

现网口径备忘（与计划初稿的预设不同，勿凭直觉改回去）：
    - 终端 SOS 位置上报在对讲群落库为 sendType=TEXT（不是 ALARM），语音为 VOICE
    - 消息级 readCount/unreadCount/failCount 恒 0，receive/info 三列表恒空——
      已读明细现网未落地，双账号已读只能做「留痕」断言（见 Im02 read_transition）
    - 未读是「聊天项级」：clear/unread 清的是 platform-chats/chat-item 的 unreadNum，
      消息级计数不动；clear/all-unread 的 data 是本次清掉的聊天项数
    - 消息域全口无越权拦截：B 账号（非群成员）可读可清，均 code=0（缺陷留痕）
"""
import math
import time

import pytest
import requests

from common.case_report_util import (
    assert_case,
    case_headers,
    jp_first,
    jp_list,
    report_extra_and_assert,
    send_case,
)
from common.cleanup import intercom_group
from common.logger_util import key
from common.requests_util import BaseRequest, parse_response_json
from common.star_bean_util import latest_balance
from common.yaml_util import (
    is_extract_placeholder,
    read_yaml,
    resolve_extract_value,
    write_yaml,
)

_TEST_DATA = read_yaml("./yaml/test_intercom_message_controller.yaml")

# 终端上行在对讲群产生的两类消息（IMAGE/OK/ALARM 协议不可造，本期不覆盖）
_EXPECT_SEND_TYPES = {"TEXT", "VOICE"}
# 双群一致性：同一条消息在 SOS 侧与对讲群侧 chatTime 允许的毫秒偏差（实测 ~20ms）。
# 勿放宽：三设备时序下心跳/取消记录与 VOICE 间隔可能 <5s，5000ms 会误判泄漏。
_CHAT_TIME_TOLERANCE_MS = 100


class _ImHelpers:
    """共享逻辑；不以 Test 开头，pytest 不收集。"""

    @staticmethod
    def resolve_id(case, field):
        """正向 `{{...}}` 走 extract（缺值 skip）；负向字面量原样返回。"""
        raw = case.get(field)
        if is_extract_placeholder(raw):
            return resolve_extract_value(raw, required=True)
        return raw

    @staticmethod
    def _get_json(http, url, headers, params, name):
        """辅助 GET。连接被远端掐掉时重试 1 次（不改断言口径）。

        现网回归见过：主请求已 200 后，紧跟着的「首页基线」查询被对端断开
        （RemoteDisconnected），整条用例误红。辅助查询允许 1 次重试。
        """
        last_err = None
        for attempt in range(2):
            try:
                res = http.send_request(
                    "get", url, params=params, headers=headers,
                    case_name=name, log_level="none",
                )
                return parse_response_json(res, context=name)
            except requests.exceptions.ConnectionError as e:
                last_err = e
                key("辅助查询重试", f"{name} 第{attempt + 1}次连接中断，1s 后重试")
                time.sleep(1)
        raise last_err

    @staticmethod
    def page(http, base_url, headers, gid, *, page=1, size=100, name="查消息分页"):
        return _ImHelpers._get_json(
            http, f"{base_url}/api/monitor/intercom/message/page", headers,
            {"intercomGroupId": gid, "page": page, "pageSize": size}, name,
        )

    @staticmethod
    def live_message_id(case, field, seed):
        """正向消息 id 兜底：extract 里的 id 不属于本轮造数群时改用本轮首条。

        单独跑 Im02 而不跑 Im01 时，extract 可能残留上一轮（已 delete 的群）的
        消息 id，直接用会拿到空明细而误判。
        """
        mid = _ImHelpers.resolve_id(case, field)
        if is_extract_placeholder(case.get(field)) and mid not in seed["messageIds"]:
            key("消息 id 兜底", f"extract {mid} 不属本轮造数群，改用 {seed['messageIds'][0]}")
            return seed["messageIds"][0]
        return mid

    @staticmethod
    def message_by_id(http, base_url, headers, gid, mid):
        """从 message/page 里取指定消息（消息级计数与 receive/info 交叉验证用）。"""
        data = _ImHelpers.page(http, base_url, headers, gid, name="查消息计数")
        return next((m for m in jp_list(data, "$.data.items[*]")
                     if m.get("id") == mid), None)

    @staticmethod
    def chat_items(http, base_url, headers, *, item_name=None, name="查聊天项"):
        """platform-chats/chat-item/page 的 GROUP 项——未读数的第二证据源。

        实测：GROUP 项的 `id` 就是对讲群 id；`itemName` 入参按群名过滤。
        """
        params = {"page": 1, "pageSize": 50, "chatItemType": "GROUP"}
        if item_name:
            params["itemName"] = item_name
        data = _ImHelpers._get_json(
            http, f"{base_url}/api/monitor/platform-chats/chat-item/page",
            headers, params, name,
        )
        return jp_list(data, "$.data.items[*]")

    @staticmethod
    def unread_num(http, base_url, headers, group_name, gid, *, name="查群未读数"):
        items = _ImHelpers.chat_items(
            http, base_url, headers, item_name=group_name, name=name,
        )
        hit = next((i for i in items if str(i.get("id")) == str(gid)), None)
        return (hit or {}).get("unreadNum"), hit

    @staticmethod
    def remainder_status(http, base_url, headers, gid, name="查群状态"):
        data = _ImHelpers._get_json(
            http, f"{base_url}/api/monitor/intercom/group/remainder",
            headers, {"intercomGroupId": gid}, name,
        )
        return jp_first(data, "$.data.status")

    @staticmethod
    def read_transition_setup(http, base_url, auth_headers, request, seed):
        """B 成员侧触发已读动作，返回留痕行（三设备造数后 B棒4 已在群内）。

        现网实测（2026-08-20）：B 成员侧 clear/unread 后，消息级 readCount/unreadCount
        仍恒 0、receive/info 三列表仍为空——已读明细未落地，故本支路只做「留痕 + 成员侧
        查询等价性」断言，不写 readCount 增 1 的臆造期望（计划 §4.3 case0a 降级条款）。
        """
        headers_b = request.getfixturevalue("auth_headers_b")
        sn_c = seed["devices"]["voice"]["sn"]
        gid = seed["group"]["id"]
        member_response = http.send_request(
            "get", f"{base_url}/api/monitor/intercom/group/terminal/list",
            params={"intercomGroupId": gid}, headers=auth_headers,
            case_name="消息域B成员复核", log_level="none",
        )
        member_data = parse_response_json(member_response, context="消息域B成员复核")
        members = jp_list(member_data, "$.data[*].addr")
        b_count = len(jp_list(
            _ImHelpers.page(http, base_url, headers_b, gid, name="B成员侧查消息"),
            "$.data.items[*]",
        ))
        clear_b = http.send_request(
            "put", f"{base_url}/api/monitor/intercom/message/clear/unread",
            params={"intercomGroupId": gid}, headers=headers_b,
            case_name="B侧清未读触发已读", log_level="none",
        )
        clear_data = parse_response_json(clear_b, context="B侧清未读触发已读")
        clear_code = clear_data["code"]
        time.sleep(2)
        key("B 侧已读触发", f"clear={clear_code}")
        return [
            {"项": "B 棒在成员列表（造数已入群）", "期望": sn_c, "实际": members,
             "通过": sn_c in members},
            {"项": "B 成员侧可见条数", "期望": len(seed["messageIds"]), "实际": b_count,
             "通过": b_count == len(seed["messageIds"])},
            {"项": "B 侧 clear/unread", "期望": 0, "实际": clear_code,
             "通过": clear_code == 0},
        ]

    @staticmethod
    def structure_rows(data):
        """信封内 PageResult 结构：items 是 list，total/totalPage 是 int。"""
        items = data.get("items")
        total = data.get("total")
        total_page = data.get("totalPage")
        return [
            {"项": "data.items 类型", "期望": "list", "实际": type(items).__name__,
             "通过": isinstance(items, list)},
            {"项": "data.total 类型", "期望": "int", "实际": f"{total}({type(total).__name__})",
             "通过": isinstance(total, int)},
            {"项": "data.totalPage 类型", "期望": "int",
             "实际": f"{total_page}({type(total_page).__name__})",
             "通过": isinstance(total_page, int)},
        ]


@pytest.fixture(scope="session", autouse=True)
def _im_star_bean_gate(base_url, auth_headers):
    """余额闸门：<200 豆则本文件全 skip（造数 30 豆 + B棒4 入群 10 豆）。"""
    bal = latest_balance(BaseRequest(), base_url, auth_headers)
    key("A账号星豆余额", bal)
    if bal is not None and bal < 200:
        pytest.skip(f"A 账号星豆 {bal} < 200，请充值后再跑对讲群消息用例")


class TestIm00FixtureChain:
    """造数链自检（非接口）：群/三设备成员/三角色消息/双SOS群/群状态。"""

    def test_fixture_chain(self, base_url, auth_headers, intercom_message_group):
        seed = intercom_message_group
        http = BaseRequest()
        gid = seed["group"]["id"]
        devices = seed["devices"]
        msgs = seed["messagesByRole"]
        member_set = set(seed["group"]["members"])
        expected_members = {d["sn"] for d in devices.values()}
        assert gid, "造数群 id 为空"
        for role, info in devices.items():
            assert info["sn"] in member_set, \
                f"造数棒未真入群: role={role} sn={info['sn']} members={sorted(member_set)}"
        assert member_set == expected_members, \
            f"成员集合不是三设备: expected={sorted(expected_members)} actual={sorted(member_set)}"
        for role, expect_type, expect_sn in (
            ("key_sos", "TEXT", devices["key_sos"]["sn"]),
            ("water_sos", "TEXT", devices["water_sos"]["sn"]),
            ("voice", "VOICE", devices["voice"]["sn"]),
        ):
            message = msgs[role]
            assert message and message.get("id"), f"缺 {role} 消息"
            assert message.get("sendType") == expect_type, \
                f"{role} sendType 期望 {expect_type} 实际 {message.get('sendType')}"
            sender = str((message.get("avatarInfo") or {}).get("memberAccount"))
            assert sender == str(expect_sn), \
                f"{role} 发送者期望 {expect_sn} 实际 {sender}"
        for role, group in seed["sosGroups"].items():
            assert group["chatItemId"], f"缺 {role} SOS 群"
            assert group["statusAfterEnd"] == 0, \
                f"{role} SOS 结束后 status 期望 0 实际 {group['statusAfterEnd']}"
        status = _ImHelpers.remainder_status(http, base_url, auth_headers, gid, "造数群状态")
        assert status == 1, f"造数群应活跃(status=1)，实际 {status}"
        write_yaml("./extract.yaml", {"im_group_id": gid}, mode="append")
        write_yaml("./extract.yaml", {"im_message_id": msgs["voice"]["id"]}, mode="append")
        key("extract", f"im_group_id={gid} im_message_id={msgs['voice']['id']}")
        key("造数事实", f"群 {seed['group']['name']} / 三设备 "
                        f"{[d['sn'] for d in devices.values()]} / "
                        f"耗时 {seed['timing']['total']:.0f}s / "
                        f"SOS {list(seed['sosGroups'])}")


class TestIm01Page:
    """GET /intercom/message/page — 分页获取对讲群聊天消息记录"""

    @pytest.mark.parametrize("case", _TEST_DATA["intercom_msg_page_cases"])
    def test_page(self, base_url, auth_headers, intercom_message_group, case, request):
        http = BaseRequest()
        url = f"{base_url}/api/monitor/intercom/message/page"
        seed = intercom_message_group
        scenario = case.get("scenario")
        headers = auth_headers
        if scenario == "cross_account":
            headers = request.getfixturevalue("auth_headers_b")
        gid = _ImHelpers.resolve_id(case, "intercomGroupId")
        params = {}
        if gid is not None:
            params["intercomGroupId"] = gid
        if "page" in case:
            params["page"] = case["page"]
        if "page_size" in case:
            params["pageSize"] = case["page_size"]
        json_data = send_case(
            http, "get", url, case, case_headers(headers, case), params=params,
        )
        if scenario == "page_size_illegal":
            code = json_data["code"]
            msg = json_data.get("msg") or ""
            report_extra_and_assert("pageSize 非法类型", [
                {"项": "code", "期望": 1001, "实际": code, "通过": code == 1001},
                {"项": "msg 命中字段名", "期望": "含 pageSize", "实际": msg[:60],
                 "通过": "pageSize" in msg},
            ], f"非法 pageSize 被拦截 code={code}")
            return
        code, _ = assert_case(case, json_data, {"请求参数": params})
        if code != 0:
            return
        data = jp_first(json_data, "$.data") or {}
        items = data.get("items") or []
        total = data.get("total")
        rows = _ImHelpers.structure_rows(data)

        if scenario == "positive":
            bad_group = [m.get("id") for m in items
                         if str(m.get("groupId")) != str(gid)]
            bad_type = [m.get("sendType") for m in items
                        if m.get("sendType") not in _EXPECT_SEND_TYPES]
            bad_time = [m.get("chatTime") for m in items
                        if not (isinstance(m.get("chatTime"), int)
                                and len(str(m.get("chatTime"))) == 13)]
            rows += [
                {"项": "条数", "期望": "≥3（造数 2 TEXT + 1 VOICE）", "实际": len(items),
                 "通过": len(items) >= 3},
                {"项": "全部 id 非空", "期望": "非空",
                 "实际": f"缺 {sum(1 for m in items if not m.get('id'))} 条",
                 "通过": all(m.get("id") for m in items)},
                {"项": "不串群", "期望": f"groupId 全为 {gid}", "实际": bad_group,
                 "通过": not bad_group},
                {"项": "sendType 枚举", "期望": sorted(_EXPECT_SEND_TYPES),
                 "实际": bad_type or [m.get("sendType") for m in items],
                 "通过": not bad_type},
                {"项": "chatTime 毫秒级", "期望": "13 位 int", "实际": bad_time,
                 "通过": not bad_time},
            ]
            report_extra_and_assert(
                "分页正向", rows,
                f"{len(items)} 条 {[m.get('sendType') for m in items]} total={total}",
            )
            if items:
                write_yaml("./extract.yaml",
                           {"im_message_id": items[0]["id"]}, mode="append")
                key("extract im_message_id", items[0]["id"])
            return

        if scenario == "field_shape":
            devices = seed["devices"]
            texts = [m for m in items if m.get("sendType") == "TEXT"]
            voices = [m for m in items if m.get("sendType") == "VOICE"]
            no_loc = [m.get("id") for m in texts
                      if not (m.get("loc") or {}).get("lng")]
            bad_voice = [m.get("id") for m in voices
                         if not (isinstance(m.get("fileSize"), int)
                                 and m["fileSize"] > 0 and m.get("content"))]
            expect_sender = {str(m["id"]): str(d["sn"])
                             for m, d in (
                                 (seed["messagesByRole"]["key_sos"], devices["key_sos"]),
                                 (seed["messagesByRole"]["water_sos"], devices["water_sos"]),
                                 (seed["messagesByRole"]["voice"], devices["voice"]),
                             )}
            bad_sender = [
                (m.get("id"), (m.get("avatarInfo") or {}).get("memberAccount"))
                for m in items
                if expect_sender.get(str(m.get("id")))
                != str((m.get("avatarInfo") or {}).get("memberAccount"))
            ]
            rows += [
                {"项": "TEXT 带定位", "期望": "loc.lng 非空", "实际": no_loc,
                 "通过": bool(texts) and not no_loc},
                {"项": "VOICE 时长与内容", "期望": "fileSize>0 且 content 非空",
                 "实际": bad_voice or [(m.get("fileSize"), str(m.get("content"))[:12])
                                       for m in voices],
                 "通过": bool(voices) and not bad_voice},
                {"项": "三设备发送者精确映射", "期望": "按 messagesByRole",
                 "实际": bad_sender or "全部命中", "通过": not bad_sender},
            ]
            report_extra_and_assert(
                "字段级校验", rows,
                f"TEXT {len(texts)} 条带定位、VOICE {len(voices)} 条带时长，"
                f"发送者按角色映射 {sorted(expect_sender.values())}",
            )
            return

        if scenario == "dual_group_consistency":
            leaked = []
            for role, group in seed["sosGroups"].items():
                rec = group["records"]
                times = [t for t in (rec.get("chatTimes") or []) if isinstance(t, int)]
                leaked += [
                    (role, item.get("id"))
                    for item in rec.get("items") or []
                    if item.get("sendType") == "VOICE"
                ]
                sn = str(group["terminalSn"])

                def matched(t, pool):
                    return any(abs(t - p) <= _CHAT_TIME_TOLERANCE_MS for p in pool)

                text_times = [
                    m["chatTime"] for m in items
                    if m.get("sendType") == "TEXT"
                    and str((m.get("avatarInfo") or {}).get("memberAccount")) == sn
                ]
                unmatched = [t for t in text_times if not matched(t, times)]
                extra = (rec.get("total") or 0) - len(text_times)
                # SOS 侧在结束跃迁时可能追加 1 条系统状态 TEXT；它不是对讲群消息泄漏。
                allow_extra = extra <= 1
                rows += [
                    {"项": f"{role} SOS 有记录", "期望": "≥1", "实际": rec.get("total"),
                     "通过": isinstance(rec.get("total"), int) and rec["total"] >= 1},
                    {"项": f"{role} TEXT 双落", "期望": "对讲群该设备 TEXT 能在 SOS 侧对上",
                     "实际": unmatched or f"{len(text_times)} 条命中",
                     "通过": bool(text_times) and not unmatched},
                    {"项": f"{role} SOS 侧多出",
                     "期望": "≤1 条 SOS 系统状态 TEXT",
                     "实际": extra, "通过": allow_extra},
                ]
            rows.append({
                "项": "VOICE 不落 SOS", "期望": "无泄漏", "实际": leaked or "无泄漏",
                "通过": not leaked,
            })
            report_extra_and_assert(
                "双群一致性", rows,
                f"按设备核对 SOS 双落；VOICE 泄漏={leaked or '无'}",
            )
            return

        if scenario == "zero_growth":
            snaps = seed["snapshots"]
            bad_type = [m.get("sendType") for m in items
                        if m.get("sendType") not in _EXPECT_SEND_TYPES]
            rows += [
                {"项": "心跳(flag=0)零增长", "期望": snaps["afterSos"],
                 "实际": snaps["afterClose"],
                 "通过": snaps["afterClose"] == snaps["afterSos"]},
                {"项": "取消SOS(flag=10)零增长", "期望": snaps["afterSos"],
                 "实际": snaps["afterClose"],
                 "通过": snaps["afterClose"] == snaps["afterSos"]},
                {"项": "语音才增长", "期望": snaps["afterClose"] + 1,
                 "实际": snaps["speech"],
                 "通过": snaps["speech"] == snaps["afterClose"] + 1},
                {"项": "当前 total 与造数末态一致", "期望": snaps["speech"],
                 "实际": total, "通过": total == snaps["speech"]},
                {"项": "无非预期消息类型", "期望": sorted(_EXPECT_SEND_TYPES),
                 "实际": bad_type or "无", "通过": not bad_type},
            ]
            report_extra_and_assert(
                "心跳/取消零增长", rows,
                f"total 轨迹 {snaps['baseline']}→{snaps['afterSos']}"
                f"→{snaps['afterClose']}→{snaps['speech']}",
            )
            return

        if scenario == "paging_conserve":
            all_ids = [m.get("id") for m in items]
            for size in (1, 2):
                pages = math.ceil(len(all_ids) / size)
                walked, per_page = [], []
                first_total, first_total_page = None, None
                for p in range(1, pages + 1):
                    body = _ImHelpers.page(
                        http, base_url, auth_headers, gid,
                        page=p, size=size, name=f"守恒 size={size} page={p}",
                    )
                    page_items = jp_list(body, "$.data.items[*]")
                    walked += [m.get("id") for m in page_items]
                    per_page.append(len(page_items))
                    if first_total is None:
                        first_total = jp_first(body, "$.data.total")
                        first_total_page = jp_first(body, "$.data.totalPage")
                    else:
                        rows.append({
                            "项": f"size={size} 各页 total 一致", "期望": first_total,
                            "实际": jp_first(body, "$.data.total"),
                            "通过": jp_first(body, "$.data.total") == first_total,
                        })
                expect_per_page = [
                    min(size, len(all_ids) - (p - 1) * size) for p in range(1, pages + 1)
                ]
                rows += [
                    {"项": f"size={size} 各页条数", "期望": expect_per_page,
                     "实际": per_page, "通过": per_page == expect_per_page},
                    {"项": f"size={size} 无重复", "期望": f"{len(all_ids)} 个唯一 id",
                     "实际": f"{len(set(walked))}/{len(walked)}",
                     "通过": len(set(walked)) == len(walked)},
                    {"项": f"size={size} 无遗漏", "期望": "并集 == 全量 id 集",
                     "实际": f"{len(set(walked) & set(all_ids))}/{len(all_ids)}",
                     "通过": set(walked) == set(all_ids)},
                    {"项": f"size={size} totalPage", "期望": math.ceil(len(all_ids) / size),
                     "实际": first_total_page,
                     "通过": first_total_page == math.ceil(len(all_ids) / size)},
                ]
            report_extra_and_assert(
                "分页守恒", rows,
                f"{len(all_ids)} 条消息按 size=1/2 遍历，条数/唯一性/并集/totalPage 全对",
            )
            return

        if scenario == "page_overflow":
            rows += [
                {"项": "items 为空列表", "期望": "[]（非 null、非报错）",
                 "实际": items, "通过": isinstance(data.get("items"), list) and not items},
                {"项": "total 不变", "期望": seed["snapshots"]["speech"], "实际": total,
                 "通过": total == seed["snapshots"]["speech"]},
            ]
            report_extra_and_assert(
                "页码超界", rows, f"page=9999 返回空列表，total 仍为 {total}",
            )
            return

        if scenario == "page_fallback":
            head = _ImHelpers.page(
                http, base_url, auth_headers, gid, page=1,
                size=case.get("page_size", 10), name="首页基线",
            )
            head_ids = [m.get("id") for m in jp_list(head, "$.data.items[*]")]
            rows += [
                {"项": "与首页同结果", "期望": head_ids, "实际": [m.get("id") for m in items],
                 "通过": [m.get("id") for m in items] == head_ids},
                {"项": "total 不变", "期望": seed["snapshots"]["speech"], "实际": total,
                 "通过": total == seed["snapshots"]["speech"]},
            ]
            report_extra_and_assert(
                "非法页码回落首页", rows,
                f"page={case.get('page')} 等价首页，{len(items)} 条",
            )
            return

        if scenario == "page_size_negative":
            rows += [
                {"项": "返回全量", "期望": total, "实际": len(items),
                 "通过": len(items) == total},
                {"项": "total 不变", "期望": seed["snapshots"]["speech"], "实际": total,
                 "通过": total == seed["snapshots"]["speech"]},
            ]
            report_extra_and_assert(
                "pageSize=-1 当默认处理", rows, f"pageSize=-1 返回全量 {len(items)} 条",
            )
            return

        if scenario == "cross_account":
            rows += [
                {"项": "B 侧可见条数", "期望": f"A 侧 {seed['snapshots']['speech']} 条",
                 "实际": len(items), "通过": len(items) == seed["snapshots"]["speech"]},
                {"项": "越权拦截", "期望": "现网无拦截（缺陷留痕）",
                 "实际": f"code=0，B 可读 {len(items)} 条", "通过": True},
            ]
            report_extra_and_assert(
                "跨账号越权查询", rows,
                f"B 账号可读 A 群全部 {len(items)} 条消息（无拦截，已留痕）",
            )
            return

        report_extra_and_assert("分页结构", rows, f"结构合规 total={total}")


class TestIm02ReceiveInfo:
    """GET /intercom/message/receive/info — 消息接收列表（已读/未读/失败明细）"""

    @pytest.mark.parametrize("case", _TEST_DATA["intercom_msg_receive_info_cases"])
    def test_receive_info(self, base_url, auth_headers, intercom_message_group,
                          case, request):
        http = BaseRequest()
        url = f"{base_url}/api/monitor/intercom/message/receive/info"
        seed = intercom_message_group
        scenario = case.get("scenario")
        mid = _ImHelpers.live_message_id(case, "intercomMessageId", seed)
        pre_rows = []
        if scenario == "read_transition":
            pre_rows = _ImHelpers.read_transition_setup(
                http, base_url, auth_headers, request, seed,
            )
        params = {}
        if mid is not None:
            params["intercomMessageId"] = mid
        if scenario == "cross_account":
            params["intercomMessageId"] = seed["accessSnapshots"]["bNonMemberReceiveMessageId"]
            response = seed["accessSnapshots"]["bNonMemberReceiveResponse"]
            json_data = parse_response_json(response, context=case["name"])
            from common.logger_util import print_request, print_response, sep
            sep(f" 测试用例: {case['name']}")
            print_request("GET", url, params=params, headers=request.getfixturevalue("auth_headers_b"))
            print_response(response)
        else:
            json_data = send_case(
                http, "get", url, case, case_headers(auth_headers, case), params=params,
            )
        code, _ = assert_case(case, json_data, {"请求参数": params})
        if code != 0:
            return
        data = jp_first(json_data, "$.data") or {}
        lists = {k: data.get(k) for k in ("readList", "unreadList", "failList")}
        rows = [
            {"项": f"{k} 是 list", "期望": "list", "实际": type(v).__name__,
             "通过": isinstance(v, list)}
            for k, v in lists.items()
        ]

        if scenario == "fake_id":
            rows.append({
                "项": "三列表均空", "期望": "假/空消息 id 返回三空列表（实测非 3003）",
                "实际": {k: len(v or []) for k, v in lists.items()},
                "通过": all(not v for v in lists.values()),
            })
            report_extra_and_assert(
                "假消息 id 形态", rows, "假消息 id 返回 code=0 + 三空列表",
            )
            return

        if scenario == "cross_account":
            rows.append({
                "项": "越权拦截", "期望": "现网无拦截（缺陷留痕，造数期非成员快照）",
                "实际": "code=0，B 可查 A 群消息接收明细", "通过": True,
            })
            report_extra_and_assert(
                "跨账号越权查接收", rows, "B 账号可查 A 群消息接收明细（无拦截，已留痕）",
            )
            return

        msg_row = _ImHelpers.message_by_id(
            http, base_url, auth_headers, seed["group"]["id"], mid,
        ) or {}
        counts = {"readList": msg_row.get("readCount"),
                  "unreadList": msg_row.get("unreadCount"),
                  "failList": msg_row.get("failCount")}
        rows += [
            {"项": f"{k} 长度 == 消息 {k.replace('List', 'Count')}",
             "期望": counts[k], "实际": len(v or []),
             "通过": len(v or []) == counts[k]}
            for k, v in lists.items()
        ]
        rows.append({
            "项": "已读明细落地情况",
            "期望": "记录项（现网消息级计数恒 0、三列表恒空）",
            "实际": f"counts={counts} lens="
                    f"{ {k: len(v or []) for k, v in lists.items()} }",
            "通过": True,
        })
        report_extra_and_assert(
            "接收列表交叉一致性", pre_rows + rows,
            f"三列表长度与消息级计数一致（均为 {counts}）",
        )


class TestIm03ClearUnread:
    """PUT /intercom/message/clear/unread — 清群聊未读数量（聊天项级）"""

    @pytest.mark.parametrize("case", _TEST_DATA["intercom_msg_clear_unread_cases"])
    def test_clear_unread(self, base_url, auth_headers, intercom_message_group, case):
        http = BaseRequest()
        url = f"{base_url}/api/monitor/intercom/message/clear/unread"
        seed = intercom_message_group
        scenario = case.get("scenario")
        gid = _ImHelpers.resolve_id(case, "intercomGroupId")
        params = {}
        if gid is not None:
            params["intercomGroupId"] = gid
        before_unread = before_counts = None
        if scenario in ("positive", "idempotent"):
            before_unread, _ = _ImHelpers.unread_num(
                http, base_url, auth_headers, seed["group"]["name"], gid, name="清前未读数",
            )
            before_counts = [(m.get("unreadCount"), m.get("readCount"))
                             for m in jp_list(_ImHelpers.page(
                                 http, base_url, auth_headers, gid, name="清前消息计数",
                             ), "$.data.items[*]")]
        json_data = send_case(
            http, "put", url, case, case_headers(auth_headers, case), params=params,
        )
        code, _ = assert_case(case, json_data, {"请求参数": params})
        if code != 0:
            return

        if scenario == "fake_group":
            report_extra_and_assert("假群 id 不拦截", [
                {"项": "后端校验", "期望": "现网不校验群存在（留痕：与 page 的 3003 不一致）",
                 "实际": "code=0", "通过": True},
            ], "假群 id 清未读返回 code=0（已留痕）")
            return

        if scenario not in ("positive", "idempotent"):
            return
        time.sleep(2)
        after_unread, item = _ImHelpers.unread_num(
            http, base_url, auth_headers, seed["group"]["name"], gid, name="清后未读数",
        )
        after_counts = [(m.get("unreadCount"), m.get("readCount"))
                        for m in jp_list(_ImHelpers.page(
                            http, base_url, auth_headers, gid, name="清后消息计数",
                        ), "$.data.items[*]")]
        rows = [
            {"项": "聊天项存在", "期望": f"id={gid}", "实际": (item or {}).get("id"),
             "通过": item is not None},
            {"项": "清后 unreadNum", "期望": 0, "实际": after_unread,
             "通过": after_unread == 0},
            {"项": "消息级计数不受影响", "期望": before_counts, "实际": after_counts,
             "通过": after_counts == before_counts},
        ]
        if scenario == "positive":
            rows.append({
                "项": "清前 unreadNum", "期望": "≥1（造数消息未读）", "实际": before_unread,
                "通过": isinstance(before_unread, int) and before_unread >= 1,
            })
            summary = f"聊天项未读 {before_unread}→{after_unread}，消息级计数不变"
        else:
            rows.append({
                "项": "幂等-清前已为 0", "期望": 0, "实际": before_unread,
                "通过": before_unread == 0,
            })
            summary = f"重复清未读仍为 {after_unread}（不回涨、不报错）"
        report_extra_and_assert("清群未读数据往返", rows, summary)


class TestIm04ClearAllUnread:
    """PUT /intercom/message/clear/all-unread — 清空所有对讲群未读（无业务参数）"""

    @pytest.mark.parametrize("case", _TEST_DATA["intercom_msg_clear_all_unread_cases"])
    def test_clear_all_unread(self, base_url, auth_headers, intercom_message_group, case):
        http = BaseRequest()
        url = f"{base_url}/api/monitor/intercom/message/clear/all-unread"
        scenario = case.get("scenario")
        json_data = send_case(
            http, "put", url, case, case_headers(auth_headers, case),
        )
        code, _ = assert_case(case, json_data, {"请求参数": {}})
        if code != 0:
            return
        cleared = jp_first(json_data, "$.data")
        time.sleep(2)
        groups = _ImHelpers.chat_items(http, base_url, auth_headers, name="清后全量聊天项")
        left = [(g.get("id"), g.get("unreadNum")) for g in groups if g.get("unreadNum")]
        rows = [
            {"项": "data 类型", "期望": "int（本次清掉的聊天项数）",
             "实际": f"{cleared}({type(cleared).__name__})",
             "通过": isinstance(cleared, int) and cleared >= 0},
            {"项": "A 侧 GROUP 项全部归零", "期望": "无残留未读",
             "实际": left or f"{len(groups)} 项全 0", "通过": not left},
        ]
        if scenario == "idempotent":
            rows.append({
                "项": "幂等-二次清理数", "期望": 0, "实际": cleared,
                "通过": cleared == 0,
            })
            summary = f"二次清所有未读返回 {cleared}（已无可清）"
        else:
            summary = f"清所有未读 data={cleared}，{len(groups)} 个 GROUP 项未读全 0"
        report_extra_and_assert("清所有未读", rows, summary)


class TestIm05StateAfterCloseDelete:
    """关群 / 删群后消息域形态（放最后：会 close+delete 造数群并注销 cleaner）"""

    @pytest.mark.parametrize("case", _TEST_DATA["intercom_msg_state_cases"])
    def test_state(self, base_url, auth_headers, intercom_message_group, case):
        http = BaseRequest()
        seed = intercom_message_group
        gid = seed["group"]["id"]
        scenario = case.get("scenario")
        pre_rows = []
        if scenario == "after_close":
            res = http.send_request(
                "put", f"{base_url}/api/monitor/intercom/group/close",
                params={"intercomGroupId": gid}, headers=auth_headers,
                case_name="状态维度-关群", log_level="none",
            )
            close_data = parse_response_json(res, context="状态维度-关群")
            close_code = close_data["code"]
            status = _ImHelpers.remainder_status(
                http, base_url, auth_headers, gid, "关群后状态",
            )
            pre_rows = [
                {"项": "close", "期望": 0, "实际": close_code, "通过": close_code == 0},
                {"项": "remainder.status", "期望": 0, "实际": status, "通过": status == 0},
            ]
        else:
            res = http.send_request(
                "delete", f"{base_url}/api/monitor/intercom/group/delete",
                params={"intercomGroupId": gid}, headers=auth_headers,
                case_name="状态维度-删群", log_level="none",
            )
            delete_data = parse_response_json(res, context="状态维度-删群")
            del_code = delete_data["code"]
            if del_code == 0:
                intercom_group.unregister(gid)
            pre_rows = [
                {"项": "delete", "期望": 0, "实际": del_code, "通过": del_code == 0},
            ]
        params = {"intercomGroupId": gid, "page": 1, "pageSize": 100}
        json_data = send_case(
            http, "get", f"{base_url}/api/monitor/intercom/message/page",
            case, case_headers(auth_headers, case), params=params,
        )
        code, _ = assert_case(case, json_data, {"请求参数": params})
        if code != 0:
            return
        items = jp_list(json_data, "$.data.items[*]")
        chat = _ImHelpers.chat_items(
            http, base_url, auth_headers, item_name=seed["group"]["name"],
            name="状态维度-聊天项",
        )
        hit = next((c for c in chat if str(c.get("id")) == str(gid)), None)
        rows = pre_rows + [
            {"项": "消息仍可查", "期望": seed["snapshots"]["speech"],
             "实际": jp_first(json_data, "$.data.total"),
             "通过": jp_first(json_data, "$.data.total") == seed["snapshots"]["speech"]},
            {"项": "消息条数", "期望": len(seed["messageIds"]), "实际": len(items),
             "通过": len(items) == len(seed["messageIds"])},
        ]
        if scenario == "after_close":
            rows.append({
                "项": "聊天项仍在且 groupStatus=0", "期望": 0,
                "实际": (hit or {}).get("groupStatus"),
                "通过": hit is not None and hit.get("groupStatus") == 0,
            })
            summary = f"关群后消息仍可查 {len(items)} 条，聊天项 groupStatus=0"
        else:
            rows.append({
                "项": "聊天项已消失", "期望": "列表中无该群", "实际": (hit or {}).get("id"),
                "通过": hit is None,
            })
            summary = f"删群后消息仍可查 {len(items)} 条（软删），聊天项已摘除"
        report_extra_and_assert("状态维度", rows, summary)
