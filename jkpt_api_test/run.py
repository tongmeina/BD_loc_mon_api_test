"""一键执行 pytest，并基于本次独立结果生成 Allure 报告。

每次运行使用唯一的 ``temps/run-*`` 目录，避免其他 pytest 进程清理或覆盖
当前任务的原始结果。静态报告仍输出到 ``reports``，便于保持固定访问路径。
"""
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

_PROJECT_DIRECTORY = Path(__file__).resolve().parent
_VENV_PYTHON = _PROJECT_DIRECTORY / ".venv" / "Scripts" / "python.exe"


def _restart_with_project_virtual_environment():
    current_python = Path(sys.executable).resolve()
    if not _VENV_PYTHON.is_file() or os.path.normcase(str(current_python)) == os.path.normcase(str(_VENV_PYTHON)):
        return

    exit_code = subprocess.call(
        [str(_VENV_PYTHON), *sys.argv],
        cwd=str(_PROJECT_DIRECTORY),
    )
    raise SystemExit(exit_code)


_restart_with_project_virtual_environment()

import pytest


def _create_run_results_directory():
    run_identifier = (
        f"run-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
        f"-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    )
    run_results_directory = _PROJECT_DIRECTORY / "temps" / run_identifier
    run_results_directory.mkdir(parents=True, exist_ok=False)
    return run_results_directory


def _remove_user_allure_output_arguments(arguments):
    filtered_arguments = []
    skip_next_argument = False

    for argument in arguments:
        if skip_next_argument:
            skip_next_argument = False
            continue
        if argument == "--alluredir":
            skip_next_argument = True
            continue
        if argument.startswith("--alluredir=") or argument == "--clean-alluredir":
            continue
        filtered_arguments.append(argument)

    return filtered_arguments


def _run_allure_command(arguments):
    allure_executable = shutil.which("allure")
    if not allure_executable:
        print("\nAllure CLI 未找到，原始结果已保留，未生成静态报告。")
        return 127

    command = [allure_executable, *arguments]
    if os.name == "nt" and Path(allure_executable).suffix.lower() in {".bat", ".cmd"}:
        command = ["cmd.exe", "/d", "/s", "/c", subprocess.list2cmdline(command)]

    completed_process = subprocess.run(command, cwd=str(_PROJECT_DIRECTORY), check=False)
    return completed_process.returncode


def main():
    run_results_directory = _create_run_results_directory()
    user_pytest_arguments = _remove_user_allure_output_arguments(sys.argv[1:])
    pytest_arguments = [
        *user_pytest_arguments,
        f"--alluredir={run_results_directory}",
        "--clean-alluredir",
    ]

    print(f"本次 Allure 原始结果目录: {run_results_directory}")
    pytest_exit_code = int(pytest.main(pytest_arguments))

    result_file_count = sum(1 for _ in run_results_directory.glob("*-result.json"))
    if result_file_count == 0:
        print("\n本次运行未产生 Allure 测试结果，跳过报告生成。")
        return pytest_exit_code

    if pytest_exit_code not in {int(pytest.ExitCode.OK), int(pytest.ExitCode.TESTS_FAILED)}:
        print(
            f"\npytest 异常结束，退出码={pytest_exit_code}。"
            f"原始结果保留在: {run_results_directory}"
        )
        return pytest_exit_code

    reports_directory = _PROJECT_DIRECTORY / "reports"
    generate_exit_code = _run_allure_command(
        ["generate", str(run_results_directory), "-o", str(reports_directory), "--clean"]
    )
    if generate_exit_code != 0:
        print(
            f"\nAllure 报告生成失败，退出码={generate_exit_code}。"
            f"原始结果保留在: {run_results_directory}"
        )
        return generate_exit_code

    print(f"\n报告已生成: {reports_directory / 'index.html'}")
    print(f"报告包含本次独立结果: {result_file_count} 条")
    print("正在启动 Allure 本地服务，请勿直接双击 index.html ...")
    return _run_allure_command(["open", str(reports_directory)])


if __name__ == "__main__":
    raise SystemExit(main())
