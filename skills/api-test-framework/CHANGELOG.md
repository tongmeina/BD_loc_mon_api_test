## [Unreleased] — 2026-08-28 普通 REST 断言统一

### Added
- `common.case_report_util.assert_response`：安全解析 JSON、可选 HTTP 校验、统一 `code/msg` 信封断言并返回领域数据。
- `common.requests_util.get_response_json`：缓存响应 JSON，供请求上下文、日志和断言复用。
- `jkpt_api_test/unit/test_case_report_util.py`：覆盖正常信封、缺字段、非 JSON、HTTP 可选校验、兼容入口、error_msg 和递归脱敏。
- `jkpt_api_test/tools/assertion_lint.py`：静态阻止普通 testcase 直接 `.json()`、手工解析 `$.code/$.msg` 或直连底层断言；`unit/test_assertion_lint.py` 覆盖扫描规则。

### Changed
- 13 个普通 REST controller 与验证码 controller 迁移到 `assert_response`；intercom 保留 `send_case/assert_case` 兼容契约和业务 rows。
- 报警模块增加分页/最新/类型统计结构断言，以及单条、按类型、按 ID 处理前未处理确认和处理后的目标状态轮询；状态字段按 AlarmInfoRespDto 的 NameValueHolder/handleTimeStr 兼容解析，未知状态不默认放行。
- `BaseRequest`、logger、断言附件与失败 Hook 统一递归脱敏；请求/响应已由传输层附加时 Hook 不重复附加。
- 协议 `result.success`、xlsx/KML/二进制导出专用断言保持不变。

### Security
- 请求、响应、业务上下文和扩展 rows 按键与值脱敏 Token、密码、验证码、手机号和邮箱。

---

## [Unreleased] — 2026-08-28 验证码接口测试与 PII 脱敏

### Added
- `jkpt_api_test/testcases/test_ver_code_controller.py`：7 个 `ver-codes` 发送接口的一类一接口 YAML 驱动测试，真实短信/邮件默认关闭，限频探测显式开关控制。
- `jkpt_api_test/yaml/test_ver_code_controller.yaml`：公共必填、格式、mode/to 不匹配、Authorization 通道和响应安全场景。
- `jkpt_api_test/unit/test_ver_code_support.py`：验证码请求日志/Allure 上下文的手机号、邮箱、Token 脱敏最小验证。
- `common/requests_util.py`：响应 JSON 缓存与递归敏感信息脱敏能力（由运行时工作区已有实现承接）。
- `common/logger_util.py`：请求、响应、键值日志复用结构化 PII 脱敏。

### Security
- 验证码测试的 Authorization、验证码不写入源码和报告明文；YAML 仅保留主人明确授权的两个专用测试接收端，运行日志与报告仍必须脱敏。
- 真实发送和低次数频控探测分别受 `JKPT_ENABLE_VER_CODE_DELIVERY`、`JKPT_ENABLE_VER_CODE_ABUSE_TEST` 控制。

---

## [Unreleased] — 2026-08-19 glht 入库记录清理改为精确登记

### Fixed
- `glht.py` 原按"session 起始日模糊字符串"猜测 SN 编码规则来批量删除入库记录，对 `generate_rescue_sn()`（月+日+时+分+秒+盐，无年份）生成的救援棒 SN 完全失效，只对含 `YYYYMMDD` 前缀的 SN（`terminal_type_enum_cases`）有效——迁移为按 sn 精确登记查删后，与 SN 格式完全无关

### Added
- `common/cleanup/glht.py`：`register(sn)`（副作用落地即注册入口）、`flush_cleaner`（tier410，批量执行删除）
- `common/cleanup/__init__.py`：包级入口 `register_glht_inventory`
- `references/cleanup-framework.md`：新增模板 D（逐项登记 + 集中批量收尾），适用于"批量接口 + 动态登记 + 需要逐项可诊断性"三者并存的场景

### Changed
- `glht.py` 从"半独立"（依赖 conftest 的 `glht_token`/`glht_base_url` fixture）改为完全自包含域模块（自读 `GLHT_*` 环境变量），对齐其余域模块的形状
- `registry.py` tier 语义文档新增 400/410（外部系统，两阶段"定位/执行"约定）
- `conftest.py` 删除独立的 `glht_base_url`/`glht_token`/`glht_cleanup_test_data` fixture 及 `pytest_session_start_day` 全局变量（唯一消费者已随之删除），glht 清理并入主 `cleanup_test_data` 调度
- `ENABLE_GLHT_CLEANUP` 默认值：`false` → `true`

### Removed
- `pytestconfig.stash["rescue_terminal_sns"]`：write-only 死数据（2 处写、0 处读），其预期消费方即本次迁移，已被 registry 逐项登记取代；连带移除 `rescue_sat_terminal`/`_provision_b_rescue_stick`/`rescue_sat_terminal_b`/`b2`/`b3` 中随之空转的 `pytestconfig` 形参
- `conftest.py` 的 `import hashlib`（唯一消费者 `glht_token` 已删除；glht 侧的 MD5 现由 `common/cleanup/glht.py` 自行 import）

### Breaking
- glht 清理从"独立于 `ENABLE_AUTO_CLEANUP` 运行"变为"并入 `run_session_cleanup`，受 `ENABLE_AUTO_CLEANUP` 总闸控制"——`ENABLE_AUTO_CLEANUP=false` 时会连带跳过 glht 清理（此前不会）。此时登记不会被清空（`registry` 纪律 3 的清表动作在 `run_session_cleanup` 的 `finally` 里，总闸关闭时整个调度不进入），登记与 `glht._pending_ids` 在进程内累积；同进程后续若跑一个开着总闸的 session，会把上一轮登记一并收走（补删，非泄漏）。单进程单 session 的常规跑法无影响
- `cleanup-report.yaml` 新增 `glht_inventory_<sn>` / `glht_inventory_flush` 两类 key；不影响已有 key

### Deferred（未处理，需后续单独决策）
- glht 后台历史遗留的存量入库记录（本次分析发现的量级：全量 1321 条，其中「今日」新增 141 条，均由 `terminal_type_enum_cases` 产生）本次不做一次性清理，仅保证"以后新造的都能精确清掉"

---

## [Unreleased] — 2026-08-19 清理框架统一化

### Fixed
- `unpaid_order.register()` 从未接入 `registry.register_cleanup`，导致待支付订单从不进入 session 收尾调度——迁移为逐项 domain 后正式接入

### Added
- `registry.py`：`register_cleanup_once`（挂载前查重）、`unregister_cleanup`（按 domain 精确移除）
- `references/cleanup-framework.md`：新增清理域的 2×2 决策矩阵 + 三套模板 + checklist + 可移植性说明

### Changed
- `unpaid_order.py` / `intercom_group.py` 从「共享 domain + 模块内平行列表」迁移为「动态·逐项 domain」，复用 `registry.py` 新原语
- `b_terminals`/`b_groups` 清理逻辑从 `conftest.py` 内联函数挪进 `common/cleanup/terminal.py`/`group.py`（`cleaner_b` 变体）
- `references/conftest-jkpt.md`：同步过期的「内部辅助函数不在 common/」描述，补链接到 `cleanup-framework.md`

### Breaking
- `cleanup-report.yaml` / session 清理报告的 domain 粒度从「聚合一行」变为「逐项一行」（如 `intercom_groups: ...` 变成多条 `intercom_group_<gid>: ...`）；无代码依赖旧 key 名（已检索确认），仅影响人工读报告时的行数

---

## [Unreleased] — 2026-08-18 开跑清空 Allure raw

### Added
- `common.run_artifact_util.wipe_allure_raw_dirs`：按项目根删除 `temps/`、`allure-results/`
- `pytest_configure` 开跑调用（`config.rootpath`）；不删 `reports/`，session 结束不删

---

## [Unreleased] — 2026-08-18 下单限频共享冷却钟

### Added
- `common.buy_cooldown_util`：`wait_buy_cooldown` / `mark_bought`（进程内 65s 钟；套餐/星豆/订单 lifecycle 共用）

### Changed
- 商城 `TestEcm05Buy`、星豆 `TestSb03Buy`、订单 `ensure_lifecycle_*` 改为共享钟；lifecycle 遇 999 再买一次再 skip

---

## [Unreleased] — 2026-08-18 待支付单 session 收尾

### Added
- `common.order_cleanup_util`：`register_unpaid_order_no` / `cleanup_registered_unpaid_orders`（进程内名单，不写 extract）
- `cleanup_test_data` 步骤 0.5：对本轮登记单 cancel→delete；`ENABLE_AUTO_CLEANUP=false` 时保留给人工扫码

### Changed
- 商城 / 星豆正向 buy 成功后登记订单号；用例内仍不 cancel `combo_order_no` / `star_bean_order_no`

---

## [Unreleased] — 2026-08-18 Suites 四层对齐

### Added
- `SKILL.md` 第 4 层「Allure Suites 四层对齐」：文件→类→方法→parametrize 为通用轴；默认一类一报告分组单元
- `yaml-conventions.md` §8：jkpt 填法（一类一 HTTP 接口、`TestEn01` 前缀、不传 ids）
- HTTP 模板改为多类骨架（`Test01`/`Test02` 占位前缀 + `_XxxHelpers` + module 清理）

### Changed
- 有状态默认改为模式 B′（文件内多类 + extract）；模式 B 单类切片标为勿用于 Suites
- YAML `name` 不再写成「Allure 标题」；叶子不传中文 `ids=`、不用 `@allure.title(name)`
- `jkpt-api-test.mdc`：拆类 / 禁止切片 / 禁止中文 ids 写入必须与禁止
- `CONTRIBUTING.md`：编码模式变更须同步 mdc
- `methods-reference.md`：`case_name` 只说明附件标题

### Deprecated
- 同一 Test 类内 `test_data[:N]` 切片 CRUD（Allure 会摊平）；改用一类一 `*_cases`

---

## [Unreleased] — 2026-08-14 正向 expected.msg / 负向 expected.error_msg

### Added
- `common.yaml_util.read_expected_msg`：正向读 `msg`，负向读 `error_msg`

### Changed
- 全部 jkpt YAML 正向用例由 `error_msg: "成功"` 改为 `msg: "成功"`；负向仍用 `error_msg`
- testcase / `export_assert_util` / 模板改为 `read_expected_msg(case["expected"])`
- `yaml-conventions.md`：正向禁止写 `error_msg: "成功"`

---

## [Unreleased] — 2026-08-13 技能追上代码与运行时对齐

### Added
- `common.yaml_util.resolve_extract_value` / `is_extract_placeholder`：统一解析 `{{var}}`，`required=True` 时 `pytest.skip`
- `common.captcha_util.generate_captcha_id`：登录与 conftest 共用
- `conftest-jkpt.md`：`msg_test_terminal`、`terminal_use_scopes`、`terminal_type_enum_cases`、glht 清理（默认关闭）
- `methods-reference.md`：`parse_response_json` / `NonJsonResponseError` / `get_last_http_context` / `get_current_timestamp` / `assert_export_response`

### Changed
- `write_yaml` 文档改为真实签名 `(file_path, data, mode="append")`
- CRUD 用例与模板改为 import `resolve_extract_value`，不再各写一份 `_resolve_value`
- 批量导入模板改为 `testcases/fixtures/batch_import_template.xlsx`
- `login.yaml` 改名为 `test_login.yaml`
- 登录凭据改环境变量；文档只写变量名
- `ENABLE_GLHT_CLEANUP` 默认 `false`，避免每场 session 都登录 glht
- `pyproject.toml` 声明 `jsonpath`；`.gitignore` 忽略 `reports/`、`temps/`、`extract.yaml`
- `CONTRIBUTING.md`：本技能仅作本仓生成依据，不再写「复制 4 文件到新项目」


### Removed
- `jkpt_api_test/api_test_framework/`（`run_case` 引擎，jkpt 从未引用）
- `assets/templates/test_case_yaml.tpl.py`（模式 C）

### Changed
- `SKILL.md` / `methods-reference.md`：引擎层改为「已移除」，生成路径只保留模式 A/B/B′ 与协议层

---

## [Unreleased] — 2026-08-13 技能目录迁到仓库根 `skills/`

### Changed
- 技能从套娃路径 `jkpt_api_test/api-test-framework/api-test-framework/` 迁至 `skills/api-test-framework/`，与 Python 包 `api_test_framework/` 区分
- `.cursor/rules/jkpt-api-test.mdc` 及技能内指向 `conftest.py` / `common/` / `yaml/` 的相对链接已同步

---

## [Unreleased] — 2026-05-15 技能同步重构

### Added（新增）
- `SKILL.md` 顶部 **jkpt 标准栈声明**：明确通用层/适配层/禁止项三类边界
- `references/conftest-jkpt.md`（适配层）：jkpt 专属 fixture 表 + 依赖图
- `references/yaml-conventions.md`（适配层）：jkpt YAML 命名与占位符约定
- `references/methods-reference.md` 新增协议层 4 模块章节：
  - `common/bd_protocol_client.py`（11 个 `send_*`）
  - `common/protocol_transport.py`
  - `common/protocol_codec.py`
  - `common/protocol_types.py`
- `assets/templates/test_case_protocol.tpl.py`：协议用例模板
- `CONTRIBUTING.md`：文档同步约定
- `.cursor/rules/jkpt-api-test.mdc`（仓库根 `.cursor/rules/`）：Cursor 生成约束

### Changed（修改）
- `SKILL.md` 第 1 层增加「jkpt 不使用」警示；模式 C 标 `[可选/jkpt 未使用]`
- `SKILL.md` 项目文件结构骨架补充协议层 4 模块
- `references/methods-reference.md` 目录按「通用层 / 适配层 / 历史归档」分组
- `assets/templates/test_case_yaml.tpl.py` 文首标「jkpt 未使用，勿复制」

### Deprecated（标记弃用 / 勿生成）
- `api_test_framework.run_case`（jkpt 未使用）
- `api_test_framework/pytest_plugin.py`（文件不存在）
- `pytest_plugins = ["api_test_framework.pytest_plugin"]`

### Archived（归档）
- `拟改动范围说明.md` → `archive/拟改动范围说明.md`（其内容大部分已落地，由本 CHANGELOG 代替跟踪）

---

## 维护模板

```markdown
## [Unreleased] — YYYY-MM-DD <变更主题>

### Added
- `<新增文件或章节>`：<一句话用途>

### Changed
- `<被改文件>`：<改了什么、影响范围>

### Deprecated
- `<旧 API>`：<为何弃用、替代方案>

### Removed
- `<被删>`

### Fixed
- `<文档错误纠正>`
```
