# common/protocol_transport.py
"""北斗协议 HTTP 传输层：POST /api/datas/bd"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from common.protocol_types import ProtocolSendResult
from common.requests_util import BaseRequest


def _now_cst_str() -> str:
    """对应 JMX 中 ${__groovy(... TimeZone Asia/Shanghai ... yyyy-MM-dd HH:mm:ss)}

    无论系统在什么时区，都返回北京时间（UTC+8）的格式化字符串
    """
    # 北京时区 (UTC+8)
    cst_timezone = timezone(timedelta(hours=8))
    return datetime.now(cst_timezone).strftime("%Y-%m-%d %H:%M:%S")


class BDProtocolTransport:
    """封装 /api/datas/bd 接口请求"""

    DEFAULT_TO_ADDR = "110110110"
    DEFAULT_PATH = "/api/datas/bd"

    def __init__(
        self,
        base_url: str,
        headers: Optional[Dict[str, str]] = None,
        http: Optional[BaseRequest] = None,
        to_addr: str = DEFAULT_TO_ADDR,
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}
        self.http = http or BaseRequest()
        self.to_addr = to_addr

    def send_bd_content(
        self,
        content_hex: str,
        from_addr: str,
        case_name: str = "",
        to_addr: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> ProtocolSendResult:
        """发送 bd 协议数据（单地址）"""
        return self.send_bd_content_batch(
            content_hexes=[content_hex] if isinstance(content_hex, str) else content_hex,
            from_addrs=[from_addr],
            case_name=case_name,
            to_addr=to_addr,
            timeout=timeout,
        )

    def send_bd_content_batch(
        self,
        content_hexes: list,
        from_addrs: list,
        case_name: str = "",
        to_addr: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> ProtocolSendResult:
        """批量发送 bd 协议数据（多地址 / 多内容）

        Body 结构与 JMX 完全一致：
        {
            "commInfos": [{"commTime": "", "content": "...", "fromAddr": "...",
                           "time": "yyyy-MM-dd HH:mm:ss", "toAddr": "110110110"}, ...],
            "receipts": [{...}]
        }
        """
        n = len(content_hexes)
        if n != len(from_addrs):
            raise ValueError(f"content_hexes({n}) 与 from_addrs({len(from_addrs)}) 长度必须一致")

        now_str = _now_cst_str()
        body: Dict[str, Any] = {
            "commInfos": [
                {
                    "commTime": "",
                    "content": content_hexes[i],
                    "fromAddr": from_addrs[i],
                    "time": now_str,
                    "toAddr": to_addr or self.to_addr,
                }
                for i in range(n)
            ],
            "receipts": [
                {
                    "fromAddr": "string",
                    "msg": "string",
                    "msgId": "string",
                    "sendTime": "string",
                    "status": 0,
                    "toAddr": "string",
                }
            ],
        }

        url = f"{self.base_url}{self.DEFAULT_PATH}"
        # /api/datas/bd 不需要 Authorization
        clean_headers = {
            k: v for k, v in self.headers.items() if k.lower() != "authorization"
        }
        clean_headers.setdefault("Content-Type", "application/json")

        resp = self.http.send_request(
            method="post",
            url=url,
            json=body,
            headers=clean_headers,
            timeout=timeout,
            case_name=case_name or "发送BD协议",
        )

        try:
            raw = resp.json()
        except Exception:
            raw = {}

        return ProtocolSendResult(
            status_code=resp.status_code,
            code=int(raw.get("code", -1)) if isinstance(raw, dict) else -1,
            msg=str(raw.get("msg", "")) if isinstance(raw, dict) else "",
            raw_response=raw if isinstance(raw, dict) else {},
            request_body=body,
        )
