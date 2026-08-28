# API 自动化覆盖缺口盘点（P0/P1/P2）

> 生成时间：2026-08-14
> 进度更新时间：2026-08-28
> 数据来源：Apifox 项目「Swagger3接口文档」OAS 拉取结果（x-download-time: 2026-08-14T06:33:06Z）
> 比对基准：`jkpt_api_test/testcases/*.py` 中实际请求的接口路径（YAML 数据驱动的执行层）
> 数值口径：沿用原计划人工修正口径；严格按路径变量归一去重时，当前已实现为 77 个 URL。
> 本次范围调整：排除小程序相关的 `app-users`、`ao-wei`、`share`、`follow-platforms`、`subscription`、微信小程序支付、微信服务通知，共 52 个 URL；其他无法仅凭路径确认归属的接口暂保留。

---

## 一、盘点口径说明（先读，避免误读数字）

1. **粒度**：按 URL 计（一个 URL 记 1，不论其下有几个 HTTP method）；OAS 全集 398 个 URL / 426 个操作，本计划当前纳入 346 个 URL。
2. **范围排除**：`app-users` 25 个、`ao-wei` 8 个、`share` 7 个、`follow-platforms` 5 个、`subscription` 4 个、`order/payment/wx/applet` 1 个、`wx-service-notification` 2 个，共 52 个小程序接口不再纳入自动化补测计划。
3. **归一化规则**：路径变量名归一（`{tid}`/`{eid}`/`{alarm_id}` → `{}`）后与 OAS 匹配，消除"同接口不同变量名"的误判。
4. **人工修正**：`/api/monitor/alarms/{addr}`（查历史报警）与 `/api/monitor/alarms/{id}`（处理报警）**均已实现**，机器口径仅匹配其一，本文档沿用人工修正口径统计为 78；严格归一去重为 77。
5. **已知歧义（不计入已实现，也不建议当独立缺口补测）**：
   - `/api/monitor/captcha`：在 `conftest.py` 登录链路中被调用，但无独立断言用例（属前置工具）。
   - `/api/datas/bd`、`/api/monitor/mock-in-storage` 等：作为协议造数工具被调用，非被测对象。
6. **P2 中的 mock/h5-mock/datas/mock-\* 系列**：多为造数/模拟接口，本身不是业务被测对象，是否补测由测试目标决定。

---

## 二、总览

| 维度 | 数量 | 占计划范围 |
|------|------|------------|
| OAS 接口全集（URL） | 398 | — |
| 已排除小程序接口 | 52 | — |
| 当前计划范围 | **346** | **100%** |
| ✅ 已实现自动化 | **78** | **22.5%** |
| ❌ 未实现自动化 | **268** | **77.5%** |
| └─ 🔴 P0 高风险写操作 | 68 | 19.7% |
| └─ 🟡 P1 消息/通知/触达 | 44 | 12.7% |
| └─ 🟢 P2 枚举/地图/造数/低ROI | 156 | 45.1% |

**进度变化**：已实现从 35 增至 78，新增 43 个接口；严格按路径变量归一去重为 77 个。新增覆盖集中在 emergency 17 个、order 4 个、star-bean 4 个、intercom 18 个。

**判级依据**：
- **P0** = 资金扣费 / 绑定关系变更 / 设备写指令 / 账号安全与越权 / 救命功能（应急求救）。出了事最赔不起。
- **P1** = 消息触达类：漏发、重发、未读数不一致属业务事故但非资金损失。
- **P2** = 纯枚举、静态资源、大屏聚合、造数桩、测试桩。自动化 ROI 低或有批量参数化的快胜路径。

---

## 三、✅ 已实现自动化的接口（78 个，13 个模块）

| 模块 | 数量 | 测试文件 | 覆盖接口 |
|------|------|----------|----------|
| alarms 报警 | 7 | test_alarm_controller.py | `/alarms`、`/alarms/{addr}`、`/alarms/latest/{addr}`、`/alarms/{id}`(PUT处理)、`batch-handle`、`batch-handle/ids`、`batch-info` |
| terminals/batch 终端批量 | 8 | test_batch_terminal_controller.py | `/batch`、`aggr-point-details`、`details`、`export`、`import`、`lnglat-details`、`move-group`、`remark` |
| groups 分组+组设备 | 6 | test_group_controller.py + test_terminal_controller.py | `/groups`、`/groups/{id}`、`{groupId}/terminals`、`{groupId}/terminals/batch`、`{addr}/follow`、`{addr}/move` |
| enclosures 围栏 | 5 | test_enclosure_controller.py | `/enclosures`、`{id}`、`codes/{shareCode}`、`{id}/export`、`{id}/terminals` |
| locations 定位 | 3 | test_location_controller.py | `/locations`、`/export`、`/track` |
| field-templates 字段模板 | 3 | test_field_template_controller.py | `/field-templates`、`{id}`、`{id}/fields` |
| alarm-settings 报警设置 | 2 | test_alarm_settings_controller.py | `/alarm-settings`、`{id}` |
| web-user 登录 | 1 | test_login.py | `/web-user/login`（正向在 conftest，负向有用例） |
| emergency/chat 求救群聊 | 12 | test_emergency_chat_controller.py | 除 `/item/complete/addr` 外，其余 12 个计划接口已覆盖 |
| emergency/combo 求救套餐 | 5 | test_emergency_combo_controller.py | `/mall`、`/chat/item/info`、`/chat/item/remaining`、`/usage/page`、`/buy` |
| order 订单 | 4 | test_emergency_order_controller.py | `/page`、`/detail`、`/cancel`、`/delete` |
| star-bean 星豆 | 4 | test_star_bean_controller.py | `/calculate`、`/package/active`、`/buy`、`/transaction/page` |
| intercom 对讲 | 18 | test_intercom_group_controller.py + test_intercom_message_controller.py | 除 `/group/closed/delivery/cancel` 外，其余 18 个计划接口已覆盖 |

> 进度状态：emergency/combo、star-bean 已全量完成；emergency/chat 为 12/13；order 在当前计划范围内为 4/5；intercom 为 18/19。
>
> 质量提醒：覆盖统计代表已有独立自动化用例，不等同于所有副作用、扣费守恒、消息送达均已验证到位。

---

## 四、🔴 P0 进度与剩余清单（目标 93 个，已完成 25 个，剩余 68 个）

> 原 P0 143 个；移除 `app-users` 25 个、`ao-wei`/`share`/`follow-platforms`/`subscription` 24 个、微信小程序支付 1 个后，计划目标为 93 个。
> 🔴🔴 标记 = P0 中的最高危（扣钱 / 改归属 / 砖机 / 账号安全）。

### 4.1 emergency 应急/求救（17/18 已完成，剩余 1 个）

- ✅ emergency/chat 已完成 12/13：发送、成员管理、消息分页、已读、清未读、结束会话、状态查询、记录查询均已覆盖。
- ✅ emergency/combo 已完成 5/5：套餐商城、条数信息、剩余量、用量分页、购买链路均已覆盖。
- ⏳ 唯一剩余：

| 接口 | 风险点 |
|------|--------|
| `/api/monitor/emergency/chat/item/complete/addr` | 按设备结束会话；验证状态机与重复结束幂等 |

### 4.2 pn07 设备指令（21 个）— 设备写操作

| 接口 | 风险点 |
|------|--------|
| 🔴🔴 `/api/monitor/pn07/codes/upgrade` | 固件升级：**失败砖机** |
| 🔴🔴 `/api/monitor/pn07/codes/restart` | 远程重启 |
| 🔴🔴 `/api/monitor/pn07/codes/shutdown` | 远程关机 |
| `/api/monitor/pn07/codes/text` | 下发文本指令 |
| `/api/monitor/pn07/codes/work-mode` | 工作模式 |
| `/api/monitor/pn07/codes/report-freq` | 上报频率 |
| `/api/monitor/pn07/codes/angle` | 角度 |
| `/api/monitor/pn07/codes/call-location` | 回拨定位 |
| `/api/monitor/pn07/codes/ip-domain` | IP/域名设置 |
| `/api/monitor/pn07/codes/device-id` | 设备ID设置 |
| `/api/monitor/pn07/codes/initialization` | 初始化 |
| `/api/monitor/pn07/codes/upgrade-setting` | 升级设置 |
| `/api/monitor/pn07/codes` | 指令列表 |
| `/api/monitor/pn07/codes/batch` | 批量指令：**幂等+部分失败** |
| `/api/monitor/pn07/codes/batch/{batchId}` | 批次删除 |
| `/api/monitor/pn07/codes/{id}` | 单条指令删/改 |
| `/api/monitor/pn07/codes/query/info` | 指令回执查询（验"指令真到了"） |
| `/api/monitor/pn07/codes/query/version` | 版本查询 |
| `/api/monitor/pn07/active` | 激活 |
| `/api/monitor/pn07/active/info/{addr}` | 激活信息 |
| `/api/monitor/pn07/active/upload` | 激活上传 |

### 4.3 pn06 设备指令（12 个）

| 接口 | 风险点 |
|------|--------|
| 🔴🔴 `/api/monitor/pn06/codes/upgrade` | 固件升级：砖机风险 |
| `/api/monitor/pn06/codes/text` | 文本指令 |
| `/api/monitor/pn06/codes/motion-mode` | 运动模式 |
| `/api/monitor/pn06/codes/timing-mode` | 定时模式 |
| `/api/monitor/pn06/codes/ip-port` | IP/端口 |
| `/api/monitor/pn06/codes/domain-port` | 域名/端口 |
| `/api/monitor/pn06/codes/feedback/{businessId}` | 指令反馈 |
| `/api/monitor/pn06/codes` | 指令列表 |
| `/api/monitor/pn06/codes/batch` | 批量指令 |
| `/api/monitor/pn06/codes/batch/{batchId}` | 批次删除 |
| `/api/monitor/pn06/codes/{id}` | 单条删/改 |
| `/api/datas/pn06` | pn06 数据上报 |

### 4.4 order 订单（4/5 已完成，剩余 1 个）— 纯资金流

- ✅ 已完成：`/page`、`/detail`、`/cancel`、`/delete`。
- ⏳ 剩余：

| 接口 | 风险点 |
|------|--------|
| 🔴🔴 `/api/monitor/order/payment` | 发起支付：**重复支付、金额篡改** |

### 4.5 star-bean 星豆虚拟资产（4/4 已完成）

✅ `/buy`、`/calculate`、`/transaction/page`、`/package/active` 已全部覆盖。后续重点从“补接口”转为扣费守恒、流水对账、重复购买幂等验证。

### 4.6 ver-codes 验证码（7 个）— 账号安全

| 接口 | 风险点 |
|------|--------|
| 🔴🔴 `/api/monitor/ver-codes/login` | 登录验证码：**爆破** |
| 🔴🔴 `/api/monitor/ver-codes/register` | 注册验证码：**短信轰炸** |
| 🔴🔴 `/api/monitor/ver-codes/retrieve` | 找回密码验证码：**改密越权** |
| 🔴🔴 `/api/monitor/ver-codes/update/pwd` | 改密验证码 |
| `/api/monitor/ver-codes/bind/email` | 绑邮箱验证码 |
| `/api/monitor/ver-codes/bind/phone` | 绑手机验证码 |
| `/api/monitor/ver-codes/set/emergency-contact` | 设紧急联系人验证码 |

### 4.7 web-users 平台用户（13 个）

| 接口 | 风险点 |
|------|--------|
| 🔴🔴 `/api/monitor/web-users/pwd` | 修改密码 |
| 🔴🔴 `/api/monitor/web-users/reset-pwd` | 重置密码 |
| 🔴🔴 `/api/monitor/web-users/code/pwd` | 验证码改密 |
| 🔴🔴 `/api/monitor/web-users/authentication` | 实名认证 |
| `/api/monitor/web-users/phone` | 改手机号 |
| `/api/monitor/web-users/email` | 改邮箱 |
| `/api/monitor/web-users/name` | 改名称 |
| `/api/monitor/web-users/avatar` | 改头像 |
| `/api/monitor/web-users/platform-logo` | 平台logo |
| `/api/monitor/web-users/platform-name` | 平台名称 |
| `/api/monitor/web-users/info` | 用户信息 |
| `/api/monitor/web-users/records` | 操作记录 |
| `/api/monitor/web-users/pre-bind-validation` | 预绑定校验 |

### 4.8 web-sub-users 子账号（6 个）

| 接口 | 风险点 |
|------|--------|
| 🔴🔴 `/api/monitor/web-sub-users` | 子账号增删查（GET/POST） |
| 🔴🔴 `/api/monitor/web-sub-users/{account}` | 子账号改/删 |
| 🔴🔴 `/api/monitor/web-sub-users/{account}/bind` | 子账号绑定 |
| `/api/monitor/web-sub-users/{account}/reset` | 子账号重置 |
| `/api/monitor/web-sub-users/{account}/terminals` | 子账号终端 |
| `/api/monitor/web-sub-users/{account}/v2/terminals` | 子账号终端v2 |

### 4.9 mock-terminal 造数终端（4 个）

| 接口 | 风险点 |
|------|--------|
| `/api/monitor/mock-terminal` | 造数终端增删查：**数据污染源头**，补"用完即删"清理用例 |
| `/api/monitor/mock-terminal/{id}` | 改/删 |
| `/api/monitor/mock-terminal/init-loc` | 初始化位置 |
| `/api/monitor/mock-terminal/{id}/addrs` | 追加地址 |

### 4.10 offline-alarm-settings 离线报警设置（2 个）

| 接口 | 风险点 |
|------|--------|
| `/api/monitor/offline-alarm-settings` | 设置列表 |
| `/api/monitor/offline-alarm-settings/{id}` | 编辑设置：可配项测改前/改后/边界 |

### 4.11 msg-noti-records 通知记录（1 个）

| 接口 | 风险点 |
|------|--------|
| `/api/monitor/msg-noti-records/{type}` | 通知记录查询 |

---

## 五、🟡 P1 进度与剩余清单（目标 62 个，已完成 18 个，剩余 44 个）

### 5.1 intercom 对讲（18/19 已完成，剩余 1 个）

- ✅ 群创建、更新、删除、关闭、邀请、移除设备、费用、余量、终端列表、成员昵称，以及邀请消息和普通消息接口均已覆盖。
- ⏳ 唯一剩余：`/api/monitor/intercom/group/closed/delivery/cancel`（关闭投递取消）。

### 5.2 platform-chats 平台聊天（15 个）

```
/api/monitor/platform-chats/chat-list         会话列表
/api/monitor/platform-chats/chat-item         会话项删除
/api/monitor/platform-chats/chat-item/page    会话项分页
/api/monitor/platform-chats/query             查询
/api/monitor/platform-chats/records           记录删除
/api/monitor/platform-chats/unread            未读
/api/monitor/platform-chats/clear/all-unread  清全部未读
/api/monitor/platform-chats/clear/{addr}/unread   清单端未读
/api/monitor/platform-chats/{addr}            单会话详情
/api/monitor/platform-chats/{addr}/text       发文本（触达）
/api/monitor/platform-chats/{addr}/voice      发语音（触达）
/api/monitor/platform-chats/{addr}/follow/{follow}      关注开关
/api/monitor/platform-chats/{addr}/msg-remind/{notDisturb} 免打扰开关
/api/monitor/platform-chats/{id}/album        相册
/api/monitor/platform-chats/{id}/enhance/voice 语音增强
```

### 5.3 msg-notification 通知开关（11 个）— 可 1 个参数化用例批量覆盖

```
/api/monitor/msg-notification/msg-noti-setting          总设置
/api/monitor/msg-notification/bd-new-msg-noti-type      北斗新消息
/api/monitor/msg-notification/bd2-new-msg-noti-type     北斗2
/api/monitor/msg-notification/bd3-new-msg-noti-type     北斗3
/api/monitor/msg-notification/lora-new-msg-noti-type   LoRa
/api/monitor/msg-notification/tian-tong-new-msg-noti-type 天通
/api/monitor/msg-notification/yx-new-msg-noti-type     易信
/api/monitor/msg-notification/other-new-msg-noti-type  其他新消息
/api/monitor/msg-notification/other-alarm-noti-type    其他报警
/api/monitor/msg-notification/alarm-statistics-noti-setting 报警统计
（可配项：读→改→边界→非法值，一套模板跑全部）
```

### 5.4 beacons 信标（3 个）

```
/api/monitor/beacons  /api/monitor/beacons/all  /api/monitor/beacons/total
```

### 5.5 ok-msgs 报平安（4 个）

```
/api/monitor/ok-msgs            列表
/api/monitor/ok-msgs/mark       标记已读（幂等）
/api/monitor/ok-msgs/mark/all   全部已读（幂等）
/api/monitor/ok-msgs/unread-num 未读数一致性
```

### 5.6 h5-sms（3 个）

```
/api/monitor/h5-sms/info  /api/monitor/h5-sms/text  /api/monitor/h5-sms/chat-records
```

### 5.7 platform-mock-chats 造数（4 个，可降 P2）

```
/api/monitor/platform-mock-chats/platform/to/{addr}/text
/api/monitor/platform-mock-chats/{addr}/to/platform/text
/api/monitor/platform-mock-chats/{addr}/to/platform/image
/api/monitor/platform-mock-chats/{addr}/to/platform/voice
```

### 5.8 unread 未读（2 个）

```
/api/monitor/unread  /api/monitor/unread/chat
```

### 5.9 phrases 常用语（1 个）

```
/api/monitor/phrases/list
```

---

## 六、🟢 P2 未实现汇总（156 个，模块级）

| 类别 | 模块（数量） | 处理建议 |
|------|--------------|----------|
| 纯枚举字典 | enums(19) | **1 个参数化用例全包** |
| 造数/模拟 | h5-mock(13)、mock(5)、mock-device-chats(6)、mock-loc1~6(6)、mock-ok1/2(2)、datas 上报系列 bd/dc-http-push/fy/jili/pd15/pl/public-net/rtk/sms/tt/yixing(11)、platform-mock-chats 已在P1、mock-qr(1) | 造数工具为主，按需 |
| 地图/坐标 | h5-map(4)、map(6)、map-setting(1)、aggregation(2) | 静态资源，ROI 极低 |
| 大屏统计 | large-data-screen(8) | 只读聚合，冒烟即可 |
| 直播 | live-broadcast(7) | 业务边缘 |
| 第三方对接回调 | receive-event(6)、api/open(6)、ntn check/datas(2)、tianyi(1)、qianxun(1)、fzwlw(1)、terminal-status(1) | 需 mock 上游再测 |
| 群组查询类 | groups(8)：`chat`、`chat/members`、`select`、`{groupId}/terminals/from/list`、`yy/list`、`{addr}/comm-records`、`{id}/expand`、`{id}/select` | 介于 P1/P2，读接口，随 groups 二期补 |
| 登录页配置 | web-user(4)：`login-flag`、`login-page-info`、`rotate-image`×2 | 低 |
| 文件 | files(3)：`{fileId}`、`mp3`、`video` | 低 |
| 缓存 | cache(3) | 运维向 |
| 基站 | stations(4) | 随设备二期 |
| 救援队 | rescue(2) | 只读 |
| 测试桩 | test(6)、test-ali-text-check(1)、delayQueue、transaction、pool、ws/print、version、captcha、diag、config、suggestions、templates、terminal、retrieve、app/unread、sms(1)、bd(1) 等 | 生产无关/工具 |

> P2 明细合计 156（机器口径 157，含已被人工修正为"已实现"的 `alarms/{addr}` 1 条）。

---

## 七、后续补测建议（按当前进度）

1. **先收尾现有模块**：补 `/emergency/chat/item/complete/addr`、`/order/payment`、`/intercom/group/closed/delivery/cancel`，关闭 3 个已接近完成模块的缺口。
2. **账号安全**：优先 ver-codes 爆破/短信轰炸、web-sub-users 越权、web-users 改密/重置/实名认证。
3. **设备高危指令**：pn07/pn06 的 upgrade/restart/shutdown、批量指令、回执查询；验证幂等、部分失败、真实回执。
4. **快胜**：msg-notification 开关参数化 + enums 参数化，低成本提升覆盖。
5. **已完成模块深化**：emergency/combo、star-bean、order 已有接口覆盖，下一步补扣费守恒、流水对账、重复请求幂等和副作用验证。
6. **范围约束**：不再补测本计划已排除的小程序接口；后续发现归属不明接口时先确认业务端再纳入。
7. **每条用例要求**：自带数据构造与清理；写操作验证“只发生一次副作用”；断言分层到落库、消息、扣费或设备回执。

---

## 附：比对方法存档

- OAS 来源：Apifox MCP `read_project_oas`（实时刷新）
- 已实现提取：`testcases/*.py` 中 `url = f"{base_url}/..."` 及裸路径正则
- 匹配规则：路径变量名归一化 `{xxx}` → `{}`
- 已知局限：同段位不同变量名（`{addr}` vs `{id}`）需人工核对；带 query 的 URL（captcha）不参与匹配
