# common/cleanup/terminal.py
# tier 200：删除 session 造的设备（按分组聚合批量删）。
# 原样搬迁自 conftest.get_terminals_by_group / cleanup_terminals_batch。
from common.logger_util import key
from common.requests_util import BaseRequest, parse_response_json

_http = BaseRequest()


def _jp():
    global _jsonpath_parse
    if _jsonpath_parse is None:
        import jsonpath
        _jsonpath_parse = jsonpath.jsonpath
    return _jsonpath_parse

_jsonpath_parse = None


def get_terminals_by_group(base_url, auth_headers, group_id):
    """获取指定分组下的所有设备地址列表"""
    url = f"{base_url}/api/monitor/groups/{group_id}/terminals"
    params = {"page": 1, "pageSize": 1000}

    resp = _http.send_request(
        method="get",
        url=url,
        params=params,
        headers=auth_headers,
        case_name=f"获取分组 {group_id} 下的设备",
        log_level="none"
    )

    json_data = parse_response_json(resp, context="设备清理响应")
    code = json_data["code"]

    if code == 0:
        terminals = _jp()(json_data, "$.data.items[*].addr")
        return terminals if terminals else []

    key(f"获取分组 {group_id} 设备失败", "将返回空列表")
    return []


def cleanup_terminals_batch(base_url, auth_headers, group_id, addrs):
    """批量删除指定分组下的设备"""
    if not addrs:
        key(f"分组 {group_id}", "无设备需要删除")
        return 0, 0

    url = f"{base_url}/api/monitor/terminals/batch"
    data = {"addrs": ",".join(addrs)}

    resp = _http.send_request(
        method="delete",
        url=url,
        json=data,
        headers=auth_headers,
        case_name=f"批量删除分组 {group_id} 下的设备",
        log_level="none"
    )

    json_data = parse_response_json(resp, context="设备清理响应")
    code = json_data["code"]

    if code == 0:
        key(f"✅ 分组 {group_id} 设备删除", f"成功删除 {len(addrs)} 个设备")
        return len(addrs), 0

    msg = json_data.get("msg") or "未知错误"
    key(f"❌ 分组 {group_id} 设备删除失败", f"code={code}, msg={msg}")
    return 0, len(addrs)


def cleaner(ctx, group_ids, **flags) -> str:
    """registry 入口：payload = 分组 id 字典（three/two/one），
    与 GroupCleaner 的 payload 相同——设备先于分组清（tier 200 < 300）。"""
    total_deleted, total_failed = 0, 0
    for level in ["three_id", "two_id", "one_id"]:
        group_id = group_ids.get(level)
        if not group_id:
            continue
        addrs = get_terminals_by_group(ctx.base_url, ctx.auth_headers, group_id)
        if addrs:
            deleted, failed = cleanup_terminals_batch(
                ctx.base_url, ctx.auth_headers, group_id, addrs
            )
            total_deleted += deleted
            total_failed += failed
    key("设备删除统计", f"成功: {total_deleted}, 失败: {total_failed}")
    return f"成功: {total_deleted}, 失败: {total_failed}"


def cleaner_b(ctx, payload, **flags) -> str:
    """registry 入口（B 支路变体）：payload 自带 B token，
    不能用 ctx.auth_headers（那是 A 的）。B 测试分组下设备用 B 权限批量删。"""
    headers = payload["auth_headers"]
    total_deleted, total_failed = 0, 0
    for level in ("three_id", "two_id", "one_id"):
        group_id = payload.get(level)
        if not group_id:
            continue
        addrs = get_terminals_by_group(ctx.base_url, headers, group_id)
        if addrs:
            deleted, failed = cleanup_terminals_batch(ctx.base_url, headers, group_id, addrs)
            total_deleted += deleted
            total_failed += failed
    key("B设备删除统计", f"成功: {total_deleted}, 失败: {total_failed}")
    return f"成功: {total_deleted}, 失败: {total_failed}"
