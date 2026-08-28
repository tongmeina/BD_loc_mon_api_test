# common/cleanup/rescue_chat.py
# tier 100：关闭 session 遗留活跃求救群。
# 原样搬迁自 conftest._close_rescue_chats_teardown（行为红线：降级路线/日志/计数不变）。
# 优先 complete/addr 批量完成；web 账号无权限（3001）时降级测试桩逐群关闭。
from common.logger_util import key
from common.requests_util import BaseRequest, parse_response_json

_jsonpath_parse = None  # 延迟导入见 _jp()
_http = BaseRequest()


def _jp():
    global _jsonpath_parse
    if _jsonpath_parse is None:
        import jsonpath
        _jsonpath_parse = jsonpath.jsonpath
    return _jsonpath_parse


def close_rescue_chats(base_url, auth_headers, sns) -> tuple:
    """按 sn 关闭遗留活跃求救群。返回 (关闭数, 仍活跃数)。"""
    closed, still_active = 0, 0
    for sn in sns:
        try:
            r = _http.send_request(
                method="get",
                url=f"{base_url}/api/monitor/emergency/chat/item/page",
                params={"Authorization": auth_headers.get("Authorization"),
                        "itemName": sn, "page": 1, "pageSize": 50},
                headers=auth_headers,
                case_name=f"收尾查群-{sn}",
                log_level="none",
            )
            page_data = parse_response_json(r, context=f"收尾查群-{sn}")
            items = _jp()(page_data, "$.data.items[*]") or []
        except Exception as e:
            key(f"⚠️ 收尾查群失败 {sn}", str(e)[:120])
            continue

        active = [it for it in items if it.get("status") == 1]
        if not active:
            continue
        key(f"发现遗留活跃群 {sn}", len(active))

        # 路线1：complete/addr 批量完成（首选）
        addr_ok = False
        try:
            r = _http.send_request(
                method="post",
                url=f"{base_url}/api/monitor/emergency/chat/item/complete/addr",
                json={"addrs": [sn], "handleResult": "AUTO会话收尾"},
                headers=auth_headers,
                case_name=f"收尾批量完成-{sn}",
                log_level="none",
            )
            response_data = parse_response_json(r, context=f"收尾批量完成-{sn}")
            addr_ok = response_data["code"] == 0
        except Exception:
            addr_ok = False

        # 路线2：无权限（3001）降级测试桩逐群关闭
        for it in active:
            if addr_ok:
                closed += 1
                continue
            try:
                r = _http.send_request(
                    method="get",
                    url=f"{base_url}/api/monitor/test/emergency-chat-item/expiration",
                    params={"Authorization": auth_headers.get("Authorization"),
                            "chatItemId": it.get("id"), "inactiveMillis": 1},
                    headers=auth_headers,
                    case_name=f"收尾关闭群-{it.get('id')}",
                    log_level="none",
                )
                response_data = parse_response_json(r, context=f"收尾关闭群-{it.get('id')}")
                closed += response_data["code"] == 0
            except Exception as e:
                key(f"⚠️ 收尾关闭失败 {it.get('id')}", str(e)[:120])
                still_active += 1

        if not addr_ok:
            # 测试桩路线复核：仍有活跃则计数（下次运行可见泄漏量）
            try:
                r = _http.send_request(
                    method="get",
                    url=f"{base_url}/api/monitor/emergency/chat/item/page",
                    params={"Authorization": auth_headers.get("Authorization"),
                            "itemName": sn, "page": 1, "pageSize": 50},
                    headers=auth_headers,
                    case_name=f"收尾复核-{sn}",
                    log_level="none",
                )
                review_data = parse_response_json(r, context=f"收尾复核-{sn}")
                remain = [x for x in (_jp()(review_data, "$.data.items[*]") or [])
                          if x.get("status") == 1]
                still_active += len(remain)
                closed -= max(0, len(remain))  # 扣回测试桩关而未闭的
            except Exception:
                pass
    return closed, still_active


def cleaner(ctx, sns, **flags) -> str:
    """registry 入口：payload = 本 session 造的全部救援 sn 列表。"""
    closed, leaked = close_rescue_chats(ctx.base_url, ctx.auth_headers, sns)
    key("求救群收尾统计", f"关闭: {closed}, 仍活跃: {leaked}")
    return f"关闭: {closed}, 仍活跃: {leaked}"
