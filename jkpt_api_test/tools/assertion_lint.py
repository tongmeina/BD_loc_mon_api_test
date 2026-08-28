"""静态检查普通 REST testcase 是否绕过统一响应信封入口。"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable


_ENVELOPE_PATHS = {"$.code", "$.msg"}


def _path_text(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _is_response_json_call(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Attribute) and node.func.attr == "json" and not node.args


def _is_low_level_assert_call(node: ast.Call, module_aliases: set[str]) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "assert_api_result"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in module_aliases
    )


def _is_envelope_jsonpath_call(
    node: ast.Call,
    jsonpath_aliases: set[str],
) -> bool:
    if isinstance(node.func, ast.Name):
        is_jsonpath_call = node.func.id in {
            "jp_first", "_jp_first", "jp_list", "_jsonpath_parse"
        }
    else:
        is_jsonpath_call = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "jsonpath"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in jsonpath_aliases
        )
    if not is_jsonpath_call:
        return False
    return any(
        isinstance(arg, ast.Constant)
        and isinstance(arg.value, str)
        and arg.value in _ENVELOPE_PATHS
        for arg in node.args[1:]
    )


def lint_source(source: str, *, display_path: str = "<memory>") -> list[dict[str, object]]:
    """检查一段 testcase 源码；供文件扫描和单元测试共用。"""
    try:
        tree = ast.parse(source, filename=display_path)
    except SyntaxError as error:
        return [{
            "path": display_path,
            "line": error.lineno or 1,
            "rule": "syntax-error",
            "message": str(error),
        }]

    low_level_module_aliases: set[str] = set()
    jsonpath_module_aliases: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "common.allure_assert_util":
                    low_level_module_aliases.add(alias.asname or alias.name.split(".")[0])
                if alias.name == "jsonpath":
                    jsonpath_module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "common.allure_assert_util":
                for alias in node.names:
                    if alias.name == "assert_api_result":
                        low_level_module_aliases.add(alias.asname or alias.name)

    violations: list[dict[str, object]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if (
                node.module == "common.allure_assert_util"
                and any(alias.name == "assert_api_result" for alias in node.names)
            ):
                violations.append({
                    "path": display_path,
                    "line": node.lineno,
                    "rule": "low-level-assert-import",
                    "message": "普通 testcase 不得直接导入 assert_api_result",
                })
        elif isinstance(node, ast.Call):
            if _is_response_json_call(node):
                violations.append({
                    "path": display_path,
                    "line": node.lineno,
                    "rule": "direct-response-json",
                    "message": "普通 testcase 应通过 assert_response 或 parse_response_json 解析响应",
                })
            elif _is_low_level_assert_call(node, low_level_module_aliases):
                violations.append({
                    "path": display_path,
                    "line": node.lineno,
                    "rule": "low-level-assert-call",
                    "message": "普通 testcase 不得直接调用 assert_api_result",
                })
            elif _is_envelope_jsonpath_call(node, jsonpath_module_aliases):
                violations.append({
                    "path": display_path,
                    "line": node.lineno,
                    "rule": "manual-envelope-jsonpath",
                    "message": "普通 testcase 不得自行解析 $.code/$.msg",
                })
    return violations


def lint_testcase_file(path: Path, root: Path | None = None) -> list[dict[str, object]]:
    """返回 testcase 文件中的违规项；仅检查普通测试代码，不检查 fixtures/cleanup。"""
    root = root or path.parent
    violations = lint_source(
        path.read_text(encoding="utf-8-sig"),
        display_path=_path_text(path, root),
    )
    return violations


def iter_testcase_files(testcase_dir: Path) -> Iterable[Path]:
    yield from sorted(testcase_dir.glob("test_*.py"))


def lint_testcases(testcase_dir: Path) -> list[dict[str, object]]:
    """扫描 testcase 目录，返回按路径和行号排序的违规项。"""
    violations = []
    for path in iter_testcase_files(testcase_dir):
        violations.extend(lint_testcase_file(path, root=testcase_dir.parent))
    return sorted(violations, key=lambda item: (str(item["path"]), int(item["line"])))


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("testcase_dir", type=Path)
    args = parser.parse_args()
    result = lint_testcases(args.testcase_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1 if result else 0)
