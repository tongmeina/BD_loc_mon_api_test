# 公共日志格式化工具，提供美观的控制台输出格式
import json

from common.requests_util import (
    get_response_json,
    sanitize_sensitive_data,
    should_redact_response_secrets,
)


def mask_log_data(data, field_name=None):
    """兼容入口：递归脱敏日志与 Allure 数据。"""
    return sanitize_sensitive_data(data, str(field_name or ""))


def mask_log_text(text):
    """对非 JSON 日志文本做手机号和邮箱脱敏。"""
    return sanitize_sensitive_data(text)


def sep(title=""):
    """打印分隔线。"""
    if title:
        print(f"\n{'━'*50}")
        print(f"  {title}")
        print(f"{'━'*50}")
    else:
        print(f"{'━'*50}")


def key(key, value):
    """打印键值对，并按字段名脱敏。"""
    print(f"  {key}: {mask_log_data(value, key)}")


def print_request(method, url, params=None, json=None, headers=None):
    """格式化打印请求信息，并递归脱敏。"""
    print(f"\n  📤 {method} {url}")
    if params:
        print("  📋 Params:")
        for k, v in mask_log_data(params).items():
            print(f"     {k}: {v}")
    if json:
        print("  📦 JSON:")
        for k, v in mask_log_data(json).items():
            print(f"     {k}: {v}")
    if headers:
        print("  📑 Headers:")
        for k, v in mask_log_data(headers).items():
            print(f"     {k}: {v}")


def print_response(response):
    """格式化打印响应信息，并复用缓存 JSON 与递归脱敏。"""
    print(f"\n  📥 Status: {response.status_code}")
    try:
        json_data = sanitize_sensitive_data(
            get_response_json(response),
            mask_verification_code_values=should_redact_response_secrets(response),
        )
        print("  📦 Response:")
        print(f"     {json.dumps(json_data, indent=6, ensure_ascii=False)}")
    except ValueError:
        response_preview = response.text[:500] if response.text else "Empty"
        print(f"     {mask_log_text(response_preview)}")


def print_result(success=True, message=""):
    """打印结果信息。"""
    if success:
        print(f"\n  ✅ {message}")
    else:
        print(f"\n  ❌ {message}")
