# 接口断言统一改造执行审计报告

> 审计日期：2026-08-28  
> 审计范围：`jkpt_api_test/testcases/test_*.py`、公共断言工具、静态检查工具及 `assertion-unification.plan.md`  
> 对照计划：[`assertion-unification.plan.md`](assertion-unification.plan.md)

---

## 1. 审计结论

原计划的核心公共断言骨架已经落地，但“执行状态：已完成”的表述偏乐观。

准确状态应为：

> **统一响应信封骨架已完成；Intercom 领域扩展断言已完成；报警领域断言部分完成；其他 Controller 的业务扩展断言和 Allure 成功证据展示仍待迁移。**

| 目标 | 审计状态 | 说明 |
|---|---|---|
| 普通 REST 统一响应信封入口 | 已完成 | 14 个模块使用 `assert_response`，2 个 Intercom 模块使用兼容 `assert_case` |
| 缺少 `code`、缺少 `msg`、非 JSON 清晰失败 | 已完成 | 公共工具及单元测试已覆盖 |
| Intercom 原有业务 rows 保留 | 已完成 | 消息、分页、未读、幂等、关群、删群等断言均保留 |
| 报警查询结构断言 | 部分完成 | 已检查列表、ID、最新报警和 batch-info 外层类型；分页字段及元素结构未完整验证 |
| 报警单条和批量处理后置验证 | 部分完成 | 已按目标 ID 轮询状态；处理结果文本和批量复杂边界未完整覆盖 |
| 所有 Controller 都有领域扩展断言 | 未计划、未完成 | 原计划明确不一次性重写全部模块 |
| Allure 扩展断言展示统一 | 未完成 | 大量业务校验使用原生 `assert`，成功时不生成 `【扩展】`附件 |
| 静态 lint 证明所有请求均走统一入口 | 未完成 | lint 只能阻止部分反模式，不能证明所有执行分支都调用公共入口 |

---

## 2. 为什么 Allure 中大部分只有标准断言

### 2.1 标准断言

普通 REST 请求调用：

```text
assert_response
→ assert_case
→ assert_api_result
```

成功时生成：

```text
【成功】验证结果
```

该附件主要证明响应信封中的 `code`、`msg/error_msg` 符合 YAML 期望。

### 2.2 结构化扩展断言

只有业务测试调用 `report_extra_and_assert()` 时，成功结果才会生成：

```text
【扩展】分页正向
【扩展】字段级校验
【扩展】未读清零
【扩展】报警分页结构
```

### 2.3 原生 `assert`

很多模块已有业务字段或状态校验，但使用 Python 原生 `assert`：

```python
assert hit, "模糊查询未命中目标群"
assert not strangers, "查询结果包含无关群"
```

这种断言：

- 失败时 pytest 能正确失败；
- 成功时不会生成 Allure 扩展附件；
- 报告中看起来仍然只有标准 `code/msg` 断言。

因此当前问题分为两类：

1. **报告可见性不统一**：有业务断言，但成功证据没有展示在 Allure。
2. **业务覆盖深度不统一**：部分 CRUD 模块确实只验证标准响应信封。

---

## 3. 全项目断言调用统计

统计范围：17 个 `testcases/test_*.py` 文件。数量为静态调用点，不是参数化后的执行次数。

| 断言类型 | 静态调用点 |
|---|---:|
| `assert_response` | 50 |
| `assert_case` | 20 |
| `report_extra_and_assert` | 47 |
| `report_extra` | 3 |
| Python 原生 `assert` | 136 |
| `pytest.fail` | 12 |

> 注意：一个公共 helper 中只有一个 `assert_response` 静态调用点，但运行时可能被数十条参数化用例复用。

---

## 4. 各模块扩展断言覆盖

| 模块 | 结构化扩展 `report_extra_and_assert` | 原生 `assert` | 审计结论 |
|---|---:|---:|---|
| `test_intercom_group_controller` | 24 | 0 | 结构化扩展断言最多，计费、成员、邀请、群状态等闭环充分 |
| `test_intercom_message_controller` | 18 | 9 | Allure 展示最完整；9 个原生断言主要属于 fixture 链自检 |
| `test_alarm_controller` | 5 | 1 | 有报警结构和处理前后状态验证，但计划细项未全部落地 |
| `test_emergency_chat_controller` | 0 | 50 | 业务断言非常多，但成功结果在 Allure 中基本不可见 |
| `test_star_bean_controller` | 0 | 23 | 金额、套餐、余额、流水等业务校验存在，但没有扩展附件 |
| `test_emergency_combo_controller` | 0 | 17 | 套餐、价格、余量、下单字段及订单可见性校验存在 |
| `test_bd_protocol_client` | 0 | 14 | 协议专用 `result.success` 等断言，不适用普通 REST 信封模型 |
| `test_emergency_order_controller` | 0 | 10 | 状态、取消、删除后复核存在，但没有扩展附件 |
| `test_intercom_message_controller` fixture | 已计入 | 9 | fixture 事实自检，不属于普通接口字段断言 |
| `test_ver_code_controller` | 0 | 8 | PII、Token、验证码泄漏和响应头安全专项断言 |
| `test_enclosure_controller` | 0 | 4 | 主要是列表命中及 KML/XML 导出断言；写接口闭环不完整 |
| `test_alarm_settings_controller` | 0 | 0 | 基本只有标准信封，更新后没有 GET 复核 |
| `test_batch_terminal_controller` | 0 | 0 | 普通写接口主要只有信封；导出使用专用断言 |
| `test_field_template_controller` | 0 | 0 | CRUD 基本只有标准信封 |
| `test_group_controller` | 0 | 0 | 创建、更新、排序、删除缺少明确后置状态断言 |
| `test_location_controller` | 0 | 0 | 查询和导出模块，导出使用专用断言 |
| `test_login` | 0 | 0 | 当前以负向登录信封断言为主 |
| `test_terminal_controller` | 0 | 0 | 编辑、关注、移动等写操作缺少读侧复核 |

---

## 5. 三个重点模块对比

| 模块 | 标准信封调用 | 结构化扩展 | 原生断言 | 特点 |
|---|---:|---:|---:|---|
| `test_intercom_group_controller` | `assert_case` 15 | 24 | 0 | 扩展业务面最广，跨成员、计费、邀请、群状态链路丰富 |
| `test_intercom_message_controller` | `assert_case` 5 | 18 | 9 | 字段、分页、双群一致性、未读、幂等、关删群状态最细 |
| `test_alarm_controller` | `assert_response` 1 个公共入口 | 5 | 1 | 扩展数量较少，但处理前后按目标 ID 轮询质量较高 |

### 5.1 `test_intercom_message_controller`

已覆盖：

- 消息 ID、群 ID、发送类型和时间戳；
- TEXT 定位字段；
- VOICE 时长、大小和内容；
- 三设备发送者映射；
- 对讲群和 SOS 群双落一致性；
- 分页条数、唯一性、并集及 `totalPage` 守恒；
- 接收明细与消息级计数一致性；
- 清未读前后状态；
- 二次清理幂等；
- 关群、删群后的消息和聊天项状态。

### 5.2 `test_intercom_group_controller`

已覆盖：

- 群创建字段；
- 创建、邀请后的星豆流水与余额守恒；
- 改名后查询复核；
- 邀请、重复邀请和通知状态；
- 成员昵称、移除、关闭状态；
- 同意、拒绝和重复处理；
- 设备跨群前后成员集合变化；
- 满员后的成员数和扣费行为。

### 5.3 `test_alarm_controller`

已覆盖：

- 报警分页外层结构和 ID 非空；
- 最新报警对象结构；
- batch-info 外层类型；
- 本轮报警 ID 提取；
- 处理前未处理状态确认；
- 单条、按类型批量、按 ID 批量处理后的状态轮询。

仍缺：

- 分页字段存在时的类型检查；
- batch-info 每个元素的字段及类型检查；
- 处理后 `handleResult` 与本次提交值严格一致；
- 查询业务失败、目标不存在、状态未变化、轮询超时的精确分类；
- 重复 ID、合法 ID 与不存在 ID 混合、历史 ID 混入等批量边界。

---

## 6. 按计划 Phase 审计

| 阶段 | 计划内容 | 审计状态 | 说明 |
|---|---|---|---|
| Phase 0 | 基线冻结与工具自测 | 部分完成 | 27 项工具单测存在；缺可机器复核的迁移前后日志与 Allure 对照产物 |
| Phase 1 | 公共响应入口 | 已完成 | `assert_response → assert_case → assert_api_result` 已落地 |
| Phase 2 | 报警模块信封迁移 | 已完成 | 报警主接口统一进入公共信封入口 |
| Phase 3 | 报警结构和单条后置断言 | 部分完成 | 结构、前后轮询已实现；分页、处理结果和失败分类不完整 |
| Phase 4 | 批量处理和其他模块渐进迁移 | 部分完成 | 报警目标 ID 集合复核已实现；其他 Controller 深度迁移有限 |
| Phase 5 | 规则、文档和静态检查 | 已完成 | 文档、模板和 lint 已落地，但 lint 不是完整覆盖证明 |

---

## 7. 主要覆盖缺口

### 7.1 高风险：写接口只验证成功信封

这些模块可能出现“接口返回 `code=0`，实际状态未落地”的假阳性。

| 模块 | 当前缺口 |
|---|---|
| `test_field_template_controller` | 更新名称后不查；保存字段后不查；删除后不确认消失 |
| `test_group_controller` | 更新后不查名称；排序后不查顺序；删除后不查消失 |
| `test_terminal_controller` | 编辑、关注、移动后不查实际设备状态 |
| `test_batch_terminal_controller` | 导入后不查新增；移动后不查分组；解绑后不查消失 |
| `test_alarm_settings_controller` | 编辑和还原后均未 GET 验证开关状态 |

### 7.2 中风险：有部分后置验证

| 模块 | 当前缺口 |
|---|---|
| `test_enclosure_controller` | 创建后列表复核存在；更新、绑设备和删除闭环不完整 |
| `test_star_bean_controller` | 响应字段和金额关系较充分；下单后未查询订单确认副作用 |

### 7.3 设计上合理的特殊模块

| 模块 | 原因 |
|---|---|
| `test_login` | 当前主要验证负向认证响应 |
| `test_ver_code_controller` | 明确只验证发送接口及安全性，不消费验证码或调用下游接口 |
| `test_location_controller` | 查询、轨迹和导出，无普通写状态 |
| `test_bd_protocol_client` | 协议客户端连通性和发送结果测试，使用专用断言 |

---

## 8. 静态 lint 的能力边界

### 8.1 能检查

- testcase 直接调用无参数 `.json()`；
- testcase 直接导入底层 `assert_api_result`；
- 部分模块别名形式调用底层断言；
- 使用字面量 JSONPath 自行解析 `$.code`、`$.msg`；
- Python 语法错误。

### 8.2 不能检查

- 每个测试函数是否实际调用 `assert_response` 或 `assert_case`；
- 每个执行分支是否都经过统一入口；
- `json_data["code"]`、`json_data.get("msg")` 等直接字典解析；
- 业务字段、分页、状态和副作用是否有断言；
- 写接口是否执行后置查询；
- 报警 ID 是否属于本轮造数；
- 异步状态是否通过轮询验证；
- Allure 扩展附件是否真实生成；
- 原生 `assert` 成功结果是否具备报告证据。

因此：

> **`0 violations` 仅表示未发现当前 lint 定义的反模式，不等于所有接口均具有业务扩展断言，也不等于所有请求都经过公共信封入口。**

---

## 9. 根因分析

### 9.1 原计划目标不是“所有接口都有扩展附件”

计划明确要求：

- 不把全项目压成万能断言；
- 不替换所有直接 `assert`；
- 不一次性重写全部模块；
- 保留协议、导出和领域专用断言。

因此统一工作的首要目标是响应信封和失败上下文，而不是全项目业务断言补齐。

### 9.2 Intercom 模块原本业务链最复杂

Intercom 涉及：

- 多设备和多成员；
- 群状态；
- 消息结构；
- 分页；
- 未读；
- 幂等；
- 星豆扣费；
- 关群、删群和通知状态。

它天然需要更多领域 rows，所以 Allure 中的扩展附件最明显。

### 9.3 其他模块沿用了原生 `assert`

计划明确不强制替换直接 `assert`，导致业务校验的展示形式没有统一。测试能发现失败，但成功证据不容易从报告中审阅。

### 9.4 CRUD 模块只完成信封迁移

字段模板、分组、设备、批量设备和报警设置等模块主要完成了公共入口迁移，没有同步增加完整读写闭环。

---

## 10. 整改建议与优先级

### P0：修正计划状态

将 `assertion-unification.plan.md` 顶部状态调整为：

> 核心公共响应入口和 Intercom 领域断言已完成；报警领域断言部分完成；其他 Controller 业务扩展断言按优先级渐进迁移。

避免“已完成”被理解为所有模块都具备完整扩展断言。

### P1：补高风险写接口后置验证

建议顺序：

1. `test_field_template_controller`
2. `test_group_controller`
3. `test_terminal_controller`
4. `test_batch_terminal_controller`
5. `test_alarm_settings_controller`

基本模式：

```text
操作前查询
→ 调用写接口
→ 标准信封断言
→ 操作后查询
→ 结构化 rows 验证字段、状态或副作用
```

### P2：统一已有原生业务断言的 Allure 展示

优先迁移：

- `test_emergency_chat_controller`
- `test_star_bean_controller`
- `test_emergency_combo_controller`
- `test_emergency_order_controller`
- `test_ver_code_controller`

原则：

- 不改变业务逻辑；
- 将同一业务场景的多个原生 `assert` 汇总成 rows；
- 使用 `report_extra_and_assert()` 输出成功和失败证据；
- fixture 内简单不变量可继续使用原生 `assert`。

### P3：完成报警计划剩余项

- 分页字段类型检查；
- batch-info 元素结构；
- `handleStatus` 与 `handleResult` 联合验证；
- 查询失败类型精确分类；
- 批量重复 ID、混合 ID、历史 ID 边界；
- 批量结果按目标 ID 集合汇总展示。

### P4：增强静态检查

可增加规则：

- 普通测试方法调用 `send_request` 后必须存在信封入口或明确特殊豁免；
- 标记直接读取 `json_data["code"]`、`json_data.get("msg")`；
- 递归扫描 `testcases` 子目录；
- 对新增写接口提示后置断言审查，而非自动判定失败。

---

## 11. 建议目标形态

```text
普通查询接口
  请求
  → 统一信封断言
  → 关键结构/字段扩展断言

普通写接口
  操作前查询
  → 写请求
  → 统一信封断言
  → 操作后查询或轮询
  → 状态/字段/副作用扩展断言

协议接口
  result.success
  → 必要时由 REST 查询验证服务侧落库

导出接口
  HTTP/Content-Type/文件名/文件内容/表头等专用断言

fixture
  保留简洁原生 assert

Allure
  标准信封使用【成功】验证结果
  业务字段和状态使用【扩展】结构化附件
```

---

## 12. 最终判定

`assertion-unification.plan.md` **有执行，但不是严格全部完成**。

已完成的是：

- 公共响应解析与信封断言入口；
- 错误上下文和安全解析；
- Intercom 领域 rows 保留；
- 报警核心处理前后轮询；
- 规则、文档和静态反模式检查。

未完整完成的是：

- 报警计划全部细项；
- 其他 Controller 的业务扩展和写后状态验证；
- 原生业务断言的 Allure 成功证据展示；
- 静态检查对统一入口覆盖和业务深度的证明。

最终结论：

> **当前项目已实现“统一标准信封”，尚未实现“全模块统一扩展断言与业务闭环”。**
