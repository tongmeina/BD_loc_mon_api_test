# common/star_bean_util.py
"""星豆流水读取（余额闸门 / 扣费对账共用）。

抽取动机：对讲群与对讲群消息两套 suite 都要读「最新一条流水的 balanceAfter」当余额闸门
（规则：≥2 个 testcase 重复 ≥5 行 → 抽到 common/）。只读，不做扣费方向判断。
"""
import jsonpath

from common.requests_util import parse_response_json

_jsonpath_parse = jsonpath.jsonpath

_TX_PATH = "/api/monitor/star-bean/transaction/page"


def _items(res):
    data = parse_response_json(res, context="星豆流水查询")
    found = _jsonpath_parse(data, "$.data.items[*]")
    return found if found else []


def latest_entry(http, base_url, auth_headers, ttype):
    """最新一条指定类型流水 → (amount, balanceAfter)；无流水返回 None。"""
    res = http.send_request(
        "get", f"{base_url}{_TX_PATH}",
        params={"type": ttype, "page": 1, "pageSize": 1},
        headers=auth_headers, case_name=f"查{ttype}流水", log_level="none",
    )
    items = _items(res)
    if not items:
        return None
    return items[0].get("amount"), items[0].get("balanceAfter")


def latest_balance(http, base_url, auth_headers):
    """全局最新一条流水的 balanceAfter（不限类型）；无流水返回 None。"""
    res = http.send_request(
        "get", f"{base_url}{_TX_PATH}",
        params={"page": 1, "pageSize": 1},
        headers=auth_headers, case_name="查全局余额", log_level="none",
    )
    items = _items(res)
    return items[0].get("balanceAfter") if items else None
