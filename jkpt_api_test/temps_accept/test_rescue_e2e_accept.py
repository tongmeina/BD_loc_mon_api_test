# temps_accept/test_rescue_e2e_accept.py — 验收用例（验证后删除）
"""端到端验收：fixture 全链可复用性验证"""
import pytest


class TestRescueE2EAccept:
    """验证 rescue_sat_terminal + emergency_chat_item fixture 全链"""

    def test_e2e_chat_item_created(self, emergency_chat_item):
        """fixture 链跑通即断言成功：群聊已创建且 chatItemId 非空"""
        assert emergency_chat_item["chatItemId"], "chatItemId 为空"
        assert emergency_chat_item["status"] == 1, f"群聊状态应为1(救援中), 实际{emergency_chat_item['status']}"
        assert emergency_chat_item["sn"], "sn 为空"
        assert "SOS-" in emergency_chat_item["itemName"], "群名格式异常"
        print(f"\n群聊: {emergency_chat_item['itemName']} chatItemId={emergency_chat_item['chatItemId']}")

    def test_e2e_chat_item_in_list(self, base_url, auth_headers, emergency_chat_item):
        """提取的 chatItemId 能在群聊列表中查到（闭环验证）"""
        from common.requests_util import BaseRequest, parse_response_json
        import jsonpath
        http = BaseRequest()
        r = http.send_request(
            method="get",
            url=f"{base_url}/api/monitor/emergency/chat/item/page",
            params={"Authorization": auth_headers.get("Authorization"),
                    "itemName": emergency_chat_item["sn"], "page": 1, "pageSize": 10},
            headers=auth_headers,
            case_name="验收-群聊列表查",
            log_level="none",
        )
        response_data = parse_response_json(r, context="验收-群聊列表查")
        items = jsonpath.jsonpath(response_data, "$.data.items[*]") or []
        ids = [it.get("id") for it in items]
        assert emergency_chat_item["chatItemId"] in ids, f"chatItemId 不在列表: {ids}"
        print(f"\n列表闭环: chatItemId={emergency_chat_item['chatItemId']} 在列")
