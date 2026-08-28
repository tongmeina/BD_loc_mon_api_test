from pathlib import Path

from tools.assertion_lint import lint_source, lint_testcases


def test_existing_testcases_use_unified_response_entry():
    testcase_dir = Path(__file__).parents[1] / "testcases"

    assert lint_testcases(testcase_dir) == []


def test_lint_detects_direct_json_and_envelope_parsing():
    violations = lint_source(
        """
import common.allure_assert_util as low
import jsonpath
from common.allure_assert_util import assert_api_result as low_assert

def test_bad():
    data = response.json()
    code = _jsonpath_parse(data, '$.code')[0]
    low.assert_api_result('bad', 0, None, 1, None)
    low_assert('bad', 0, None, 1, None)
    other = jsonpath.jsonpath(data, '$.msg')
""",
        display_path="test_bad.py",
    )
    rules = {item["rule"] for item in violations}

    assert rules == {
        "low-level-assert-import",
        "low-level-assert-call",
        "direct-response-json",
        "manual-envelope-jsonpath",
    }


def test_lint_allows_domain_jsonpath_fields():
    assert lint_source(
        """
def test_domain(json_data):
    items = _jsonpath_parse(json_data, '$.data.items[*]')
    assert items
""",
        display_path="test_domain.py",
    ) == []
