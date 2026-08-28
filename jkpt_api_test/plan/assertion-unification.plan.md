# 接口断言统一改造计划（不使用 Schema）

> 编写日期：2026-08-28  
> 适用范围：`jkpt_api_test` 接口自动化测试  
> 执行状态：已完成。核心公共入口、PII 脱敏、controller 信封迁移、报警结构/处理前后置断言、规则与静态检查均已落地；工具单测 27 项、全量编译、断言 lint、440 项 collect 和分组真实接口回归均已通过。

## 1. 一句话决策

不把全项目压成一种“万能断言”，也不引入 JSON Schema、Pydantic、DeepDiff 或完整响应 Golden 比对；采用“统一响应信封入口 + 轻量字段断言 + rows 业务断言 + 领域后置断言”的分层方案。

## 2. 当前基线与统计口径

当前断言差异需要分三个维度统计，不能简单相加为一个互斥数量：

### 2.1 主要断言路径：3 类

1. **标准响应信封断言**
   - 通过 `assert_api_result()` 比较响应体 `code + msg`。
   - 代表：`test_alarm_controller.py` 及多数普通 REST 测试模块。

2. **信封断言 + rows 扩展断言**
   - `assert_case()` 负责 YAML expected 与响应信封。
   - `report_extra_and_assert()` 负责结构、业务关系、分页、状态、幂等等扩展验证。
   - 代表：`test_intercom_group_controller.py`、`test_intercom_message_controller.py`。

3. **协议/导出特殊断言**
   - 协议结果 `result.success`。
   - HTTP 状态、二进制文件非空、文件头、Content-Type、文件名、表头等导出断言。

### 2.2 底层失败机制：约 6 类

1. Python 直接 `assert`。
2. `assert_api_result()` 内部断言。
3. `report_extra_and_assert()` 最终抛出 `AssertionError`。
4. 业务代码直接 `raise AssertionError`。
5. `pytest.fail()`，主要用于前置造数或动态 ID 提取失败。
6. HTTP/协议结果判断，例如 `status_code`、`result.success`。

这些机制存在包装和嵌套关系，不作为互斥总数对外宣称。

### 2.3 验证深度：4 层

1. 响应信封：`code/msg/error_msg`。
2. 响应结构：关键字段存在性、类型、列表形态。
3. 业务语义：字段值、枚举、分页守恒、跨接口关系。
4. 后置状态：落库结果、状态变化、幂等、副作用。

### 2.4 已确认的现状

- 当前没有统一 JSON Schema、Pydantic、DeepDiff 或完整响应体等值比对。
- 普通 REST 接口普遍不直接断言 `response.status_code`。
- 绝大多数 YAML expected 只描述 `code/msg/error_msg`，没有完整响应契约。
- 没有直接连接数据库、Redis 后进行断言的模式；落库主要通过后续 REST 查询或业务流水接口间接验证。
- `pytest.skip` 是控制流，不是断言；cleanup-report 记录也不是普通 pytest 断言。

## 3. 改造目标

### 3.1 必须达到

- 所有普通 REST 接口拥有统一的响应解析和信封断言入口。
- 缺少 `code`、非 JSON 响应、消息缺失等异常可以形成清晰失败，而不是随机 `IndexError` 或不可读异常。
- 失败上下文至少包含：
  - 用例名称
  - 请求方法
  - URL
  - 请求参数或请求体
  - 预期 code/msg
  - 实际 code/msg
  - 关键业务 ID（存在时）
- 保留对讲群现有的结构、业务关系、跨接口和后置状态断言。
- 报警模块补齐最小必要的结构断言和写操作后置验证。
- 统一过程中不引入 Schema，不重写成完整响应模型。

### 3.2 明确不做

- 不把所有直接 `assert` 替换成公共 helper。
- 不把所有业务逻辑放入公共断言工具。
- 不强制所有接口默认 `HTTP 200`。
- 不将协议造数、导出文件断言强行塞入普通 JSON 断言。
- 不在本次改造中引入数据库、Redis 直连校验。
- 不一次性重写全部测试模块。
- 不改变现有用例执行顺序、fixture 生命周期、extract.yaml 语义和 cleanup 行为。

## 4. 目标断言分层

### 4.1 公共响应入口

在现有 `common/case_report_util.py` 基础上增加统一响应入口，或以兼容方式演进现有工具；底层仍复用 `common/allure_assert_util.py` 的 `assert_api_result()`。

建议能力：

```text
assert_response(case, response, biz_context, expected_http_status=None)
    1. 安全解析 response.json()，只解析一次
    2. 按需校验 HTTP status
    3. 用 jp_first 提取 $.code / $.msg
    4. 读取 expected.code 与 expected.msg/error_msg
    5. 调用 assert_api_result
    6. 返回 json_data，供后续领域断言使用
```

要求：

- `expected_http_status` 默认不启用。
- 只有用例明确配置 HTTP 期望值时才校验。
- `code` 缺失必须生成明确的“响应缺少 $.code”失败。
- `msg` 缺失与 `msg == ""` 的行为要明确区分或在公共层统一记录。
- 保留正向精确匹配、负向 error_msg 读取和特殊场景包含匹配能力，不强行合并成一种策略。

### 4.2 YAML 用例适配

现有 `assert_case(case, json_data, biz_context)` 先保留，作为兼容包装层。

迁移期间不直接修改所有调用方的签名：

```text
旧调用：send_case → assert_case
新调用：统一响应入口
兼容层：assert_case 继续支持旧调用
```

YAML 只允许逐步增加可选字段，不进行批量重写：

```yaml
expected:
  code: 0
  msg: 成功
  http_status: 200   # 可选，未声明时不校验
```

本阶段不引入 Schema，也不要求为所有现有用例补充 `http_status`。

### 4.3 rows 扩展断言

保留 `report_extra_and_assert()` 的业务定位：

- 公共层负责打印、Allure 附件和失败汇总。
- 测试模块负责构造业务 rows。
- 不在公共层解释“报警是否已处理”“消息是否串群”等领域概念。

初期不强制改名，避免影响两个 intercom 模块；如果后续统一命名，提供兼容别名后再逐步迁移。

### 4.4 轻量字段断言

只提供少量原子能力，例如：

- 字段是否存在
- 字段是否为指定基础类型
- 列表是否为空/非空
- 值是否相等
- 值是否包含关键字

不建立字段定义文件，不实现伪 Schema 框架。

### 4.5 领域后置断言

写接口仍由领域测试执行：

```text
操作前查询
→ 调用写接口
→ 等待/轮询异步结果
→ 操作后查询
→ 用 rows 验证状态和副作用
```

公共层不抽象成通用状态机，因为清未读、处理报警、关群、删群、扣豆和订单状态的后置条件不同。

## 5. 两个重点模块的改造方案

### 5.1 `test_alarm_controller.py`

#### 第一阶段：统一信封断言

目标位置：

- `test_alarm_controller.py:283-301` 的 `_assert_and_report()`

改造要求：

- 删除该方法中重复的 `res.json()`、JSONPath 和日志逻辑，改为调用公共响应入口。
- 保留现有请求 URL、参数、用例顺序、协议造数和动态 ID 提取逻辑。
- 统一补充请求上下文。
- 缺少 `code` 时不能再出现裸 `IndexError`。

#### 第二阶段：补查询类关键结构断言

适用接口：

- `/api/monitor/alarms`
- `/api/monitor/alarms/{addr}`
- `/api/monitor/alarms/latest/{addr}`
- `/api/monitor/alarms/batch-info`

只增加关键字段级检查，例如：

- `data.items` 或实际列表字段为 `list`。
- 报警记录的 `id` 非空。
- 最新报警响应在成功场景存在目标对象。
- 分页字段在实际存在时类型正确。

字段名称必须以当前接口实测响应和最新契约为准，不预设完整报警对象 Schema。

#### 第三阶段：补单条处理后置断言

当前流程：

```text
造数
→ 提取 alarm_id
→ PUT 处理
→ 只校验 code/msg
```

目标流程：

```text
造数
→ 精确提取本轮 alarm_id
→ 查询处理前状态
→ PUT 处理
→ 轮询查询同一 alarm_id
→ 验证处理状态/处理结果
```

要求：

- 不能用全局最新报警替代本轮唯一 ID。
- 不能在异步写入场景只做一次立即查询。
- 明确超时、业务失败和查询不到记录三类失败。
- 状态字段以真实接口字段和最新需求为准；当前 Swagger `AlarmInfoRespDto` 的权威证据为 `handleStatus.name/value` 与 `handleTimeStr`，未知状态返回不可判定并失败，不默认当作未处理。

#### 第四阶段：补批量处理后置断言

在单条处理稳定后再实施：

- 处理前记录目标 ID 集合。
- 处理后按目标 ID 集合复核。
- 验证实际处理对象，而不是只验证接口返回成功或全局数量变化。
- 对重复处理、空 ID、混入历史数据进行独立处理。

### 5.2 `test_intercom_message_controller.py`

不重写现有业务断言，只做底层入口收敛：

- 保留 `send_case()`、`assert_case()` 的兼容行为，逐步接入统一响应解析。
- 保留 `test_intercom_message_controller.py:217-240` 的 fixture 事实直接断言。
- 保留 `:290-357` 的消息字段断言。
- 保留 `:429-471` 的分页守恒断言。
- 保留 `:659-686`、`:703-722` 的未读和幂等断言。
- 保留 `:735-795` 的关群/删群后状态断言。
- 负向用例继续允许信封通过后提前返回，不能强制套成功响应结构。
- `cross_account` 等“缺陷留痕”场景的业务口径不在本次统一中改写。

## 6. 分阶段实施顺序

### Phase 0：基线冻结与工具自测

工作项：

1. 固化当前断言模式清单和代表用例。
2. 为公共响应入口准备单元级测试数据：
   - 正常 `code/msg`
   - error_msg
   - 缺少 code
   - 缺少 msg
   - msg 为 null
   - 非 JSON 响应
   - HTTP 状态与业务 code 不一致
3. 记录迁移前的日志和 Allure 失败上下文表现。

通过条件：公共工具测试完成，未改业务用例行为。

### Phase 1：公共响应入口

工作项：

1. 在公共工具中实现安全响应解析和统一上下文。
2. 保留 `assert_api_result` 作为底层 code/msg 断言。
3. 保留 `assert_case` 兼容入口。
4. 不默认增加 HTTP 状态断言。

通过条件：旧 intercom 用例无需改调用方式即可继续使用。

### Phase 2：报警模块信封迁移

工作项：

1. 迁移 `_AlarmHelpers._assert_and_report()`。
2. 迁移列表、历史、最新、批量信息和处理接口。
3. 维持原 YAML 和类执行顺序。
4. 对比迁移前后的请求数量、响应 code/msg 和失败归因。

通过条件：报警模块原有正向、负向用例行为不发生非预期变化。

### Phase 3：报警结构和单条后置断言

工作项：

1. 添加关键字段 rows。
2. 增加单条处理前后状态轮询。
3. 处理未知状态字段的兜底策略，避免默认“未知即未处理”造成误选。

通过条件：既能发现“code=0 但状态未改变”，又不因异步延迟产生稳定性回退。

### Phase 4：批量处理和其他模块渐进迁移

工作项：

1. 在单条处理稳定后补批量处理后置验证。
2. 每次只迁移一个控制器。
3. 优先迁移存在私有 `_assert_and_report` 或重复 `code/msg` 解析的模块。
4. 导出和协议保留专用断言入口。

通过条件：每个模块独立回归通过后再进入下一个模块。

### Phase 5：规则固化与文档

工作项：

1. 更新测试框架说明和断言使用规范。
2. 增加可执行静态检查：普通 testcase 不得直接 `.json()`、自行解析 `$.code`/`$.msg` 或直连底层 `assert_api_result`。
3. 明确 `assert`、`pytest.fail`、`pytest.skip`、cleanup 记录的使用边界。
4. 建立控制器迁移清单，不追求一次性清零旧代码；协议、导出、cleanup 和 fixture 保留明确例外边界。

## 7. 风险矩阵与控制措施

| 风险 | 等级 | 具体表现 | 控制措施 |
|---|---|---|---|
| 误把 `assert_case` 和 `assert_api_result` 当成两套平行底层机制 | 高 | 重复抽象、调用链变复杂 | 保留低层 `assert_api_result`，上层只做适配 |
| 统一入口改变负向用例行为 | 高 | 错误响应没有 data 却被按成功结构校验 | 保留 `code != 0` 提前返回语义 |
| 全局强制 HTTP 200 | 高 | 400/401/403/404 负向用例误报 | `http_status` 可选，按用例声明 |
| 改写 intercom 业务 rows | 高 | 丢失分页、幂等、跨接口业务证据 | 只改入口和报告，不改业务 rows |
| 写接口立即查询后置状态 | 高 | 异步延迟、读写分离导致 flaky | 使用轮询、明确超时和证据 |
| 改变 `send_case` 返回值或签名 | 高 | 多个 intercom 模块同时回归 | 先增加兼容入口，不直接替换旧签名 |
| 响应被重复 `.json()` 解析 | 中 | 异常位置、日志顺序、性能变化 | 明确公共入口只解析一次 |
| YAML 新增字段导致契约漂移 | 中 | 旧用例默认行为变化 | 新字段可选，缺省保持旧语义 |
| 直接 assert 全量迁移 | 中 | 失败定位可能变差，代码变冗长 | 保留 fixture 和本地不变量的直接 assert |
| 动态 ID 混入历史脏数据 | 高 | 后置断言验证错对象 | 使用本轮造数 ID，禁止仅按全局最新判断 |
| fixture/执行序/cleanup 被改动 | 高 | 共享数据、extract、清理行为异常 | 每阶段保持执行序和 teardown 不变 |
| 状态字段未知时默认未处理 | 中 | 错误选取报警 ID | 先确认真实状态字段，再收紧兜底策略 |
| 将 cleanup 记录当成普通断言 | 中 | 改变测试主结果和 cleanup-report | cleanup 框架单独维护 |

## 8. 回归与验收标准

### 8.1 工具层

- 缺少 `code` 时输出明确字段缺失错误。
- 非 JSON 响应输出响应解析失败上下文。
- `code/msg` 不匹配时保留 case、预期、实际和业务上下文。
- Allure 成功/失败附件行为不出现非预期丢失。

### 8.2 报警模块

- 正向列表、历史、最新、批量信息用例可正常完成。
- 负向 code/msg 断言行为与迁移前一致。
- 协议造数失败仍归类为前置失败。
- 动态报警 ID 提取失败仍能明确定位。
- 单条处理后能够确认目标报警状态变化。
- 批量处理后能够确认目标 ID 集合的处理结果。

### 8.3 对讲模块

- 现有消息字段、分页守恒、双群一致性、未读、幂等、关删群状态断言全部保留。
- 不改变跨账号缺陷留痕场景的现网口径。
- 不改变 fixture 顺序、extract 写入和 cleanup 注销行为。

### 8.4 统一规则

- 新增普通 REST 用例必须经过公共响应信封入口。
- 新增业务字段验证优先使用领域 rows 或清晰的局部 assert。
- `pytest.fail` 仅用于不可继续的前置/提取失败。
- `pytest.skip` 必须在报告中与 passed/failed 区分。
- 不新增 Schema 类依赖或完整响应模型。

### 8.5 当前验证记录

已执行并通过：

- 工具及辅助单测：27 passed（使用 `--basetemp=temps/pytest-basetemp`，避开系统临时目录权限限制）。
- 全量 Python 编译：`common`、`testcases`、`unit`、`tools`。
- 普通 testcase 断言静态检查：0 violations。
- 全量收集：440 tests collected。
- 基础 controller 分组：137 passed，0 failed，0 skipped，214.97s；设备 39/39、分组 3/3、GLHT 入库记录 36/36 清理成功。
- BD 协议分组：13 passed，0 failed，0 skipped，61.24s；设备 0/0、分组 3/3 清理成功；AA 图片 7/7 分包均返回 HTTP 200/code=0。
- emergency 分组：109 passed，0 failed，0 skipped，217.65s；求救群无活跃残留，订单、设备 1/1、分组 3/3、GLHT 1/1 清理成功。
- intercom + 验证码分组：172 passed，0 failed，9 skipped，93.65s；对讲群全部关闭并删除，设备 11/11、分组 4/4、GLHT 11/11 清理成功。
- 真实接口回归合计：431 passed，0 failed，9 skipped；与 440 项 collect 完全对应。
- AA 协议定向复核：1 passed；修复后的分包级日志和 15 秒单请求超时已验证有效。
- `git diff --check`：通过；仅有既有 `openpyxl` 样式 warning，不影响测试结果。

验收结论：本计划目标已完成。

## 9. 回滚策略

每个阶段独立提交，禁止把公共工具、报警迁移、后置断言和其他模块迁移放在同一提交中。

回滚顺序：

1. 先回滚当前控制器的调用切换。
2. 保留公共工具新增能力，但不影响旧入口。
3. 若公共工具改变旧行为，则恢复兼容包装逻辑。
4. 后置断言出现异步不稳定时，先关闭新增后置检查，不回滚已有信封断言。
5. 不使用 `git reset --hard` 覆盖主人已有未提交修改；通过独立提交或精确反向修改回滚。

## 10. 最终目标形态

```text
普通 REST：统一响应信封入口
          + 可选 HTTP 状态
          + 领域 rows/局部字段断言

写接口：  信封断言
          + 领域后置查询
          + 状态/副作用/幂等验证

协议接口：result.success 等专用结果断言

导出接口：JSON 或二进制专用断言

前置失败：pytest.fail
测试跳过：pytest.skip
收尾清理：cleanup 独立记录
```

最终收敛目标不是“全项目只剩一个断言函数”，而是：

> **所有普通接口使用同一套信封断言骨架；业务断言按领域保留；特殊协议、导出、前置失败和 cleanup 不被错误统一。**
