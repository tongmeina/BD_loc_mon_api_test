# 断言统一改造交接记录

> 更新时间：2026-08-28
> 对应计划：`assertion-unification.plan.md`

## 当前结论

核心改造和最终验收均已完成。普通 REST testcase 已统一经过 `assert_response` 或 intercom 兼容链 `send_case → assert_case`；领域断言继续消费已解析的 `json_data`。协议、导出、fixture 和 cleanup 保留专用入口。

## 已完成

- `common/case_report_util.py`：统一安全响应解析、可选 HTTP 状态、信封断言和兼容入口。
- `common/requests_util.py`：响应 JSON 缓存、非 JSON 清晰错误、请求/响应脱敏。
- 报警控制器：分页/最新/批量信息结构断言；单条/按类型/按 ID 处理前确认未处理、处理后按目标 ID 轮询。
- 报警状态按 Swagger `AlarmInfoRespDto` 支持 `handleStatus.name/value`、`handleTimeStr`；未知状态不默认放行。
- 普通 testcase 已清理直接 `.json()` 和 `$.code/$.msg` 信封解析。
- fixture、common helper、cleanup 和验收探针的直接解析已统一改用 `parse_response_json`；协议/导出例外未误改。
- `tools/assertion_lint.py` 及 `unit/test_assertion_lint.py` 已加入静态门禁。
- `SKILL.md`、`yaml-conventions.md`、模板和 CHANGELOG 已同步统一入口规范。

## 已通过验证

- 单测：27 passed。
- 编译：`common`、`testcases`、`unit`、`tools` 全部通过。
- 静态 lint：普通 testcase 0 violations。
- 收集：440 tests collected。
- 基础 controller：137 passed，0 failed，0 skipped，214.97s；设备 39/39、分组 3/3、GLHT 36/36 清理成功。
- BD 协议：13 passed，0 failed，0 skipped，61.24s；AA 图片 7/7 分包均返回 HTTP 200/code=0，分组 3/3 清理成功。
- emergency：109 passed，0 failed，0 skipped，217.65s；求救群无活跃残留，订单、设备、分组和 GLHT 清理成功。
- intercom + 验证码：172 passed，0 failed，9 skipped，93.65s；对讲群、设备 11/11、分组 4/4、GLHT 11/11 清理成功。
- 真实接口回归合计：431 passed，0 failed，9 skipped，与 440 项 collect 完全对应。
- AA 定向复核：1 passed；分包日志和 15 秒单请求超时有效。
- `git diff --check`：通过。

## 验收结论

本计划目标已完成。协议、导出、fixture、cleanup 的专用边界均保持；未覆盖已有未提交改动。后续仅需按主人安排，将当前改动拆分提交为公共工具、报警迁移、controller 迁移、文档/lint 等独立提交。

## 运行约束

- 工作目录：`jkpt_api_test`。
- Python：`.venv/Scripts/python.exe`。
- 推荐单测参数：`--confcutdir=unit -p no:cacheprovider --basetemp=temps/pytest-basetemp`。
- 默认服务地址来自 `JKPT_BASE_URL`；真实回归会创建/修改远端测试数据并依赖 cleanup。
