# common/requests_util.py
import json
import logging
import re
import time
from typing import Optional, Dict, Any
from urllib.parse import urlparse

import requests

try:
    import allure
except Exception:  # pragma: no cover
    allure = None


_LAST_HTTP_CONTEXT: Dict[str, Any] = {}
_RESPONSE_JSON_CACHE_ATTRIBUTE = "_jkpt_response_json_cache"
_RESPONSE_JSON_ERROR_ATTRIBUTE = "_jkpt_response_json_error"
_RESPONSE_SECRET_REDACTION_ATTRIBUTE = "_jkpt_redact_response_secrets"
_MASKED_VALUE = "******"
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "token",
    "cookie",
    "password",
    "secret",
    "api_key",
    "apikey",
    "captcha",
    "verification_code",
    "verificationcode",
    "ver_code",
    "vercode",
)
_RECIPIENT_KEYS = {
    "to",
    "phone",
    "phone_number",
    "phonenumber",
    "mobile",
    "mobile_number",
    "mobilenumber",
    "email",
    "mail",
}
_PHONE_PATTERN = re.compile(r"(?<!\d)(1\d{10})(?!\d)")
_EMAIL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._%+\-])([A-Za-z0-9._%+\-]+)@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})(?![A-Za-z0-9.\-])"
)
_VERIFICATION_CODE_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z0-9]{4,8}(?![A-Za-z0-9])"
)


def get_last_http_context() -> Dict[str, Any]:
    return _LAST_HTTP_CONTEXT.copy()


def _mask_phone(phone: str) -> str:
    if len(phone) < 5:
        return _MASKED_VALUE
    return f"{phone[:3]}******{phone[-2:]}"


def _mask_email(local_part: str, domain: str) -> str:
    visible_prefix = local_part[:1] if local_part else ""
    return f"{visible_prefix}***@{domain}"


def _mask_sensitive_text(value: str) -> str:
    masked_value = _PHONE_PATTERN.sub(lambda match: _mask_phone(match.group(1)), value)
    return _EMAIL_PATTERN.sub(
        lambda match: _mask_email(match.group(1), match.group(2)),
        masked_value,
    )


def _looks_like_verification_code(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return bool(
        re.fullmatch(r"[A-Za-z0-9]{4,8}", value)
        and any(character.isdigit() for character in value)
    )


def sanitize_sensitive_data(
    data: Any,
    parent_key: str = "",
    mask_verification_code_values: bool = False,
) -> Any:
    """递归脱敏凭据与个人信息；敏感接口可额外隐藏疑似验证码值。"""
    normalized_parent_key = parent_key.lower().replace("-", "_")
    if any(part in normalized_parent_key for part in _SENSITIVE_KEY_PARTS):
        return _MASKED_VALUE
    if normalized_parent_key in _RECIPIENT_KEYS and data not in (None, ""):
        return _mask_sensitive_text(str(data))
    if (
        mask_verification_code_values
        and normalized_parent_key in {"data", "msg", "message"}
        and _looks_like_verification_code(data)
    ):
        return _MASKED_VALUE
    if isinstance(data, dict):
        return {
            key: sanitize_sensitive_data(
                value,
                str(key),
                mask_verification_code_values,
            )
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [
            sanitize_sensitive_data(
                value,
                parent_key,
                mask_verification_code_values,
            )
            for value in data
        ]
    if isinstance(data, tuple):
        return tuple(
            sanitize_sensitive_data(
                value,
                parent_key,
                mask_verification_code_values,
            )
            for value in data
        )
    if isinstance(data, str):
        masked_text = _mask_sensitive_text(data)
        if mask_verification_code_values:
            return _VERIFICATION_CODE_TOKEN_PATTERN.sub(
                lambda match: (
                    _MASKED_VALUE
                    if any(character.isdigit() for character in match.group(0))
                    else match.group(0)
                ),
                masked_text,
            )
        return masked_text
    return data


def should_redact_response_secrets(response: requests.Response) -> bool:
    return bool(getattr(response, _RESPONSE_SECRET_REDACTION_ATTRIBUTE, False))


def get_response_json(response: requests.Response) -> Any:
    """读取并缓存响应 JSON；日志、附件、断言共享同一次解析结果。"""
    if hasattr(response, _RESPONSE_JSON_CACHE_ATTRIBUTE):
        return getattr(response, _RESPONSE_JSON_CACHE_ATTRIBUTE)
    if hasattr(response, _RESPONSE_JSON_ERROR_ATTRIBUTE):
        cached_error = getattr(response, _RESPONSE_JSON_ERROR_ATTRIBUTE)
        raise cached_error
    try:
        data = response.json()
    except ValueError as error:
        setattr(response, _RESPONSE_JSON_ERROR_ATTRIBUTE, error)
        raise
    setattr(response, _RESPONSE_JSON_CACHE_ATTRIBUTE, data)
    return data


class NonJsonResponseError(ValueError):
    """HTTP 响应体为空或无法解析为 JSON"""

    def __init__(self, response: requests.Response, context: str = "", cause: Exception | None = None):
        self.response = response
        self.context = context
        text = (response.text or "").strip()
        preview = repr(text[:300]) if text else "(empty)"
        label = f"{context}：" if context else ""
        msg = (
            f"{label}响应非 JSON（status={response.status_code}, "
            f"content-type={response.headers.get('content-type', '')}, body={preview}）"
        )
        if cause is not None:
            msg = f"{msg}，解析错误: {cause}"
        super().__init__(msg)


def parse_response_json(response: requests.Response, context: str = "") -> Dict[str, Any]:
    """解析响应 JSON 对象；空体、非 JSON 或非对象响应抛出清晰异常。"""
    text = (response.text or "").strip()
    if not text:
        raise NonJsonResponseError(response, context)
    try:
        data = get_response_json(response)
    except ValueError as error:
        raise NonJsonResponseError(response, context, cause=error) from error
    if not isinstance(data, dict):
        cause = TypeError(f"期望 JSON object，实际 {type(data).__name__}")
        raise NonJsonResponseError(response, context, cause=cause)
    return data


class BaseRequest:
    """增强版请求类，手写用例首选入口"""

    def __init__(self, timeout: int = 30, debug: bool = True):
        self.timeout = timeout
        self.debug = debug
        self.logger = logging.getLogger(__name__)

    def send_request(
        self,
        method: str,
        url: str,
        params: Optional[Dict] = None,
        json: Optional[Dict] = None,
        data: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        files: Optional[Dict] = None,
        timeout: Optional[int] = None,
        case_name: str = "",
        log_level: str = "simple",
        redact_response_secrets: bool = False,
    ) -> requests.Response:
        """
        发送HTTP请求

        Args:
            method: HTTP方法 (get/post/put/delete/patch)
            url: 请求URL
            params: URL查询参数
            json: JSON请求体
            data: 表单请求体
            headers: 请求头
            files: 文件上传
            timeout: 超时秒数
            case_name: 用例名称（用于日志标识）
            log_level: 日志级别 (full/simple/none)
            redact_response_secrets: 隐藏响应 data/msg 中疑似验证码值
        """
        timeout = timeout or self.timeout

        # 日志输出
        if log_level == "full":
            print(f"\n[用例] {case_name}")
            print(f"[请求] {method.upper()} {url}")
            if params:
                sanitized_params = self._sanitize(params)
                print(f"[参数] {sanitized_params}")
            if headers:
                print(f"[请求头] {self._sanitize(headers)}")
            if json:
                print(f"[JSON] {self._sanitize(json)}")

        start = time.time()
        request_context = {
            "case_name": case_name,
            "method": method.upper(),
            "url": url,
            "params": self._sanitize(params),
            "json": self._sanitize(json),
            "data": self._sanitize(data),
            "headers": self._sanitize(headers),
        }

        try:
            response = requests.request(
                method=method.upper(),
                url=url,
                params=params,
                json=json,
                data=data,
                headers=headers,
                files=files,
                timeout=timeout,
            )
            setattr(
                response,
                _RESPONSE_SECRET_REDACTION_ATTRIBUTE,
                redact_response_secrets,
            )
            elapsed_ms = int((time.time() - start) * 1000)
            response_context = self._build_response_context(
                response,
                elapsed_ms,
                redact_response_secrets,
            )
            self._attach_allure_context(request_context, response_context)
            self._set_last_http_context(request_context, response_context)

            if log_level in ("full", "simple"):
                try:
                    response_json = get_response_json(response)
                    sanitized_response = sanitize_sensitive_data(
                        response_json,
                        mask_verification_code_values=redact_response_secrets,
                    )
                    print(f"[响应] {sanitized_response}")
                except ValueError:
                    response_preview = sanitize_sensitive_data(
                        response.text[:500],
                        mask_verification_code_values=redact_response_secrets,
                    )
                    print(f"[响应] {response_preview}")

            return response

        except requests.exceptions.RequestException as e:
            elapsed_ms = int((time.time() - start) * 1000)
            error_context = {
                "error_type": e.__class__.__name__,
                "error_message": str(e),
                "elapsed_ms": elapsed_ms,
            }
            self._attach_allure_context(request_context, None, error_context)
            self._set_last_http_context(request_context, None, error_context)
            print(f"[错误] 请求失败: {e}")
            raise

    @staticmethod
    def _sanitize(data: Any) -> Any:
        """递归过滤凭据、手机号、邮箱和验证码字段。"""
        return sanitize_sensitive_data(data)

    @staticmethod
    def _to_pretty_json(data: Any) -> str:
        return json.dumps(data, ensure_ascii=False, indent=2, default=str)

    def _build_response_context(
        self,
        response: requests.Response,
        elapsed_ms: int,
        redact_response_secrets: bool = False,
    ) -> Dict[str, Any]:
        try:
            response_body = get_response_json(response)
        except ValueError:
            response_body = response.text[:5000] if response.text else ""
        return {
            "status_code": response.status_code,
            "headers": self._sanitize(dict(response.headers)),
            "body": sanitize_sensitive_data(
                response_body,
                mask_verification_code_values=redact_response_secrets,
            ),
            "elapsed_ms": elapsed_ms,
        }

    @staticmethod
    def _allure_attach_title(kind: str, request_context: Dict[str, Any]) -> str:
        """Allure 附件标题：方法 + 路径 + 可选用例名，便于一条用例里多请求时区分。"""
        method = (request_context.get("method") or "?").upper()
        raw_url = request_context.get("url") or ""
        path = urlparse(raw_url).path or raw_url
        title = f"[{kind}] {method} {path}"
        case_name = (request_context.get("case_name") or "").strip()
        if case_name:
            title = f"{title} · {case_name}"
        return title

    def _attach_allure_context(
        self,
        request_context: Dict[str, Any],
        response_context: Optional[Dict[str, Any]] = None,
        error_context: Optional[Dict[str, Any]] = None
    ) -> None:
        if allure is None:
            return
        allure.attach(
            self._to_pretty_json(request_context),
            name=self._allure_attach_title("请求", request_context),
            attachment_type=allure.attachment_type.JSON
        )
        if response_context is not None:
            status = response_context.get("status_code")
            kind = f"响应 {status}" if status is not None else "响应"
            allure.attach(
                self._to_pretty_json(response_context),
                name=self._allure_attach_title(kind, request_context),
                attachment_type=allure.attachment_type.JSON
            )
        if error_context is not None:
            allure.attach(
                self._to_pretty_json(error_context),
                name=self._allure_attach_title("请求失败", request_context),
                attachment_type=allure.attachment_type.JSON
            )

    def _set_last_http_context(
        self,
        request_context: Dict[str, Any],
        response_context: Optional[Dict[str, Any]] = None,
        error_context: Optional[Dict[str, Any]] = None
    ) -> None:
        global _LAST_HTTP_CONTEXT
        payload: Dict[str, Any] = {
            "request": request_context,
            "transport_allure_attached": allure is not None,
        }
        if response_context is not None:
            payload["response"] = response_context
        if error_context is not None:
            payload["error"] = error_context
        _LAST_HTTP_CONTEXT = payload