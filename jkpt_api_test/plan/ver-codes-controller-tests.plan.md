# ver-codes 验证码接口自动化用例实施计划

> 制定时间：2026-08-28
> 接口来源：Apifox 项目「Swagger3接口文档」最新 OAS
> 目标模块：验证码管理接口
> 框架依据：仓库根目录 `skills/api-test-framework/SKILL.md`
> 关联缺口：`plan/api-automation-coverage-gap.plan.md` 4.6
>
> 已确认范围：仅测试验证码发送接口，不调用或校验下游登录、改密、绑定接口；当前无法自动获取验证码；已具备专用测试手机号和邮箱；允许在显式开关下执行低次数限频测试。
>
> 执行状态（2026-08-28）：已完成 7 个接口的测试骨架、YAML 场景、无副作用基线校准、PII 脱敏和静态/回归验证；真实发送成功文案、账号归属越权和限频阈值仍需在显式环境开关与专用接收端就绪后校准。

---

## 一、目标与边界

### 1.1 实施目标

为 7 个验证码发送接口建立 pytest + YAML 数据驱动自动化，覆盖：

1. 每个 URL 的基础契约与成功受理路径。
2. `Authorization`、`mode`、`to` 三个查询参数的必填和格式校验。
3. 手机、邮箱通知方式与接收对象格式匹配。
4. 登录、注册、找回密码、修改密码、绑定邮箱、绑定手机、设置紧急联系人等业务上下文差异。
5. 未授权、伪造授权、越权发送、验证码泄露、重复发送和限频等账号安全风险。
6. 真实短信/邮件副作用的安全隔离、脱敏、串行执行和可控开关。
7. 仅验证发送接口响应、参数契约、账号安全和限频行为，不建立下游消费链路。

### 1.2 本轮不做

1. 不调用或校验下游登录、注册、找回密码、修改密码、绑定邮箱、绑定手机、设置紧急联系人接口。
2. 当前无法自动取得真实验证码，不把验证码获取作为本轮实施依赖。
3. 不读取、破解、人工录入或消费真实验证码完成业务闭环。
4. 不对生产手机号、生产邮箱或个人账号发送验证码。
5. 不在默认回归套件执行高频轰炸、并发压测或大规模限流测试。
6. 除主人明确授权写入本测试 YAML 的两个专用接收端外，不硬编码其他真实手机号、邮箱、Token、密码；Authorization 仍由运行时生成或注入。
7. 不假设 OAS 未声明的业务码、错误文案、频控窗口和验证码有效期。
8. 不使用已删除的 `api_test_framework.runner`、`run_case` 或模式 C。

---

## 二、Apifox OAS 分析

### 2.1 接口清单

| 序号 | Method | Path | operationId | OAS 摘要 |
|------|--------|------|-------------|----------|
| 01 | POST | `/api/monitor/ver-codes/login` | `loginCodeUsingPOST` | 发送 APP 登录验证码 |
| 02 | POST | `/api/monitor/ver-codes/register` | `registerCodeUsingPOST` | 发送注册验证码 |
| 03 | POST | `/api/monitor/ver-codes/retrieve` | `retrievePwdCodeUsingPOST` | 发送找回密码验证码 |
| 04 | POST | `/api/monitor/ver-codes/update/pwd` | `updatePwdCodeUsingPOST` | 发送修改密码验证码 |
| 05 | POST | `/api/monitor/ver-codes/bind/email` | `bindEmailCodeUsingPOST` | 发送绑定邮箱验证码 |
| 06 | POST | `/api/monitor/ver-codes/bind/phone` | `bindPhoneCodeUsingPOST` | 发送绑定手机验证码 |
| 07 | POST | `/api/monitor/ver-codes/set/emergency-contact` | `setEmgContactCodeUsingPOST` | 发送设置紧急联系人验证码 |

### 2.2 七个接口的共同契约

全部接口均为 `POST`，参数位于 query：

| 参数 | 位置 | 必填 | OAS 描述 | 自动化处理 |
|------|------|------|----------|------------|
| `Authorization` | query | 是 | 授权码；部分接口只要求非空 | 必须放入 `params`；不能只传 Header |
| `mode` | query | 是 | `SHORT_MSG` 或 `EMAIL` | 覆盖合法值、空值、缺失、大小写和非法枚举 |
| `to` | query | 是 | 手机号或邮箱 | 从环境变量注入；日志与报告中脱敏 |

响应：

- HTTP 文档响应包含 `200/201/401/403/404`。
- HTTP 200 响应模型为 `CommonResult<string>`。
- OAS 未声明业务 `code/msg` 枚举。
- OAS 未声明验证码是否返回在 `data`、限频策略、接收对象存在性校验、Token 校验强度。
- OAS `security: []`，但接口又要求 query `Authorization`。这是契约歧义，必须通过基线探测确认。

### 2.3 OAS 风险提示

1. `Authorization` 是 query 参数。若只复用 `auth_headers` 作为 Header，可能得到误导性结果。
2. `bind/email` 示例包含敏感外观 Token 和邮箱。实施时禁止复制 OAS 示例值。
3. `mode` 只写在描述中，schema 未声明 enum。服务端可能未严格校验，需专门验证。
4. 返回模型是 `CommonResult<string>`。成功响应若直接返回明文验证码，属于高风险信息泄露，应形成缺陷。
5. 文档没有频控契约。自动化不能预设“第 N 次必限流”，应先校准再固化。

---

## 三、框架落地方案

### 3.1 文件结构

新增：

- `testcases/test_ver_code_controller.py`
- `yaml/test_ver_code_controller.yaml`

不新增独立 runner，不改 `conftest.py` 写入 `extract.yaml`。

若实施公共 PII 脱敏能力，再修改：

- `common/requests_util.py`
- `common/logger_util.py`
- `skills/api-test-framework/references/methods-reference.md`
- `skills/api-test-framework/CHANGELOG.md`

### 3.2 用例模式

采用 **模式 A：无状态接口**。

原因：

- 7 个接口请求之间不存在 CRUD/extract 依赖。
- 每个接口独立发送验证码。
- 无需使用 `extract.yaml`。

虽然使用模式 A，该文件仍必须串行执行：验证码发送存在外部副作用、账号限频和接收对象限频，不允许按 class 开 pytest-xdist。

### 3.3 一接口一 Test 类

| 顺序 | Test 类 | YAML 顶层 key |
|------|---------|---------------|
| 01 | `TestVc01LoginCode` | `login_code_cases` |
| 02 | `TestVc02RegisterCode` | `register_code_cases` |
| 03 | `TestVc03RetrievePasswordCode` | `retrieve_password_code_cases` |
| 04 | `TestVc04UpdatePasswordCode` | `update_password_code_cases` |
| 05 | `TestVc05BindEmailCode` | `bind_email_code_cases` |
| 06 | `TestVc06BindPhoneCode` | `bind_phone_code_cases` |
| 07 | `TestVc07SetEmergencyContactCode` | `set_emergency_contact_code_cases` |

每个类：

- 一个测试方法。
- 一次 `@pytest.mark.parametrize("case", ...)`。
- 不传 `ids=`。
- 不使用 `@allure.title(case["name"])`。

共享逻辑放 `_VerCodeHelpers`，不以 `Test` 开头。

### 3.4 必须使用的框架能力

Python 用例只引用：

- `from common.requests_util import BaseRequest`
- `from common.allure_assert_util import assert_api_result`
- `from common.yaml_util import read_yaml, read_expected_msg`
- `from common.logger_util import sep, key, print_response`

建议使用 `_jsonpath_parse = jsonpath.jsonpath` 解析 `$.code`、`$.msg`、`$.data`。

HTTP 请求：

- `BaseRequest.send_request(method="post", ...)`
- 三个接口参数全部传入 `params`。
- 日常 `log_level="none"` 或脱敏后的 `simple`。
- `case_name=case["name"]`。

统一断言：

- 正向 YAML 使用 `expected.msg`。
- 负向 YAML 使用 `expected.error_msg`。
- 通过 `read_expected_msg` 交给 `assert_api_result`。

---

## 四、测试数据与安全控制

### 4.1 环境变量

专用测试手机号和邮箱已具备。按主人明确授权，本计划正向用例将两个专用接收端直接写入 `yaml/test_ver_code_controller.yaml`；Authorization、Token 和其他敏感数据仍不写入仓库。环境变量保留为后续替代注入方式：

| 环境变量 | 用途 | 缺失行为 |
|----------|------|----------|
| `JKPT_VER_CODE_TEST_PHONE` | 专用测试手机号 | 需真实发送的 SHORT_MSG 用例 `pytest.skip` |
| `JKPT_VER_CODE_TEST_EMAIL` | 专用测试邮箱 | 需真实发送的 EMAIL 用例 `pytest.skip` |
| `JKPT_ENABLE_VER_CODE_DELIVERY` | 是否允许产生真实发送副作用 | 默认 `false` |
| `JKPT_ENABLE_VER_CODE_ABUSE_TEST` | 是否允许限频/重复发送安全测试 | 默认 `false` |
| `JKPT_VER_CODE_COOLDOWN_SECONDS` | 接口间冷却时间 | 基线探测后确定；未配置时采用保守值 |

要求：

- YAML 中固定的手机号、邮箱必须是主人确认的专用测试接收端。
- 禁止再新增未经授权的员工个人联系方式。
- CI 默认关闭真实发送和滥用测试。
- 专项环境手工开启后才能执行正向发送和频控用例。
- 任何使用“格式合法真实接收对象”的用例，即使预期因无授权或伪造授权而失败，也必须受发送开关控制；否则服务端认证缺陷可能意外触发真实短信/邮件。

### 4.2 Authorization 处理

构建 query 参数时区分三类：

1. **合法授权**：从 `auth_headers.get("Authorization")` 取 Token，放入 query `Authorization`。
2. **非空占位授权**：只在基线确认接口确实允许随机非空值后使用；值由运行时生成，不写死。
3. **无授权/非法授权**：省略、空串、随机伪造、仅 Header 不传 query。

`no_auth` 场景必须同时：

- 从 query 中移除 `Authorization`。
- 从 Header 中移除 `Authorization`。

这样才能避免服务端从另一通道读取 Token，导致无授权用例失真。

### 4.3 接收对象脱敏

实现 `_mask_recipient`：

- 手机号只显示前 3 位和后 2 位。
- 邮箱保留首字符和域名，其余掩码。
- `biz_context`、`key()`、手工日志不得出现完整接收对象。

同时检查 `BaseRequest` 最近请求上下文和 Allure 失败附件是否会保存原始 `to`。若会保存，先实现通用手机号/邮箱值级脱敏，再写验证码用例。

通用脱敏若进入 `common/`：

- 必须补单元/最小验证。
- 必须更新 `methods-reference.md` 和 `CHANGELOG.md`。

### 4.4 冷却和串行策略

1. 文件内用例不并发。
2. 同一接收对象的真实发送之间执行冷却。
3. 默认套件只执行一组最小成功受理场景，不批量发送 14 次短信/邮件。
4. 重复发送、跨接口频控、恢复窗口测试放到显式开关下。
5. 发生限流后，不立即继续跑依赖同一接收对象的正向场景。
6. 限频专项仅做低次数探测，不做压力测试；必须同时开启发送开关和滥用测试开关。

### 4.5 数据传递

```text
YAML case
  ├─ mode: SHORT_MSG / EMAIL
  ├─ recipient_source: test_phone / test_email
  └─ authorization_mode: valid / missing / empty / forged / header_only
          ↓
Python helper
  ├─ 从 JKPT_VER_CODE_TEST_PHONE / EMAIL 解析接收对象
  ├─ 从 auth_headers 解析 Token
  ├─ 按场景构造 query Authorization
  └─ 构造 params={Authorization, mode, to}
          ↓
POST /api/monitor/ver-codes/*
          ↓
仅断言当前发送接口的 HTTP status、code、msg、响应安全与限频行为
```

- 不从响应、短信或邮件中提取验证码。
- 不写 `extract.yaml`。
- 不把验证码传给任何下游接口。
- 不建立跨 Test 类业务依赖；仅限频专项在同一方法/helper 内连续发起低次数请求。

---

## 五、用例矩阵

### 5.1 全接口公共契约场景

以下场景原则上覆盖全部 7 个接口；实际业务码和文案先校准再写入 YAML。

| 场景 | 输入 | 预期验证 | 默认运行 |
|------|------|----------|----------|
| 基础成功受理 | 合法 Authorization + 合法 mode + 专用接收对象 | HTTP/业务成功；响应不泄露明文验证码 | 受发送开关控制 |
| 缺 Authorization | 不传 query Authorization，Header 也移除 | 明确拒绝，不产生发送副作用 | 使用真实接收对象时受发送开关控制 |
| Authorization 为空 | `Authorization=""` | 明确拒绝 | 使用真实接收对象时受发送开关控制 |
| 伪造 Authorization | 随机非法 Token | 需要认证的接口拒绝；开放接口行为记录 | 使用真实接收对象时受发送开关控制 |
| 仅 Header 有 Token | Header 有 Token，query 不传 | 验证 OAS query 契约是否真实 | 使用真实接收对象时受发送开关控制 |
| 缺 mode | 不传 `mode` | 参数校验失败 | 是 |
| mode 为空 | `mode=""` | 参数校验失败 | 是 |
| mode 非法枚举 | `SMS`、`PHONE` 或随机值 | 参数校验失败，不发送 | 是 |
| mode 大小写错误 | `short_msg`、`email` | 验证是否严格区分大小写 | 是 |
| 缺 to | 不传 `to` | 参数校验失败 | 是 |
| to 为空 | `to=""` | 参数校验失败 | 是 |
| SHORT_MSG + 非法手机号 | 字母、位数不足、特殊字符 | 参数校验失败，不发送 | 是 |
| EMAIL + 非法邮箱 | 缺少 `@`、缺域名 | 参数校验失败，不发送 | 是 |
| mode/对象不匹配 | SHORT_MSG + 邮箱；EMAIL + 手机号 | 参数校验失败，不发送 | 是 |
| 超长 to | 超长字符串 | 参数长度校验失败，不 5xx | 是 |
| 注入字符 | 引号、脚本片段、SQL 风格字符串 | 安全拒绝，不 5xx，不回显敏感内容 | 是 |

说明：

- 公共负向场景很多，但不能简单把一组 case 切片给多个接口。
- 每个 YAML 顶层 key 都应有自己独立的 case 列表，保证一类一接口。
- 可由 Python helper 统一构建参数和断言，YAML 仍保持接口级分组。

### 5.2 接口特有业务场景

#### 5.2.1 `/ver-codes/login`

重点：登录验证码爆破、账号枚举、重复发送。

场景：

1. 已注册手机号/邮箱发送成功。
2. 未注册接收对象：响应不得泄露“账号存在/不存在”差异，或按产品明确规则校验。
3. 同一接收对象连续请求：验证限频。
4. 同一对象切换 `SHORT_MSG/EMAIL` 的格式校验。
5. 成功响应不得返回明文验证码。

#### 5.2.2 `/ver-codes/register`

重点：短信轰炸、重复注册、账号枚举。

场景：

1. 未注册专用测试接收对象发送成功。
2. 已注册对象重复申请注册验证码。
3. 同一目标快速重复请求。
4. 不同 Authorization 对同一目标请求，验证限频是否按目标生效。
5. 错误信息不得帮助攻击者批量枚举账号，除非产品明确允许。

#### 5.2.3 `/ver-codes/retrieve`

重点：找回密码越权、账号枚举。

场景：

1. 当前测试账号绑定的手机号/邮箱发送成功。
2. 非当前账号接收对象请求。
3. 不存在接收对象请求。
4. 伪造 Authorization 请求。
5. 响应不得返回验证码或账号敏感信息。

#### 5.2.4 `/ver-codes/update/pwd`

重点：修改密码前置验证是否绑定当前登录账号。

场景：

1. 当前登录账号绑定接收对象发送成功。
2. 其他账号接收对象请求，应拒绝。
3. 无 Token、伪造 Token、过期 Token。
4. Token 同时存在于 Header/query 但值冲突，确认服务端取值优先级。
5. 重复发送限频。

#### 5.2.5 `/ver-codes/bind/email`

重点：邮箱归属、重复绑定、跨账号绑定。

场景：

1. 当前账号未绑定的专用测试邮箱发送成功。
2. 当前账号已绑定邮箱重复申请。
3. 已被其他测试账号绑定的邮箱申请。
4. 非法邮箱、大小写和前后空格。
5. 无 Token、伪造 Token、Header/query Token 冲突。

#### 5.2.6 `/ver-codes/bind/phone`

重点：手机号归属、重复绑定、跨账号绑定。

场景：

1. 当前账号未绑定的专用测试手机号发送成功。
2. 当前账号已绑定手机号重复申请。
3. 已被其他测试账号绑定的手机号申请。
4. 非法号码、前后空格、国家码格式。
5. 无 Token、伪造 Token、Header/query Token 冲突。

#### 5.2.7 `/ver-codes/set/emergency-contact`

重点：紧急联系人属于高敏救命关系，防越权和骚扰。

场景：

1. 合法专用测试联系人发送成功。
2. 当前账号自身手机号作为紧急联系人。
3. 已存在紧急联系人重复申请。
4. 非法手机号/邮箱和 mode 不匹配。
5. 无 Token、伪造 Token、其他账号联系人。
6. 重复请求限频和跨接口共享限频。

---

## 六、限频与防轰炸专项

此部分默认关闭，仅 `JKPT_ENABLE_VER_CODE_ABUSE_TEST=true` 时运行。

### 6.1 最小自动化策略

不要做高并发压测。采用低副作用探测：

1. 同一接口、同一目标，短时间发送 2 次。
2. 同一目标，在 login/register/retrieve 间切换请求。
3. 同一 Token，切换不同目标。
4. 不同 Token，请求同一目标。
5. 等待冷却窗口后重试，验证恢复。

### 6.2 需确认的限频维度

- 接收对象维度。
- 账号/Token 维度。
- IP 维度。
- 接口场景维度。
- 全 ver-codes 共享维度。

### 6.3 断言原则

- 首轮仅记录实际限频业务码、文案和触发次数。
- 产品/后端确认规则后，才固定阈值断言。
- 限频响应应稳定，不返回 500。
- 被限频请求不得继续触发真实短信/邮件。
- 错误文案不得泄露内部 Redis key、账号 ID、手机号全量等信息。

---

## 七、验证码泄露与响应安全断言

每个成功响应额外检查：

1. `data` 不得直接等于 4–8 位纯数字/字母验证码。
2. `msg` 不得包含验证码。
3. 响应不得回显完整手机号、完整邮箱、完整 Token。
4. 失败响应不得返回内部异常栈、缓存键、模板内容。
5. HTTP Header 不应携带验证码。

如当前测试环境为了联调返回验证码：

- 不把明文值写入日志、YAML、Allure。
- 记录为安全风险或环境特例。
- 生产配置必须关闭该能力。

---

## 八、分阶段实施

### 阶段 0：响应基线校准

目标：获取真实业务码和文案，不产生不必要副作用。

执行：

1. 每个接口调用缺参场景，记录 HTTP status、业务 code、msg。
2. 验证 `Authorization` 到底读取 query、Header 还是两者。
3. 使用专用接收端各执行最少量成功请求。
4. 确认 `mode` 是否严格限制为 `SHORT_MSG/EMAIL`。
5. 确认成功响应 `data` 是否泄露验证码。
6. 确认接口认证分类：开放接口、仅非空校验、真实 Token 校验。
7. 确认最小安全冷却时间。

产出：

- 真实 code/msg 映射表。
- 认证行为表。
- 限频初始观察。
- 是否允许默认 CI 运行正向发送的结论。

### 阶段 1：公共契约自动化

1. 创建 Python/YAML 文件。
2. 建立 7 个 Test 类。
3. 实现参数构建、接收对象解析、脱敏、统一响应解析与断言。
4. 覆盖公共必填、格式、枚举、未授权场景。
5. 写入阶段 0 验证过的 expected code/msg。

### 阶段 2：接口特有发送安全场景

1. 补登录、注册、找回密码发送接口的账号枚举与接收对象存在性观察。
2. 补改密、绑邮箱、绑手机、紧急联系人发送接口的 Token 与接收对象归属校验。
3. 仅使用已确认的专用手机号、邮箱执行真实发送。
4. 若缺少“已注册/未注册/其他账号已绑定”等前置状态，则对应场景标记为可选或跳过，不额外修改账号状态造数。
5. 全部场景只断言发送接口，不消费验证码，不调用下游接口。

### 阶段 3：限频专项

1. 增加显式运行开关。
2. 实现低次数重复发送与恢复窗口验证。
3. 与后端确认阈值后固化断言。
4. 确认限频是否跨 ver-codes 接口共享。

### 阶段 4：稳定性与报告

1. 验证单文件 collect 结构为 7 个接口目录。
2. 验证默认回归不产生不可控短信/邮件。
3. 验证 Allure/失败上下文无手机号、邮箱、Token、验证码泄露。
4. 单独运行该 controller，确认无 xdist、无重试放大副作用。
5. 更新覆盖计划 4.6 状态。

---

## 九、实施任务拆分

### 任务 A：测试数据和环境准备

- [已具备] 专用测试手机号、邮箱。
- 将具体接收端值配置到 `JKPT_VER_CODE_TEST_PHONE`、`JKPT_VER_CODE_TEST_EMAIL`，不写入仓库。
- 配置真实发送开关、滥用测试开关和冷却时间。
- 明确 CI 默认关闭真实发送；专项执行时手工开启。
- 不准备验证码自动获取渠道，不准备下游接口数据。

### 任务 B：PII 脱敏前置

- 检查 `BaseRequest` 请求上下文是否保存原始 `to`。
- 检查 `print_request`、失败 Hook、Allure 附件是否泄露接收对象。
- 必要时实现值级手机号/邮箱脱敏。
- 更新技能方法字典和变更记录。

### 任务 C：框架文件

- 新增 `testcases/test_ver_code_controller.py`。
- 新增 `yaml/test_ver_code_controller.yaml`。
- 实现 `_VerCodeHelpers`。
- 实现 7 个 Test 类和 7 个 YAML key。

### 任务 D：基线与断言

- 运行缺参、非法格式、伪造 Token 场景。
- 记录并确认真实业务码/文案。
- 将确认后的 expected 写入 YAML。
- 增加验证码和 PII 不回显断言。

### 任务 E：副作用和限频

- 加真实发送总开关。
- 加滥用测试总开关。
- 实现冷却。
- 实现最小重复发送、跨接口限频、恢复窗口场景。

### 任务 F：验证和文档

- `pytest --collect-only` 核对分组。
- 单 controller 执行。
- 检查 Allure 附件脱敏。
- 检查默认 CI 不发送真实验证码。
- 更新 `api-automation-coverage-gap.plan.md`。

---

## 十、验收标准

### 10.1 结构验收

- [ ] `testcases/test_ver_code_controller.py` 与 YAML 一一对应。
- [ ] 7 个接口各自一个 Test 类。
- [ ] 类名为 `TestVc01...TestVc07...`，顺序可读。
- [ ] 7 个 YAML 顶层 key 均以 `_cases` 结尾。
- [ ] `parametrize` 不传 `ids=`。
- [ ] 无 `@allure.title(case["name"])`。
- [ ] Helpers 不以 `Test` 开头。

### 10.2 框架验收

- [ ] HTTP 入口仅使用 `BaseRequest`。
- [ ] 统一断言使用 `assert_api_result`。
- [ ] 正向 `expected.msg`，负向 `expected.error_msg`。
- [ ] 无 `api_test_framework.*`、`run_case`、`pytest_plugin`。
- [ ] 无生产 URL、真实密码、真实 Token 或未经授权的真实手机号/邮箱硬编码；YAML 中仅保留主人授权的两个专用测试接收端。

### 10.3 安全验收

- [ ] query `Authorization` 契约已验证。
- [ ] Header/query Token 冲突行为已记录。
- [ ] mode 非法值不会触发发送。
- [ ] to 非法值不会触发发送。
- [ ] 成功响应不泄露明文验证码。
- [ ] 日志、Allure、失败 Hook 不泄露完整手机号、邮箱、Token、验证码。
- [ ] 默认 CI 不执行真实发送和防轰炸专项。
- [ ] 限频用例不会形成短信/邮件轰炸。

### 10.4 覆盖验收

- [ ] 7 个 URL 均有独立自动化入口。
- [ ] 每个接口至少覆盖基础受理、缺参、非法 mode、非法 to、授权异常。
- [ ] 账号安全接口覆盖可执行的对象归属/越权场景；缺少前置状态的数据场景明确跳过。
- [ ] 限频规则经后端确认后再固定断言。
- [ ] 限频专项只在显式开关下执行低次数请求。
- [ ] 不存在验证码提取、`extract.yaml` 写入或下游接口调用。
- [ ] 计划完成后覆盖缺口 4.6 从 0/7 更新为 7/7。

---

## 十一、关键决策摘要

1. **仅测发送接口**：不调用、不校验任何下游登录、改密或绑定接口。
2. **不获取验证码**：当前无自动渠道，测试不读取、不提取、不消费验证码。
3. **模式 A，不用 extract**：7 个接口无状态依赖，也不允许写验证码到 `extract.yaml`。
4. **一 URL 一类**：符合 jkpt Suites 规范。
5. **接收端走环境变量**：专用手机号、邮箱已具备，具体值不进入仓库。
6. **Authorization 放 query**：OAS 明确要求，Header 不能替代契约验证。
7. **先校准，再写 expected**：OAS 无业务码，禁止猜测。
8. **真实发送默认关闭**：验证码接口有费用、骚扰和频控副作用。
9. **限频专项显式开启**：仅执行低次数探测，不做并发或压力测试。
10. **先治理 PII 日志**：失败上下文可能保存 `to`，安全问题优先于覆盖数量。
11. **成功响应检查验证码泄露**：`CommonResult<string>` 是本模块最高优先级响应安全断言。
