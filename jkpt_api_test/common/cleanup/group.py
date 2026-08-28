# common/cleanup/group.py
# tier 300：删除三级测试分组（倒序 three→two→one）。
# 原样搬迁自 conftest.delete_groups_in_order。
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


def delete_groups_in_order(base_url, auth_headers, group_ids):
    """按顺序删除分组：三级 → 二级 → 一级"""
    groups_url = f"{base_url}/api/monitor/groups"
    success_count = 0
    fail_count = 0

    for level in ["three_id", "two_id", "one_id"]:
        group_id = group_ids.get(level)
        if group_id is None:
            continue

        delete_url = f"{groups_url}/{group_id}"
        resp = _http.send_request(
            method="delete",
            url=delete_url,
            headers=auth_headers,
            case_name=f"删除{level}分组 {group_id}",
            log_level="none"
        )

        json_data = parse_response_json(resp, context=f"删除{level}分组 {group_id}")
        code = json_data["code"]
        if code == 0:
            success_count += 1
            key(f"✅ 删除{level}分组 {group_id}", "成功")
        else:
            fail_count += 1
            msg = json_data.get("msg") or "未知错误"
            key(f"❌ 删除{level}分组 {group_id} 失败", f"code={code}, msg={msg}")

    return success_count, fail_count


def cleaner(ctx, group_ids, **flags) -> str:
    """registry 入口：payload = {"three_id":…, "two_id":…, "one_id":…}"""
    success, fail = delete_groups_in_order(ctx.base_url, ctx.auth_headers, group_ids)
    key("分组删除统计", f"成功: {success}, 失败: {fail}")
    return f"成功: {success}, 失败: {fail}"


def cleaner_b(ctx, payload, **flags) -> str:
    """registry 入口（B 支路变体）：payload 自带 B token，删 B 测试一级分组。"""
    success, fail = delete_groups_in_order(ctx.base_url, payload["auth_headers"], payload)
    key("B分组删除统计", f"成功: {success}, 失败: {fail}")
    return f"成功: {success}, 失败: {fail}"
