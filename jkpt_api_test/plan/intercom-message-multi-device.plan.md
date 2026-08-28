# Context

当前 `intercom_message_group` 使用一台 A 账号救援棒串行发送 `flag=1 → flag=2 → flag=0 → flag=10 → speech`，同设备四次间隔默认 62 秒，整条 session 造数约 4～5 分钟。目标是在保留 SOS 状态机、双落群、零增长和取消后语音单落等现有覆盖的前提下，改为三设备分工：

- A账号设备A：`flag=1` 按键SOS、`flag=10` 取消SOS；
- A账号设备B：`flag=2` 落水SOS、`flag=0` 心跳解除SOS；
- B账号设备C：加入 A 创建的对讲群后发送 VOICE，并复用现有 B棒4成员侧查询/清未读能力。

预期通过“不同设备快速顺序发送、同设备独立冷却”把主要等待从 `4 × 62s` 压缩为 `1 × 62s`，目标总耗时不超过约 90 秒。该优化依赖若干现网未知事实，必须先探针、后改正式 fixture；任何硬前提失败都停止，不自动退回慢链掩盖问题。

> **✅ 已落地（2026-08-24）**：探针 + 正式改造 + 两轮全量回归完成。
>
> 探针实证（P0 全部通过）：
> - 62 秒限制确认为**终端级**：跨设备背靠背上行实测间隔仅 0.03s，均被接受并落库
> - `flag=2` 作为新设备首报可**独立创建 SOS 群**；同设备 `flag=0` 可将其 `status` 置 0
> - B账号设备C的 VOICE **成功路由到 A 创建的对讲群**，A/B 两侧同 id，且不出现在任一 SOS 群
> - 三设备恰好占满 `maxMembers=3`，成员集合硬校验通过
> - B 账号需先完成**实名认证**（首次探针因 `code=999 星联卫士设备绑定前必须先完成实名认证` 失败，实名后通过）——B 侧造棒前置条件
>
> 实施结果：
> - `conftest.py`：`intercom_message_group` 切换为三设备两波调度（跨设备 0 间隔 + 双设备冷却钟），新增 `rescue_sat_terminal_c2` fixture；seed 一次性切换为 `group/devices/messagesByRole/sosGroups/snapshots/accessSnapshots/timing` 多设备结构，不保留旧单设备字段
> - `testcases/test_intercom_message_controller.py`：Im00~Im05 全部迁移新契约；发送者按角色精确硬断言；双群一致性按设备分别匹配（water_sos SOS 侧允许 1 条心跳 TEXT 多出）；B 非成员越权证据以造数期快照 `accessSnapshots.bNonMember` 留痕，live 场景更名为「跨账号成员查询」；Im02 不再重复邀请 B棒4
> - `_CHAT_TIME_TOLERANCE_MS` 由 5000 收紧为 **100ms**：三设备时序下心跳记录与 VOICE 间隔可 <5s，5000ms 会误判 VOICE 泄漏（回归实测发现）
> - 两轮全量回归 **34/34 通过**，单轮总耗时约 **84~86s**（旧链约 4~5 分钟）；造数期扣费约 50 豆（20 建群 + 3×10 邀请，以现网配置为准）

# 风险深度分析

## P0：必须由最小探针证实，失败即停止正式改造

1. **62 秒限制作用域未知**
   - 已证实的只有“同一终端两次上行需 >60 秒”；原计划明确放弃了不同终端作用域探针：`jkpt_api_test/plan/intercom-message-tests.plan.md`。
   - 可能按 terminalId、JKPT账号、10304管理员会话、同一对讲群或服务全局限流。
   - HTTP `code=0` 也不能证明成功，必须同时验证目标消息和 SOS item 异步落库。

2. **设备B以 `flag=2` 作为首条业务上行能否独立建 SOS 群未知**
   - 当前实测只覆盖同一设备先 `flag=1` 再 `flag=2`。
   - 若 `flag=2` 只能追加到既有 SOS 态，则“两设备两SOS群”模型不成立。

3. **由首报 `flag=2` 创建的 SOS 群能否被同设备 `flag=0` 稳定结束未知**
   - 当前“心跳将 status 置 0”的证据来自经历过 `flag=1→flag=2` 的单设备群，不能直接外推。

4. **B账号设备C在A账号创建的群中发送 VOICE 的路由未知**
   - 现有代码只证实 B棒可 PENDING→AGREED 入群、B侧可查询和清未读；没有 B棒 speech 落 A 群的实打证据。
   - 必须验证 A侧和B侧看到同一个 message ID、sender 为设备C，且两个已结束的 SOS 群都没有该 VOICE。

5. **两台A设备已入群后，B设备恰好占第3个成员位的组合行为未独立验证**
   - `maxMembers=3` 已有实测；三设备正好满员、零余量。
   - 必须验证 B invitation 是否预占容量、handler 时是否二次校验，以及最终成员集合恰为三台目标设备。

## P0：测试覆盖回退风险，正式改造前必须显式处理

6. **B设备提前入群会破坏现有“B账号非成员越权查询”语义**
   - 当前 Im01 的 `cross_account` 在 B棒4入群前执行，因此能证明非成员越权读取。
   - 若设备C在 fixture 开始阶段已入群，该场景只能证明“跨账号成员查询”，不能继续标注为非成员越权。
   - 推荐在 B 同意入群前，由 fixture 采集一次 B账号对当前两条TEXT的非成员查询快照并保存到 `seed.accessSnapshots.bNonMember`；Im01 增加专门断言该快照。正式 live `cross_account` 场景改名为“跨账号成员查询”，避免伪造语义。

## P1：代码结构确定存在，正式实现必须修复

7. **当前落库闸门只看总数，三设备下会假绿**
   - `wait_landed(tag, want)` 仅判断 `count >= want`，无法区分危险SOS、落水SOS、VOICE由谁产生。
   - 新闸门必须基于“发送前 baseline IDs + sender SN + sendType + content/时间窗”匹配指定新消息。

8. **当前数据模型只支持一个设备和一个 SOS 群**
   - `seed["sn"]`、`sosChatItemId`、`sosRecords` 以及字段级“所有消息均由同一SN发送”的断言均与新模型冲突。
   - 按已确认决策一次性切换为 `devices / messagesByRole / sosGroups / snapshots / timing`，不保留含糊旧别名；遗漏引用应以 `KeyError` 显性暴露。

9. **现有 B棒4 helper 会重复邀请已入群设备**
   - `read_transition_setup` 当前负责邀请、查PENDING、B同意、成员复核、查询和 clear。
   - 设备C已在核心 fixture 入群后，Im02 只能复用其 B headers 和成员身份，必须删除重复 invitation/handler 分支。

10. **两个 SOS 群不能再取查询结果 `items[0]`**
    - 必须按各自 SN、活跃状态和本轮时间窗分别捕获，保存 chatItemId；双群一致性按设备逐一匹配。
    - 设备B `flag=0` 在 SOS 侧会额外产生心跳 TEXT，但对讲群零增长，因此不能做两个消息池总数一比一。

11. **VOICE 前仅固定 sleep 不足以保证单落**
    - 设备A `flag=10`、设备B `flag=0` 后必须分别轮询对应 SOS chatItem 到 `status=0`；两个闸门都通过才允许设备C发 speech。

12. **10304 收尾可能误伤共享环境会话**
    - `RescueUplinkClient` 已按 terminalId 维护 `_active_sessions`，但现有 `disconnect_all()` 据代码探索会遍历平台全部活跃模拟会话。
    - 实现前复核该函数；若属实，改为只断开本客户端登记的 terminalId/session，避免三设备方案扩大共享环境误伤面。

13. **失败非事务、只有尽力清理**
    - 设备入库、群创建后均即时登记 cleaner，这是正确基础；但邀请扣豆、PENDING通知、异步晚到消息无法事务回滚。
    - 任一步失败必须附设备时间线、10304请求结果、session records、message logs、成员列表、两个SOS查询和当前 message/page 快照；不得静默重试为慢链。

## P2：可维护性和稳定性风险

14. **群名仅到秒，重复/并发有碰撞可能**：保持15字符上限下增加短盐，且继续禁止 xdist。
15. **消息顺序不应依赖 `items[0]`**：`messagesByRole` 按语义匹配保存；extract 的 `im_message_id` 选择明确角色或最新有效消息。
16. **成本与闸门注释漂移**：建群20豆 + 3台邀请各10豆，最低直接成本约50豆（以最新现网配置为准）；保留 `<200` 安全闸门，但更新说明和分段余额记录。
17. **三设备正好满员**：成员复核必须比较目标 SN 集合，而非只看数量；任何额外设备或遗漏都立即失败。

# 推荐实施计划

## 阶段 1：建立最小探针，先证明硬前提

1. 在 `jkpt_api_test/conftest.py` 仅新增第二根消息域专用 A 棒 fixture，复用 `_provision_a_rescue_stick`，不复制 provision 代码；继续复用现有 `rescue_sat_terminal_c` 和 `rescue_sat_terminal_b4`。
2. 在约定临时目录创建一次性 pytest 探针，运行后删除，不把探针脚本留在源码：
   - 创建并立即注册临时对讲群；
   - 逐台邀请两个A设备；邀请B设备后完成 PENDING→AGREED；
   - 硬校验成员集合恰为三个目标 SN；
   - 记录单调时钟，设备A `flag=1` 请求完成后立即由设备B `flag=2`；
   - 联合轮询两个指定 sender/content 的新 TEXT 及各自独立 SOS item；
   - 等到两台设备各自距最后上行均超过 `IM_UPLINK_GAP`；
   - 设备B `flag=0`、设备A `flag=10` 快速顺序发送；
   - 轮询两个 SOS 群均为 `status=0`；
   - B设备C发送 speech，验证 A/B 两侧同一 VOICE、sender=C，且两个 SOS 群均无该 VOICE。
3. 探针报告必须输出各阶段耗时、两次快速上行间隔、请求业务码/sessionId、消息落库延迟、SOS群ID和状态轨迹、成员集合及余额变化。
4. 任一 P0 条件失败：停止，不修改正式 `intercom_message_group`；呈报实际限制和可选替代，不自动改成全局62秒慢速三设备链。

## 阶段 2：重构正式三设备 fixture

修改 `jkpt_api_test/conftest.py`：

1. 为三种角色建立明确局部映射：`key_sos`、`water_sos`、`voice`；A设备继续走 `_provision_a_rescue_stick`，B设备继续走 `_provision_b_rescue_stick`。
2. 抽取/复用跨账号邀请闭环 helper：A invitation → PENDING轮询 → B AGREED → terminal/list 集合复核；逐台邀请，避免未经验证的混合批量邀请部分成功语义。
3. 在 B AGREED 前采集 B账号非成员查询快照，保留现有越权证据；入群后再开始核心三设备消息链。
4. 用每设备 `last_uplink_at` 计算剩余冷却，不再每一步固定 sleep：
   - 第一波：A flag1、B flag2快速顺序发送；
   - 联合语义落库闸门；
   - 等待 `max(A剩余冷却, B剩余冷却)`；
   - 第二波：B flag0、A flag10快速顺序发送；
   - 双 SOS status=0闸门；
   - C speech；VOICE语义落库闸门。
5. 新增可复用的内部查询/闸门逻辑：
   - 按 SN 捕获本轮 SOS item；
   - 按 baseline ID、sender、sendType、content和时间窗匹配消息；
   - 轮询指定 SOS 状态；
   - 失败统一调用增强版 `_fail()` 输出三设备和双SOS证据。
6. 返回全新 seed，不保留 `sn/sosChatItemId/sosRecords`：
   - `group`：id/name/members；
   - `devices`：角色、SN、账号、动作；
   - `messagesByRole`：三条目标消息；
   - `sosGroups`：两个群及状态/records；
   - `snapshots`：baseline、双SOS后、心跳/取消后、VOICE后；
   - `accessSnapshots`：B非成员与B成员查询证据；
   - `timing`：各阶段和总耗时。
7. 保留目标 `totalSeconds <= 90` 为报告指标；超过时告警并展示瓶颈阶段，不因环境抖动单独判业务失败。

## 阶段 3：同步改造消息域用例

修改 `jkpt_api_test/testcases/test_intercom_message_controller.py`：

1. **Im00 fixture自检**：校验三个设备均在成员集合、三角色消息存在且 sender/type/content 精确匹配、两个SOS群均捕获并结束、最终对讲群状态活跃；继续写 `im_group_id`，`im_message_id` 明确选择 `messagesByRole.voice.id` 或约定角色。
2. **Im01 positive/field_shape**：移除“所有 sender 等于单一SN”，改为危险TEXT→A、落水TEXT→B、VOICE→C的精确映射。
3. **Im01 dual_group_consistency**：按角色分别匹配 SOS-A/SOS-B；允许 SOS-B 多出心跳TEXT；VOICE必须不出现在两个SOS记录池。
4. **Im01 zero_growth**：改读 `snapshots`，仍断言 flag0/flag10 对讲群零增长、VOICE增加1；不依赖旧 `totals` 平铺结构。
5. **Im01 cross_account**：
   - 新增/改造非成员快照断言，明确证明 B 在入群前可读；
   - live B 查询改名为跨账号成员查询，不继续冒充非成员越权。
6. **Im02 read_transition_setup**：删除再次创建/邀请 B棒4；直接使用 seed 中设备C和 `auth_headers_b`，执行成员侧查询及 `clear/unread` 留痕。
7. **Im03～Im05**：将 `groupId/groupName/messageIds/totals` 读取迁移到新结构；清未读、close/delete主逻辑保持不变；delete成功仍注销 intercom cleaner。
8. 全文件搜索并消除旧字段引用，避免留下兼容别名掩盖漏改。

## 阶段 4：收紧会话和清理安全

1. 复核并视结果修改 `jkpt_api_test/common/rescue_platform_client.py::disconnect_all`，只断开本客户端创建/记录的终端会话，不清理共享平台其他任务会话。
2. 继续沿用副作用落地即注册：两个A设备、一个B设备、GLHT记录、两个可能活跃的SOS群、对讲群均由现有 tier cleaner接管。
3. 验证 B邀请在 handler失败/群删除后的 PENDING 通知行为；若通知残留且无现成删除接口，将其记录为明确已知泄漏，不臆造清理能力。
4. 更新余额日志和 cleanup report，使每个设备、SOS群、对讲群都可归因。

## 阶段 5：更新测试数据和设计记录

1. 检查 `jkpt_api_test/yaml/test_intercom_message_controller.yaml` 中场景名称、描述和 expected 是否仍声称“B非成员”或“单设备”；仅修改受语义变化影响的条目。
2. 更新 `jkpt_api_test/plan/intercom-message-tests.plan.md`：记录新探针结果、62秒真实作用域、三设备拓扑、双SOS群模型、B speech路由、成本和性能实测；所有具体数值标注以最新现网需求/配置为准。
3. 保持文件内执行序和禁 xdist 约束，因为 Im03～Im05 仍有清未读、close/delete写侧状态消费。

# 验证方案

## 探针闸门

- 只运行一次性探针，确认五个 P0 前提；探针结束检查 cleanup report，无临时脚本残留。
- 若失败，输出证据并停止正式改造。

## 正式回归

1. 在 `jkpt_api_test` 目录串行运行完整文件，禁止 xdist：
   - `pytest testcases/test_intercom_message_controller.py -s -q`
2. 至少连续运行两轮，验证：
   - 每轮创建全新群和三台设备；
   - 三条消息 sender/type/content 映射稳定；
   - 两个 SOS 群分别创建并结束；
   - B非成员快照和B成员 live 查询语义均真实；
   - 清未读、关群、删群仍按既有顺序通过；
   - 第二轮无上一轮 message ID、成员、PENDING通知或活跃会话污染。
3. 检查关键守恒：
   - 对讲群最终新增恰为2 TEXT + 1 VOICE；
   - flag0/flag10 对讲群零增长；
   - SOS-B允许额外心跳TEXT；
   - VOICE只落对讲群；
   - 成员集合始终恰为三台目标设备；
   - 清理报告覆盖对讲群、A/B设备、GLHT记录和活跃SOS。
4. 性能报告：总耗时目标≤90秒，同时给出 invitation、双SOS落库、冷却、双状态归零、VOICE落库分段耗时；超时只告警，业务闸门仍按真实结果判断。
5. 静态核对：搜索旧 `seed["sn"]`、`sosChatItemId`、`sosRecords` 和重复 `rescue_sat_terminal_b4` invitation 引用，确保一次性契约切换完整。

# 关键文件

- `jkpt_api_test/conftest.py`：设备 provisioning、跨账号入群、三设备调度、双SOS和新 seed。
- `jkpt_api_test/testcases/test_intercom_message_controller.py`：所有下游断言、B非成员/成员语义、读写状态链。
- `jkpt_api_test/common/rescue_platform_client.py`：多终端会话收尾安全。
- `jkpt_api_test/yaml/test_intercom_message_controller.yaml`：受语义变化影响的场景描述/期望。
- `jkpt_api_test/plan/intercom-message-tests.plan.md`：探针事实与最终架构记录。
