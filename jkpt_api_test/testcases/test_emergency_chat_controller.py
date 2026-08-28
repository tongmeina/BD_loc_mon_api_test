# testcases/test_emergency_chat_controller.py
"""求救群聊接口测试（emergency/chat/*）

Allure Suites：先按接口类名 TestEc00…TestEc15 排序，类内 YAML 用例用默认 [case0]/[case1]
（与围栏一致，避免中文 ids 转成 \\uXXXX）。
状态链锁死：TestEc10ItemComplete 必须先于 TestEc10bSendAfterComplete
（session 群 complete 后回写 extract.yaml）。
"""
import time
import jsonpath
import pytest

from common.case_report_util import assert_response
from common.logger_util import key, print_request, print_response, sep
from common.requests_util import BaseRequest, parse_response_json
from common.yaml_util import read_yaml, resolve_extract_value, write_yaml

_jsonpath_parse = jsonpath.jsonpath
http = BaseRequest()
_TEST_DATA = read_yaml("./yaml/test_emergency_chat_controller.yaml")


class _EmergencyChatHelpers:
    """不被 pytest 收集；供各 TestEc* 复用查询/断言。"""

    def _get_complete_status(self, base_url, auth_headers, chat_item_id):
        """查 complete/status 接口的 isCompleted（辅助方法）"""
        url = f"{base_url}/api/monitor/emergency/chat/item/complete/status"
        params = {"Authorization": auth_headers.get("Authorization") or "",
                  "chatItemId": chat_item_id}
        res = http.send_request("get", url, params=params, headers=auth_headers,
                                case_name="查完成状态", log_level="none")
        data = parse_response_json(res, context="查完成状态")
        matched = _jsonpath_parse(data, "$.data.isCompleted")
        return matched[0] if matched else None

    def _create_active_chat(self, base_url, auth_headers, rescue_client, sn):
        """二次 SOS 造一个活跃群（供 expiration / 取消SOS 验证真实「活跃→完成/关闭」跃迁）。

        主群在 10 批次已被 complete，无法用于验证正向跃迁；用同 sn 再发一次 SOS，
        轮询 item/page 取「非 extract 主群 id」的最新群。
        """
        result = rescue_client.send_sos(sn, kind=1)
        if not result.success:
            pytest.fail(f"二次 SOS 失败: code={result.code}, msg={result.message}")
        for i in range(3):
            time.sleep(2)
            items = self._get_item_page(base_url, auth_headers, sn)
            # 过滤掉已完结的主群，取最新活跃群（列表按时间倒序，第一个 status==1 的）
            active = [it for it in items if it.get("status") == 1]
            if active:
                return active[0]
        pytest.fail(f"二次造群超时: sn={sn} 无新活跃群")

    def _get_record_page(self, base_url, auth_headers, chat_item_id):
        """查询聊天记录（辅助方法）"""
        url = f"{base_url}/api/monitor/emergency/chat/record/page"
        params = {"Authorization": auth_headers.get("Authorization") or "",
                  "chatItemId": chat_item_id, "page": 1, "pageSize": 50}
        res = http.send_request("get", url, params=params, headers=auth_headers,
                                case_name="查聊天记录", log_level="none")
        data = parse_response_json(res, context="查聊天记录")
        return _jsonpath_parse(data, "$.data.items[*]") or []

    def _get_item_page(self, base_url, auth_headers, sn):
        """查询群聊列表（辅助方法）"""
        url = f"{base_url}/api/monitor/emergency/chat/item/page"
        params = {"Authorization": auth_headers.get("Authorization") or "",
                  "itemName": sn, "page": 1, "pageSize": 10}
        res = http.send_request("get", url, params=params, headers=auth_headers,
                                case_name="查群聊列表", log_level="none")
        data = parse_response_json(res, context="查群聊列表")
        return _jsonpath_parse(data, "$.data.items[*]") or []

    def _get_member_list(self, base_url, auth_headers, chat_item_id):
        """查询群成员列表（辅助方法）"""
        url = f"{base_url}/api/monitor/emergency/chat/member/list"
        params = {"Authorization": auth_headers.get("Authorization") or "", "chatItemId": chat_item_id}
        res = http.send_request("get", url, params=params, headers=auth_headers,
                                case_name="查成员列表", log_level="none")
        data = parse_response_json(res, context="查成员列表")
        return _jsonpath_parse(data, "$.data[*]") or []


class TestEc00FixtureChain(_EmergencyChatHelpers):
    """a0 造数验证"""

    def test_fixture_chain(self, emergency_chat_item):
        """a0 造数验证：fixture 全链跑通（入库→添加→SOS→建群→提取chatItemId）"""
        sep(" a0 造数验证 ")
        assert emergency_chat_item["chatItemId"], "chatItemId 为空"
        assert emergency_chat_item["sn"], "sn 为空"
        assert emergency_chat_item["status"] == 1, f"群聊状态应为1(救援中)，实际{emergency_chat_item['status']}"
        assert "SOS-" in emergency_chat_item["itemName"], f"群名格式异常: {emergency_chat_item['itemName']}"
        key("chatItemId", emergency_chat_item["chatItemId"])
        key("sn", emergency_chat_item["sn"])
        key("itemName", emergency_chat_item["itemName"])


class TestEc01ItemPage(_EmergencyChatHelpers):
    """群聊列表"""

    @pytest.mark.parametrize("case", _TEST_DATA["item_page_cases"])
    def test_item_page(self, base_url, auth_headers, emergency_chat_item, case):
        """群聊列表查询（正向/模糊查询/边界/无token）"""
        url = f"{base_url}/api/monitor/emergency/chat/item/page"
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}

        params = {
            "Authorization": headers.get("Authorization") or "",
            "page": case.get("page", 1),
            "pageSize": case.get("page_size", 10),
        }
        item_name = case.get("item_name")
        if item_name:
            params["itemName"] = resolve_extract_value(item_name, required=False) or item_name

        sep(f" 测试用例: {case['name']} ")
        print_request("GET", url, params=params, headers=headers)
        res = http.send_request("get", url, params=params, headers=headers,
                                case_name=case["name"], log_level="none")
        print_response(res)
        json_data = assert_response(
            case,
            res,
            biz_context={"请求参数": params},
        )
        code = json_data["code"]

        if code == 0 and case.get("item_name") and not case.get("no_auth"):
            items = _jsonpath_parse(json_data, "$.data.items[*]") or []
            hit = any(it.get("id") == emergency_chat_item["chatItemId"] for it in items)
            assert hit, f"模糊查询未命中本群: chatItemId={emergency_chat_item['chatItemId']}"
            # 仅命中：所有返回项的 itemName 都必须含 sn（搜 sn 不允许带出别的群）
            sn = emergency_chat_item["sn"]
            strangers = [it.get("itemName") for it in items if sn not in str(it.get("itemName") or "")]
            assert not strangers, f"模糊查询带出无关群: {strangers}"
            key("模糊查询命中", f"{len(items)} 条全部含 sn={sn}")



class TestEc02MemberList(_EmergencyChatHelpers):
    """成员查询"""

    @pytest.mark.parametrize("case", _TEST_DATA["member_list_cases"])
    def test_member_list(self, base_url, auth_headers, emergency_chat_item, case):
        """群成员列表查询（正向/不存在/为空/无token）"""
        url = f"{base_url}/api/monitor/emergency/chat/member/list"
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}

        chat_item_id = resolve_extract_value(case.get("chat_item_id"), required=False) \
            or emergency_chat_item["chatItemId"]
        params = {
            "Authorization": headers.get("Authorization") or "",
            "chatItemId": chat_item_id,
        }

        sep(f" 测试用例: {case['name']} ")
        print_request("GET", url, params=params, headers=headers)
        res = http.send_request("get", url, params=params, headers=headers,
                                case_name=case["name"], log_level="none")
        print_response(res)
        json_data = assert_response(
            case,
            res,
            biz_context={"请求参数": params},
        )
        code = json_data["code"]

        if code == 0 and case["name"] == "成员列表-正向":
            members = _jsonpath_parse(json_data, "$.data[*]") or []
            key("成员数", len(members))
            assert len(members) >= 1, "SOS 群聊成员列表不应为空"
            # 数据往返：SOS 发起设备必须在成员列表，且状态/类型正确（2026-08-17 探测实锤字段）
            sn = emergency_chat_item["sn"]
            device = next((m for m in members
                           if m.get("avatarInfo", {}).get("memberAccount") == sn), None)
            assert device, \
                f"成员列表未含 SOS 发起设备 {sn}: {[m.get('avatarInfo', {}).get('memberAccount') for m in members]}"
            ai = device.get("avatarInfo", {})
            key("SOS设备成员", f"type={ai.get('memberAccountType')} status={ai.get('status')}")
            assert ai.get("memberAccountType") == "TERMINAL_DEVICE", \
                f"设备成员类型异常: {ai.get('memberAccountType')}"
            assert ai.get("status") == "SOS", f"设备成员状态应为SOS: {ai.get('status')}"
            # 结构断言：每个成员骨架字段齐全（id 唯一、avatarInfo 内核字段在）
            ids = [m.get("id") for m in members]
            assert len(set(ids)) == len(ids), f"成员 id 不唯一: {ids}"
            for m in members:
                ai = m.get("avatarInfo") or {}
                assert ai.get("memberAccount") is not None, \
                    f"成员 {m.get('id')} avatarInfo 缺 memberAccount: {ai}"



class TestEc03MemberAdd(_EmergencyChatHelpers):
    """添加成员"""

    @pytest.mark.parametrize("case", _TEST_DATA["member_add_cases"])
    def test_member_add(self, base_url, auth_headers, emergency_chat_item, case):
        """添加群成员（正向3类型/负向/幂等/无token）"""
        url = f"{base_url}/api/monitor/emergency/chat/member/add"
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}

        chat_item_id = resolve_extract_value(case.get("chat_item_id"), required=False)             or emergency_chat_item["chatItemId"]
        body = {
            "chatItemId": chat_item_id,
            "memberAccount": case.get("member_account", ""),
            "memberAccountType": case.get("member_account_type", ""),
        }
        if case.get("nickname"):
            body["nickname"] = case.get("nickname")

        sep(f" 测试用例: {case['name']} ")
        print_request("POST", url, json=body, headers=headers)
        res = http.send_request("post", url, json=body, headers=headers,
                                case_name=case["name"], log_level="none")
        print_response(res)
        json_data = assert_response(
            case,
            res,
            biz_context={
                "请求body": {
                    key_name: value
                    for key_name, value in body.items()
                    if key_name != "Authorization"
                }
            },
        )
        code = json_data["code"]

        # 正向断言：数据往返——写入什么账号，必须在成员列表可观测到什么
        # 2026-08-17 探测实锤：memberAccount 是内部id（不可预测，如"354"），
        # 正确锚点是 avatarInfo 三元组：phone(=请求memberAccount) + memberAccountType(=请求类型) + nickname(=请求昵称)
        if code == 0 and case.get("scenario") == "positive" and case.get("member_account"):
            members = self._get_member_list(base_url, auth_headers, chat_item_id)
            hit = next((m for m in members
                        if m.get("avatarInfo", {}).get("phone") == body["memberAccount"]
                        and m.get("avatarInfo", {}).get("memberAccountType") == body["memberAccountType"]
                        and m.get("avatarInfo", {}).get("nickname") == body.get("nickname")), None)
            assert hit, (
                f"添加后成员列表未观测到写入数据 phone={body['memberAccount']} "
                f"type={body['memberAccountType']} nick={body.get('nickname')}；"
                f"实际: {[(m.get('avatarInfo', {}).get('phone'), m.get('avatarInfo', {}).get('memberAccountType'), m.get('avatarInfo', {}).get('nickname')) for m in members]}"
            )
            key("数据往返命中", f"phone={body['memberAccount']} memberId={hit.get('id')}")
            # 回写 extract 供 member/edit 编辑「新增成员」而非自己（add→edit 闭环）
            if case.get("member_account") == "13128251672":
                write_yaml("./extract.yaml",
                           {"emergency_added_member_id": hit.get("id")}, mode="append")
                key("回写 extract", f"emergency_added_member_id={hit.get('id')}")

        # 幂等断言：同账号重复添加，成员列表中该 phone 的记录数必须仍为 1（防多条）
        if case.get("scenario") == "idempotent":
            phone = body["memberAccount"]
            cnt_before = sum(1 for m in self._get_member_list(base_url, auth_headers, chat_item_id)
                             if m.get("avatarInfo", {}).get("phone") == phone)
            res2 = http.send_request("post", url, json=body, headers=headers,
                                     case_name=case["name"] + "-重复", log_level="none")
            cnt_after = sum(1 for m in self._get_member_list(base_url, auth_headers, chat_item_id)
                            if m.get("avatarInfo", {}).get("phone") == phone)
            key("幂等验证", f"phone={phone} 添加前={cnt_before} 重复添加后={cnt_after}")
            assert cnt_after == cnt_before, \
                f"重复添加改变了成员记录数: {cnt_before}→{cnt_after}（幂等要求不产生新记录）"

        # 幂等断言：重复添加同账号，成员数不翻倍
        if case.get("scenario") == "idempotent":
            before = len(self._get_member_list(base_url, auth_headers, chat_item_id))
            # 再发一次同请求
            res2 = http.send_request("post", url, json=body, headers=headers,
                                    case_name=case["name"]+"-重复", log_level="none")
            after = len(self._get_member_list(base_url, auth_headers, chat_item_id))
            key("幂等验证", f"添加前={before} 重复添加后={after}")
            assert after <= before + 1, f"重复添加产生多条记录: {before}→{after}"



class TestEc04MemberEdit(_EmergencyChatHelpers):
    """编辑成员"""

    @pytest.mark.parametrize("case", _TEST_DATA["member_edit_cases"])
    def test_member_edit(self, base_url, auth_headers, emergency_chat_item, case):
        """编辑群成员昵称（正向/不存在/为空/无token）"""
        url = f"{base_url}/api/monitor/emergency/chat/member/edit"
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}

        # memberId 解析（2026-08-17 实测实锤规则「仅能编辑自己的群昵称」）：
        # - 正向场景：编辑当前账号自己（接口归属校验下唯一合法语义）
        # - forbidden 场景：编辑 3-1 新增成员——他人昵称必须被拒（越权面断言）
        member_id = case.get("member_id")
        old_nickname = None
        # 显式空串是负向用例（原样发送验校验）；仅 None/占位符 才走动态解析
        if member_id is None or "{{" in str(member_id):
            members = self._get_member_list(base_url, auth_headers, emergency_chat_item["chatItemId"])
            if case.get("scenario") == "forbidden":
                added = resolve_extract_value("{{emergency_added_member_id}}", required=False)
                assert added, "新增成员ID未提取：需先跑 TestEc03MemberAdd 正向-企业账号"
                me = next((m for m in members if m.get("id") == added), None)
            else:
                me = next((m for m in members
                           if m.get("avatarInfo", {}).get("memberAccount") == "user1752216001906"), None)
            member_id = me.get("id") if me else None
            assert member_id, f"未找到可编辑的 memberId: {[m.get('avatarInfo',{}).get('memberAccount') for m in members]}"
            old_nickname = me.get("avatarInfo", {}).get("nickname")

        body = {"memberId": member_id, "nickname": case.get("nickname", "")}

        sep(f" 测试用例: {case['name']} ")
        print_request("POST", url, json=body, headers=headers)
        res = http.send_request("post", url, json=body, headers=headers,
                                case_name=case["name"], log_level="none")
        print_response(res)
        json_data = assert_response(
            case,
            res,
            biz_context={"请求body": body},
        )
        code = json_data["code"]

        # 正向断言：数据往返——新昵称在、旧昵称消失（防编辑无效却因残留数据通过）
        if code == 0 and case.get("scenario") == "positive" and not case.get("no_auth"):
            members = self._get_member_list(base_url, auth_headers, emergency_chat_item["chatItemId"])
            me = next((m for m in members if m.get("id") == member_id), None)
            if me:
                new_nick = me.get("avatarInfo", {}).get("nickname")
                key("编辑后昵称", new_nick)
                assert new_nick == case.get("nickname"), f"昵称未更新: {new_nick} != {case.get('nickname')}"
                if old_nickname and old_nickname != case.get("nickname"):
                    nicks = [m.get("avatarInfo", {}).get("nickname") for m in members]
                    assert old_nickname not in nicks, \
                        f"旧昵称 {old_nickname} 仍存在（编辑可能未生效而是残留）: {nicks}"

        # 越权断言：编辑他人昵称必须被拒，且对方昵称不变（副作用未发生）
        if case.get("scenario") == "forbidden" and code != 0:
            members = self._get_member_list(base_url, auth_headers, emergency_chat_item["chatItemId"])
            me = next((m for m in members if m.get("id") == member_id), None)
            if me:
                nick_now = me.get("avatarInfo", {}).get("nickname")
                key("他人昵称未被篡改", nick_now)
                assert nick_now == old_nickname, \
                    f"编辑被拒但他人昵称被改: {old_nickname}→{nick_now}"



class TestEc05Send(_EmergencyChatHelpers):
    """发送消息"""

    @pytest.mark.parametrize("case", _TEST_DATA["send_cases"])
    def test_send(self, base_url, auth_headers, emergency_chat_item, case):
        """发送消息（正向TEXT/幂等reportId/负向/状态机/无token）"""
        url = f"{base_url}/api/monitor/emergency/chat/send"
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}

        chat_item_id = resolve_extract_value(case.get("chat_item_id"), required=False) \
            or emergency_chat_item["chatItemId"]
        params = {
            "Authorization": headers.get("Authorization") or "",
            "chatItemId": chat_item_id,
            "sendType": case.get("send_type", ""),
            "content": case.get("content", ""),
        }
        if case.get("report_id"):
            params["reportId"] = case.get("report_id")

        sep(f" 测试用例: {case['name']} ")
        print_request("POST", url, params=params, headers=headers)
        res = http.send_request("post", url, params=params, headers=headers,
                                case_name=case["name"], log_level="none")
        print_response(res)
        request_context = {
            "请求参数": {
                key_name: value
                for key_name, value in params.items()
                if key_name != "Authorization"
            }
        }
        if case.get("send_type") == "VIDEO":
            # VIDEO 响应消息是异常栈，仅比较业务 code，不强制匹配 msg。
            json_data = assert_response(
                {"name": case["name"], "expected": {"code": case["expected"]["code"]}},
                res,
                biz_context=request_context,
            )
        else:
            json_data = assert_response(case, res, biz_context=request_context)
        code = json_data["code"]
        msg = json_data.get("msg") or ""

        if code == 0 and case.get("scenario") == "positive" and case.get("send_type") == "TEXT":
            time.sleep(1)
            records = self._get_record_page(base_url, auth_headers, chat_item_id)
            contents = [r.get("content") for r in records]
            hit = case.get("content") in contents
            key("消息落库", f"内容在记录中: {hit}")
            assert hit, f"发送后 record/page 未含该消息: {case.get('content')}"

        if case.get("scenario") == "idempotent":
            # 幂等的数据往返验证：同 content 发送 2 次后，该 content 落库条数必须 ≤1
            # （旧断言 after<=before+1 恒真——重复记录也算通过，等于没验）
            time.sleep(1)
            content = case.get("content")
            res2 = http.send_request("post", url, params=params, headers=headers,
                                     case_name=case["name"] + "-重复", log_level="none")
            repeat_json = assert_response(
                {"name": case["name"] + "-重复", "expected": {"code": case["expected"]["code"]}},
                res2,
                biz_context={"请求参数": params},
            )
            code2 = repeat_json["code"]
            time.sleep(2)
            records = self._get_record_page(base_url, auth_headers, chat_item_id)
            cnt = sum(1 for r in records if r.get("content") == content)
            key("幂等验证", f"content重复发送2次后落库={cnt}条 重复code={code2}")
            assert cnt <= 1, f"同 content 重复发送落库 {cnt} 条（>1 即非幂等，重复副作用实锤）"

        # sendType非法用例：msg 为完整异常栈，跳过 msg 精确匹配
        if case.get("send_type") == "VIDEO":
            sep(" 断言结果 ")
            key("预期 code", case["expected"]["code"])
            key("实际 code", code)
            key("实际 msg(截断)", msg[:100])


class TestEc05bSendVoice(_EmergencyChatHelpers):
    """发送语音"""

    def test_send_voice(self, base_url, auth_headers, emergency_chat_item):
        """发送语音消息（计划5-2/风险3/S6）：file 走 form-data 文件上传。

        S6 三传法实测（2026-08-17）：
          - form-data 文件上传 → code=0 唯一正确传法
          - query 纯 hex → 1001 Spring 类型转换异常
          - 仅 fileSize → 1001 语音文件保存失败
        副作用断言字段为 sendType（计划原文 lastChatType 系字段名误记，实测 record 无此字段）。
        """
        from common.rescue_platform_client import DEFAULT_SPEECH_HEX
        url = f"{base_url}/api/monitor/emergency/chat/send"
        chat_item_id = emergency_chat_item["chatItemId"]
        params = {
            "Authorization": auth_headers.get("Authorization") or "",
            "chatItemId": chat_item_id,
            "sendType": "VOICE",
        }

        before = len(self._get_record_page(base_url, auth_headers, chat_item_id))
        key("发送前记录数", before)

        sep(" 测试用例: 发送消息-正向-VOICE(form-data) ")
        print_request("POST", url, params=params, headers=auth_headers)
        wav_like = bytes.fromhex(DEFAULT_SPEECH_HEX)
        res = http.send_request(
            "post", url, params=params, headers=auth_headers,
            files={"file": ("voice.dvw", wav_like, "application/octet-stream")},
            case_name="发送消息-正向-VOICE(form-data)", log_level="none")
        print_response(res)
        json_data = assert_response(
            {
                "name": "发送消息-正向-VOICE(form-data)",
                "expected": {"code": 0},
            },
            res,
            biz_context={"请求参数": {"chatItemId": chat_item_id, "sendType": "VOICE"}},
        )
        code = json_data["code"]
        key("实际 code", code)

        # 副作用：record 新增一条 sendType=VOICE（轮询兜异步）
        time.sleep(3)
        records = self._get_record_page(base_url, auth_headers, chat_item_id)
        key("发送后记录数", len(records))
        assert len(records) == before + 1, f"记录数未+1: {before}→{len(records)}"
        newest = records[0]  # 列表按时间倒序，最新在前
        key("最新记录 sendType", newest.get("sendType"))
        key("最新记录 fileSize", newest.get("fileSize"))
        assert newest.get("sendType") == "VOICE", \
            f"新增记录 sendType 应为 VOICE: {newest.get('sendType')}"
        assert newest.get("fileSize"), "VOICE 记录 fileSize 为空"


class TestEc06RecordPage(_EmergencyChatHelpers):
    """聊天记录"""

    @pytest.mark.parametrize("case", _TEST_DATA["record_page_cases"])
    def test_record_page(self, base_url, auth_headers, emergency_chat_item, case):
        """聊天记录分页查询（正向/提取recordId/不存在/无token）"""
        url = f"{base_url}/api/monitor/emergency/chat/record/page"
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}

        chat_item_id = resolve_extract_value(case.get("chat_item_id"), required=False) \
            or emergency_chat_item["chatItemId"]
        params = {
            "Authorization": headers.get("Authorization") or "",
            "chatItemId": chat_item_id,
            "page": case.get("page", 1),
            "pageSize": case.get("page_size", 10),
        }

        sep(f" 测试用例: {case['name']} ")
        print_request("GET", url, params=params, headers=headers)
        res = http.send_request("get", url, params=params, headers=headers,
                                case_name=case["name"], log_level="none")
        print_response(res)
        json_data = assert_response(
            case,
            res,
            biz_context={"请求参数": params},
        )
        code = json_data["code"]

        if code == 0 and case["name"] == "聊天记录-正向-默认分页":
            items = _jsonpath_parse(json_data, "$.data.items[*]") or []
            key("记录数", len(items))
            assert len(items) >= 1, "SOS 建群后应至少有1条报警消息记录"
            # 数据往返：SOS 建群必有该已知文案（造数链 U2 上行 → 平台自动消息，实测固定）
            contents = [it.get("content") for it in items]
            assert "遇到危险，触发SOS报警，请求帮助!" in contents, \
                f"聊天记录未含 SOS 建群标准文案: {contents[:5]}"

        if code == 0 and case.get("scenario") == "extract_record_id":
            items = _jsonpath_parse(json_data, "$.data.items[*]") or []
            if items:
                record_id = items[0].get("id")
                write_yaml("./extract.yaml", {"emergency_chat_record_id": record_id}, mode="append")
                key("提取 recordId", record_id)

        # 翻页守恒（计划 6-2）：pageSize=1 取两页，两页 id 无重叠且均属本群全量记录集
        # 按全量数动态分支：N>=2 验两页各1条无重叠；N==1（如计费拦截致消息未落库）验 P1=1条+P2=空
        if code == 0 and case.get("scenario") == "paging_conserve":
            full_ids = [r.get("id") for r in
                        self._get_record_page(base_url, auth_headers, chat_item_id)]
            p1, p2 = [], []
            for pg in (1, 2):
                r2 = http.send_request("get", url,
                                       params={"Authorization": auth_headers.get("Authorization") or "",
                                               "chatItemId": chat_item_id, "page": pg, "pageSize": 1},
                                       headers=auth_headers,
                                       case_name=f"翻页第{pg}页", log_level="none")
                page_data = parse_response_json(r2, context=f"翻页第{pg}页")
                page_items = (_jsonpath_parse(page_data, "$.data.items[*]") or [])
                (p1 if pg == 1 else p2).extend(it.get("id") for it in page_items)
            key("翻页守恒", f"全量={len(full_ids)} P1={p1} P2={p2}")
            assert len(full_ids) >= 1, "全量记录为空，无法验翻页"
            if len(full_ids) >= 2:
                assert len(p1) == 1 and len(p2) == 1, f"pageSize=1 每页应恰1条: P1={p1} P2={p2}"
                assert p1[0] != p2[0], f"两页记录重复（翻页失效）: {p1} vs {p2}"
            else:
                assert len(p1) == 1 and not p2, f"仅1条记录时应P1=1条P2=空: P1={p1} P2={p2}"
            assert set(p1) | set(p2) <= set(full_ids), "翻页记录不属于本群全量集合"



class TestEc07AllRead(_EmergencyChatHelpers):
    """全部已读"""

    @pytest.mark.parametrize("case", _TEST_DATA["all_read_cases"])
    def test_all_read(self, base_url, auth_headers, emergency_chat_item, case):
        """全部已读（正向/幂等/负向/无token）"""
        url = f"{base_url}/api/monitor/emergency/chat/item/all/read"
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}

        chat_item_id = resolve_extract_value(case.get("chat_item_id"), required=False)             or emergency_chat_item["chatItemId"]
        params = {
            "Authorization": headers.get("Authorization") or "",
            "chatItemId": chat_item_id,
        }

        sep(f" 测试用例: {case['name']} ")
        print_request("GET", url, params=params, headers=headers)
        res = http.send_request("get", url, params=params, headers=headers,
                                case_name=case["name"], log_level="none")
        print_response(res)
        json_data = assert_response(
            case,
            res,
            biz_context={"请求参数": params},
        )
        code = json_data["code"]

        if code == 0 and case.get("scenario") == "positive":
            time.sleep(1)
            items = self._get_item_page(base_url, auth_headers, emergency_chat_item["sn"])
            target = next((it for it in items if it.get("id") == chat_item_id), None)
            if target:
                unread = target.get("unreadCount")
                key("已读后未读数", unread)
                assert unread == 0, f"已读后未读数未归零: {unread}"

        if case.get("scenario") == "idempotent":
            res2 = http.send_request("get", url, params=params, headers=headers,
                                    case_name=case["name"]+"-重复", log_level="none")
            repeat_json = assert_response(
                {"name": case["name"] + "-重复", "expected": {"code": 0}},
                res2,
                biz_context={"请求参数": params},
            )
            code2 = repeat_json["code"]
            # 幂等的数据往返：重复已读后未读数必须仍为 0（code=0 什么也没证）
            time.sleep(1)
            items = self._get_item_page(base_url, auth_headers, emergency_chat_item["sn"])
            target = next((it for it in items if it.get("id") == chat_item_id), None)
            unread2 = target.get("unreadCount") if target else None
            key("幂等验证", f"重复调用 code={code2} 重复后未读数={unread2}")
            assert code2 == 0, f"重复调用失败: {code2}"
            assert unread2 == 0, f"重复已读后未读数翻倍/回涨: {unread2}"



class TestEc08ReadList(_EmergencyChatHelpers):
    """已读未读成员"""

    @pytest.mark.parametrize("case", _TEST_DATA["read_list_cases"])
    def test_read_list(self, base_url, auth_headers, emergency_chat_item, case):
        """已读未读成员列表（正向/负向/无token）"""
        url = f"{base_url}/api/monitor/emergency/chat/record/read/list"
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}

        record_id = resolve_extract_value(case.get("record_id"), required=False)             or resolve_extract_value("{{emergency_chat_record_id}}", required=False)
        if not record_id:
            pytest.skip("recordId 未提取（先跑 record/page 提取用例）")
        params = {
            "Authorization": headers.get("Authorization") or "",
            "chatRecordId": record_id,
        }

        sep(f" 测试用例: {case['name']} ")
        print_request("GET", url, params=params, headers=headers)
        res = http.send_request("get", url, params=params, headers=headers,
                                case_name=case["name"], log_level="none")
        print_response(res)
        json_data = assert_response(
            case,
            res,
            biz_context={"请求参数": params},
        )
        code = json_data["code"]

        if code == 0 and case.get("scenario") == "positive":
            data = json_data.get("data") or {}
            read_list = data.get("readList") or []
            unread_list = data.get("unreadList") or []
            key("已读成员", len(read_list))
            key("未读成员", len(unread_list))
            # 守恒断言（2026-08-17 探测实锤真实语义）：
            # readList+unreadList 并不覆盖全部群成员（不含企业成员与终端设备），只统计 App 个人账号。
            # 可靠不变量是「⊆ 群成员集合」：已读/未读名单里不允许出现群外成员；且无交集。
            member_ids = {m.get("id") for m in
                          self._get_member_list(base_url, auth_headers,
                                                emergency_chat_item["chatItemId"])}
            read_ids = {m.get("id") for m in read_list}
            unread_ids = {m.get("id") for m in unread_list}
            assert not (read_ids & unread_ids), \
                f"同一成员同时在已读与未读名单: {read_ids & unread_ids}"
            outside = (read_ids | unread_ids) - member_ids
            assert not outside, f"已读/未读名单出现群外成员: {outside}"
            key("守恒校验", f"已读∪未读={len(read_ids | unread_ids)} ⊆ 群成员={len(member_ids)}")



class TestEc09ErrorMsg(_EmergencyChatHelpers):
    """下发失败原因"""

    @pytest.mark.parametrize("case", _TEST_DATA["error_msg_cases"])
    def test_error_msg(self, base_url, auth_headers, emergency_chat_item, case):
        """下发失败原因（正向/负向/无token）"""
        url = f"{base_url}/api/monitor/emergency/chat/record/errorMsg"
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}

        record_id = resolve_extract_value(case.get("record_id"), required=False)             or resolve_extract_value("{{emergency_chat_record_id}}", required=False)
        if not record_id:
            pytest.skip("recordId 未提取（先跑 record/page 提取用例）")
        params = {
            "Authorization": headers.get("Authorization") or "",
            "chatRecordId": record_id,
        }

        sep(f" 测试用例: {case['name']} ")
        print_request("GET", url, params=params, headers=headers)
        res = http.send_request("get", url, params=params, headers=headers,
                                case_name=case["name"], log_level="none")
        print_response(res)
        json_data = assert_response(
            case,
            res,
            biz_context={"请求参数": params},
        )
        code = json_data["code"]

        # 正向数据往返：正常送达的消息，record 的 errorMsg 应为空（成功态）
        # 实现方式：从 record/page 查该 recordId 的 errorMsg 字段并断言为空
        if code == 0 and case.get("scenario") == "positive":
            records = self._get_record_page(base_url, auth_headers,
                                            emergency_chat_item["chatItemId"])
            target = next((r for r in records if r.get("id") == record_id), None)
            if target is not None:
                em = target.get("errorMsg")
                key("record.errorMsg", em)
                assert not em, f"正常消息 errorMsg 非空: {em}"



class TestEc10ItemComplete(_EmergencyChatHelpers):
    """救援完成"""

    @pytest.mark.parametrize("case", _TEST_DATA["complete_cases"])
    def test_item_complete(self, base_url, auth_headers, emergency_chat_item,
                           emergency_chat_voice, case):
        """救援完成（正向含前后状态闭环/幂等/负向/无token）

        emergency_chat_voice：session 级 fixture——complete 前向主群上行终端语音（U5），
        落库确认后才放行 complete（状态机闸门前置数据）。全量跑天然满足 >60s 上报间隔；
        单跑本类时 fixture 内补足等待。
        """
        url = f"{base_url}/api/monitor/emergency/chat/item/complete"
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}

        chat_item_id = resolve_extract_value(case.get("chat_item_id"), required=False) \
            or emergency_chat_item["chatItemId"]

        # 状态机闭环·前：complete 前查 status，应为未完成
        # 仅主群正向用例做前置检查（负向用例 YAML 惯例也标 positive，按是否带 chat_item_id 区分）
        if case.get("scenario") == "positive" and not case.get("chat_item_id"):
            pre = self._get_complete_status(base_url, auth_headers, chat_item_id)
            key("前置 isCompleted", pre)
            assert pre is False, f"前置状态异常（群已被完成？）: isCompleted={pre}"

        params = {
            "Authorization": headers.get("Authorization") or "",
            "chatItemId": chat_item_id,
        }

        sep(f" 测试用例: {case['name']} ")
        print_request("GET", url, params=params, headers=headers)
        res = http.send_request("get", url, params=params, headers=headers,
                                case_name=case["name"], log_level="none")
        print_response(res)
        json_data = assert_response(
            case,
            res,
            biz_context={"请求参数": params},
        )
        code = json_data["code"]

        # 正向：副作用三连——列表 status=0 / status接口 true / 回写 extract 供 5-7 状态机反例
        if code == 0 and case.get("scenario") == "positive":
            time.sleep(1)
            items = self._get_item_page(base_url, auth_headers, emergency_chat_item["sn"])
            target = next((it for it in items if it.get("id") == chat_item_id), None)
            if target is not None:
                key("完成后列表 status", target.get("status"))
                assert target.get("status") == 0, f"完成后 status 未变0: {target.get('status')}"
            post = self._get_complete_status(base_url, auth_headers, chat_item_id)
            key("后置 isCompleted", post)
            assert post is True, f"完成后 isCompleted 应为 true: {post}"
            # 消息持久性：完结后终端语音记录仍可查（历史消息不因 complete 丢失）
            records = self._get_record_page(base_url, auth_headers, chat_item_id)
            voice_hit = any(r.get("id") == emergency_chat_voice["voiceRecordId"]
                            and r.get("sendType") == "VOICE" for r in records)
            key("完结后语音记录仍在", voice_hit)
            assert voice_hit, \
                f"complete 后终端语音记录丢失: voiceRecordId={emergency_chat_voice['voiceRecordId']}"
            write_yaml("./extract.yaml",
                       {"emergency_completed_item_id": chat_item_id}, mode="append")
            key("回写 extract", f"emergency_completed_item_id={chat_item_id}")

        # 幂等：重复 complete——幂等成功或明确业务码拒绝均可，群终态必须保持已完成（计划10-3）
        if case.get("scenario") == "idempotent":
            res2 = http.send_request("get", url, params=params, headers=headers,
                                     case_name=case["name"] + "-重复", log_level="none")
            repeat_json = assert_response(
                {"name": case["name"] + "-重复", "expected": {"code": case["expected"]["code"]}},
                res2,
                biz_context={"请求参数": params},
            )
            code2 = repeat_json["code"]
            msg2 = repeat_json.get("msg") or ""
            key("幂等验证", f"重复 complete code={code2} msg={msg2}")
            final = self._get_complete_status(base_url, auth_headers, chat_item_id)
            key("最终 isCompleted", final)
            assert final is True, f"重复 complete 后群终态异常: isCompleted={final}"



class TestEc10bSendAfterComplete(_EmergencyChatHelpers):
    """已完成群再发消息"""

    def test_send_after_complete(self, base_url, auth_headers):
        """已完成群聊再发消息——非法跃迁拦截验证（本计划最高优先断言）。

        依赖 TestEc10ItemComplete 正向用例回写的 {{emergency_completed_item_id}}；
        同一次全量跑中按定义序在其后执行。单独跑 5 批次时显式 skip（不静默回退活跃群）。
        """
        chat_item_id = resolve_extract_value("{{emergency_completed_item_id}}", required=False)
        if not chat_item_id:
            pytest.skip("已完成群聊ID未生成：需先执行 TestEc10ItemComplete 正向用例回写 extract")

        url = f"{base_url}/api/monitor/emergency/chat/send"
        params = {
            "Authorization": auth_headers.get("Authorization") or "",
            "chatItemId": chat_item_id,
            "sendType": "TEXT",
            "content": "AUTO_state_machine_should_be_rejected",
        }

        sep(" 测试用例: 发送消息-状态机-已完成群聊再发 ")
        print_request("POST", url, params=params, headers=auth_headers)
        res = http.send_request("post", url, params=params, headers=auth_headers,
                                case_name="发送消息-状态机-已完成群聊再发", log_level="none")
        print_response(res)
        json_data = assert_response(
            {
                "name": "发送消息-状态机-已完成群聊再发",
                "expected": {"code": 1001, "msg": "救援已结束，无法发送消息"},
            },
            res,
            biz_context={"请求参数": params},
        )
        key("已完成群 chatItemId", chat_item_id)
        key("实际 code", json_data["code"])
        key("实际 msg", json_data.get("msg"))
        # 2026-08-17 实测：状态机护栏存在——code=1001 "救援已结束，无法发送消息"。
        # 2026-08-14 旧记录「已完成群仍可发消息(code=0)」系 extract 缺键静默回退活跃群的假阳性，已纠正。


class TestEc11CompleteStatus(_EmergencyChatHelpers):
    """完成按钮状态"""

    @pytest.mark.parametrize("case", _TEST_DATA["complete_status_cases"])
    def test_complete_status(self, base_url, auth_headers, emergency_chat_item, case):
        """完成按钮状态（语义 hasPermission/isCompleted/负向/无token）"""
        url = f"{base_url}/api/monitor/emergency/chat/item/complete/status"
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}

        chat_item_id = resolve_extract_value(case.get("chat_item_id"), required=False) \
            or emergency_chat_item["chatItemId"]
        params = {
            "Authorization": headers.get("Authorization") or "",
            "chatItemId": chat_item_id,
        }

        sep(f" 测试用例: {case['name']} ")
        print_request("GET", url, params=params, headers=headers)
        res = http.send_request("get", url, params=params, headers=headers,
                                case_name=case["name"], log_level="none")
        print_response(res)
        json_data = assert_response(
            case,
            res,
            biz_context={"请求参数": params},
        )
        code = json_data["code"]

        # 语义断言：hasPermission 必为 bool；主群已被 10 批次 complete → isCompleted=true
        if code == 0 and case.get("scenario") == "semantic":
            data = json_data.get("data") or {}
            hp = data.get("hasPermission")
            ic = data.get("isCompleted")
            key("hasPermission", hp)
            key("isCompleted", ic)
            assert isinstance(hp, bool), f"hasPermission 应为 bool: {hp}"
            assert ic is True, f"已完成群 isCompleted 应为 true: {ic}"



class TestEc13ClearUnread(_EmergencyChatHelpers):
    """清空全部未读"""

    @pytest.mark.parametrize("case", _TEST_DATA["clear_unread_cases"])
    def test_clear_unread(self, base_url, auth_headers, emergency_chat_item, case):
        """清空全部未读（正向副作用/幂等/无token）"""
        url = f"{base_url}/api/monitor/emergency/chat/item/clear/all-unread"
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}

        params = {"Authorization": headers.get("Authorization") or ""}

        sep(f" 测试用例: {case['name']} ")
        print_request("PUT", url, params=params, headers=headers)
        res = http.send_request("put", url, params=params, headers=headers,
                                case_name=case["name"], log_level="none")
        print_response(res)
        json_data = assert_response(
            case,
            res,
            biz_context={"请求参数": params},
        )
        code = json_data["code"]

        # 正向副作用：列表第一页所有群 unreadCount=0
        if code == 0 and case.get("scenario") == "positive":
            time.sleep(1)
            list_url = f"{base_url}/api/monitor/emergency/chat/item/page"
            list_params = {"Authorization": auth_headers.get("Authorization") or "",
                           "page": 1, "pageSize": 50}
            r = http.send_request("get", list_url, params=list_params, headers=auth_headers,
                                  case_name="查全部群聊", log_level="none")
            list_data = parse_response_json(r, context="查全部群聊")
            items = _jsonpath_parse(list_data, "$.data.items[*]") or []
            not_cleared = [(it.get("itemName"), it.get("unreadCount"))
                           for it in items if it.get("unreadCount")]
            key("未清零群数", len(not_cleared))
            assert not not_cleared, f"清空后仍有未读群: {not_cleared[:5]}"

        # 幂等：连续 2 次，均成功
        if case.get("scenario") == "idempotent":
            res2 = http.send_request("put", url, params=params, headers=headers,
                                     case_name=case["name"] + "-重复", log_level="none")
            repeat_json = assert_response(
                {"name": case["name"] + "-重复", "expected": {"code": 0}},
                res2,
                biz_context={"请求参数": params},
            )
            code2 = repeat_json["code"]
            key("幂等验证", f"重复清空 code={code2}")



class TestEc14Expiration(_EmergencyChatHelpers):
    """自动关闭"""

    @pytest.mark.parametrize("case", _TEST_DATA["expiration_cases"])
    def test_expiration(self, base_url, auth_headers, emergency_chat_item, rescue_client, case):
        """测试桩：按 inactiveMillis 关闭群聊（正向造新群验证/负向边界）"""
        url = f"{base_url}/api/monitor/test/emergency-chat-item/expiration"
        headers = {**auth_headers}
        if case.get("no_auth"):
            headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}

        sn = emergency_chat_item["sn"]
        active_chat = None
        if case.get("scenario") == "positive":
            active_chat = self._create_active_chat(base_url, auth_headers, rescue_client, sn)
            chat_item_id = active_chat.get("id")
            key("待关闭群", f"id={chat_item_id}")
        else:
            chat_item_id = emergency_chat_item["chatItemId"]

        params = {
            "Authorization": headers.get("Authorization") or "",
            "chatItemId": chat_item_id,
            "inactiveMillis": case.get("inactive_millis", 1),
        }

        sep(f" 测试用例: {case['name']} ")
        print_request("GET", url, params=params, headers=headers)
        res = http.send_request("get", url, params=params, headers=headers,
                                case_name=case["name"], log_level="none")
        print_response(res)
        json_data = assert_response(
            case,
            res,
            biz_context={"请求参数": params},
        )
        code = json_data["code"]

        # 正向副作用：群聊不再处于活跃态
        if code == 0 and active_chat:
            time.sleep(2)
            items = self._get_item_page(base_url, auth_headers, sn)
            target = next((it for it in items if it.get("id") == chat_item_id), None)
            if target is not None:
                key("关闭后 status", target.get("status"))
                assert target.get("status") != 1, f"群聊仍活跃: status={target.get('status')}"
            else:
                key("关闭后查询", "群已不在列表（视为已关闭）")



class TestEc15CancelSos(_EmergencyChatHelpers):
    """取消SOS状态机"""

    def test_cancel_sos_state_machine(self, base_url, auth_headers, emergency_chat_item, rescue_client):
        """取消 SOS（reportFlag=10）后群聊终态验证（S4.7 实测转用例，2026-08-17）。

        链路：二次 SOS 造新群 → send_cancel_sos(reportFlag=10) → 验证群终态：
          1. 取消后群 status 是否翻 0（等价 complete）
          2. 取消后再发消息是否被拦截（状态机护栏面）
        """
        sn = emergency_chat_item["sn"]
        sep(" 🆘 U4 取消SOS状态机 ")
        active_chat = self._create_active_chat(base_url, auth_headers, rescue_client, sn)
        chat_id = active_chat.get("id")
        key("新群", f"id={chat_id}")

        result = rescue_client.send_cancel_sos(sn)
        key("取消SOS success", result.success)
        assert result.success, f"取消SOS发送失败: code={result.code}, msg={result.message}"
        time.sleep(3)

        # 断言1：群终态——status 翻 0（等价 complete）
        items = self._get_item_page(base_url, auth_headers, sn)
        target = next((it for it in items if it.get("id") == chat_id), None)
        assert target is not None, "取消后群从列表消失（视为已终态，但无法断言 status）"
        key("取消后 status", target.get("status"))
        assert target.get("status") == 0, \
            f"取消SOS后群未完结: status={target.get('status')}（应等价 complete 翻0）"

        # 断言2：取消后群内再发消息被拦截（状态机护栏，与 5-7 同族）
        url = f"{base_url}/api/monitor/emergency/chat/send"
        params = {
            "Authorization": auth_headers.get("Authorization") or "",
            "chatItemId": chat_id,
            "sendType": "TEXT",
            "content": "AUTO_cancel_sos_should_be_rejected",
        }
        res = http.send_request("post", url, params=params, headers=auth_headers,
                                case_name="取消SOS后发消息", log_level="none")
        response_data = assert_response(
            {
                "name": "取消SOS后发消息",
                "expected": {"code": 1001, "msg": "救援已结束，无法发送消息"},
            },
            res,
            biz_context={"请求参数": params},
        )
        key("取消后发消息 code", response_data["code"])
        key("取消后发消息 msg", response_data.get("msg"))
