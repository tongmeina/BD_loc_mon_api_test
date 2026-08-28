from common.logger_util import mask_log_data, mask_log_text
from common.requests_util import sanitize_sensitive_data


def test_sanitize_sensitive_data_masks_ver_code_request_fields():
    data = {
        "Authorization": "real-token",
        "to": "13800138000",
        "email": "tester@example.invalid",
        "nested": {"phone": "13900139000"},
    }

    masked = sanitize_sensitive_data(data)

    assert "real-token" not in str(masked)
    assert "13800138000" not in str(masked)
    assert "13900139000" not in str(masked)
    assert "tester@example.invalid" not in str(masked)


def test_logger_compatibility_mask_covers_text_and_structures():
    assert "13800138000" not in mask_log_text("to=13800138000")
    assert "tester@example.invalid" not in mask_log_text("email=tester@example.invalid")
    assert "13800138000" not in str(mask_log_data({"to": "13800138000"}))
