# web-users 平台用户接口自动化用例实施计划

> 制定时间：2026-09-04  
> 接口来源：Apifox 项目「Swagger3接口文档」最新 OAS（`x-download-time: 2026-09-04T08:16:36.902Z`）  
> 目标模块：`web用户信息管理接口`  
> 框架依据：仓库根目录 `skills/api-test-framework/SKILL.md`、`references/conftest-jkpt.md`、`references/yaml-conventions.md`、`references/cleanup-framework.md`  
> 关联缺口：`plan/api-automation-coverage-gap.plan.md` 4.7  
> 统计口径：web-users 业务 **13 个 URL、14 个 HTTP operation**；另含测试支撑 DELETE **1 个 URL、1 个 operation**；本计划总范围 **14 个 URL、15 个 operation**。

---

## 一、一句话结论与工程异议

本模块以**账号 A 的真实正向链路默认执行**为基线：能闭环的接口必须完成“前置快照 → 真实写入 → 业务旁证 → 恢复或保留已确认终态”，缺少验证码或合法业务参数时明确记录阻塞并主动补齐数据，不能用长期 skip 或仅负向用例冒充接口已完成。

### 1.1 必须先解决的契约歧义

1. **鉴权声明冲突**：15 个操作都把 `Authorization` 声明为必填 query 参数，但同时声明 `security: []`；当前 jkpt 框架实际通过 Header 传 Token。必须先确认服务端读取 Header、query 还是两者。
2. **文件上传声明可疑**：头像和平台 Logo 被 OAS 声明为 query 中的 `type: string, format: binary`。二进制文件通常应使用 `multipart/form-data`，不能直接按文档猜实现。
3. **成功业务码和错误文案未枚举**：OAS 只声明 `CommonResult` 结构，没有声明具体 `code/msg`；YAML expected 必须经基线探针回填，禁止臆测。
4. **OTP 发送与消费必须分开记账**：已有 ver-codes 能真实发送短信/邮件验证码，但当前不能自动取得有效验证码；发送成功默认执行，`pre-bind-validation`、绑手机、绑邮箱、验证码改密的消费成功链明确阻塞且不计 L3。
5. **测试清理接口契约有限**：`DELETE /api/monitor/test/web-user/authentication` 的 OAS 只证明测试环境路由、`Authorization/account` 参数和 200/204 等响应，不证明“仅管理员”“重复删除成功”“不存在账号成功”等行为。本轮只执行 A Token 清理 A 自身，并把权限、幂等、防枚举列为待实测目标，不宣称已覆盖管理员跨账号能力。
6. **高影响操作不等于默认跳过**：当前环境已确认为测试环境，账号 A 承担可执行正向；密码、名称和实名认证等可恢复操作串行闭环，恢复失败立即阻断后续写操作。头像和平台 Logo 使用主人提供的同一图片，并按确认要求保留为最终状态，不恢复原图。
7. **真实数据与脱敏边界**：经主人授权的真实姓名、手机号、邮箱和身份证可进入测试 YAML；密码、Token、有效验证码不得写入版本库。当前公共脱敏未覆盖 `idCardNumber`，实施实名认证前必须补齐请求、响应、最近请求上下文、控制台和 Allure 的脱敏验证。

### 1.2 覆盖完成的判定

不能把“有测试文件”直接等同于“接口已覆盖”。建议分三级记账：

| 等级 | 判定标准 | 是否可更新 4.7 为已完成 |
|------|----------|-------------------------|
| L1 契约骨架 | 有独立 Test 类，覆盖缺参、非法值、未授权，未执行成功业务链路 | 否 |
| L2 可执行成功 | 至少一个成功场景，完成响应结构和业务语义断言 | 只读接口可 |
| L3 副作用闭环 | 写操作成功后读回验证，且恢复原状态或达到主人明确批准的最终状态 | 高风险写接口必须达到此级 |

覆盖采用双口径，避免把测试支撑接口重复计入业务缺口：

- **web-users 业务接口**：13 个 URL、14 个 operation，对应原 4.7 分母。
- **测试支撑接口**：1 个 URL、1 个 operation，即取消实名认证 DELETE。
- **本计划总范围**：14 个 URL、15 个 operation。

回填 `api-automation-coverage-gap.plan.md` 时应先核对该 DELETE 是否已计入 P2 test/mock 桶；未重算全局统计前不得直接把 4.7 改成 14/14。无论采用哪种口径，都不能把 OTP 消费阻塞或 records PUT 骨架计为完成。

---

## 二、目标与边界

### 2.1 实施目标

1. 为 14 个 URL、15 个操作建立 pytest + YAML 数据驱动自动化入口。
2. 统一验证 HTTP 响应、`CommonResult` 信封、领域字段和写后副作用。
3. 验证 Header/query 鉴权通道、缺失/空/伪造 Token、冲突 Token 和低权限账号行为。
4. 覆盖昵称、平台名称的边界与恢复，以及头像/Logo 的真实上传和批准终态；地图图层 PUT 在参数真源缺失时明确阻塞。
5. 完整覆盖旧密码改密和默认密码重置的凭据状态机；验证码改密先完成真实发送与负向，消费链明确阻塞。
6. 手机号/邮箱本轮完成真实验证码发送、格式和错误码验证；有效码预校验、绑定与恢复待取码能力后补齐。
7. 覆盖实名认证字段格式、姓名与证件匹配、账号类型限制和重复认证行为。
8. 覆盖测试环境取消实名认证接口的 A 自身清理、参数和 200/204 响应分支；管理员跨账号权限、幂等、不存在账号和防枚举保留为待实测扩展，不在本轮误报。
9. 允许主人提供的姓名、手机号、邮箱和身份证进入测试 YAML；确保密码、Token、有效验证码以及所有敏感值不进入明文日志或 Allure。
10. 运行 web-user controller 时，数据已具备且能闭环的真实正向默认执行；风险通过串行、快照、读回、恢复和失败阻断控制，而不是通过默认关闭规避。

### 2.2 本轮不做与明确阻塞

1. 不在生产环境执行；本计划仅面向当前已确认的测试环境。
2. 不绕过验证码、不抓取个人短信或邮箱；当前只真实调用发送接口，OTP 消费成功链待授权取码能力后补齐。
3. `PUT /web-users/records` 的业务用途和合法 `mapLayer` 尚不明确，本轮保留契约/负向骨架但不执行正向，不计完成。
4. 手机、邮箱、pre-bind 和 code/pwd 当前不消费有效验证码，不把发送成功等同于下游接口成功。
5. 本轮取消实名认证只测 A Token + A canonical account，不执行 B→A，也不宣称覆盖管理员跨账号能力。
6. 不对改密、重置密码、绑定、实名认证或取消实名认证开启 pytest-xdist 或自动重试。
7. 不预设密码强度、验证码有效期、地图图层枚举、文件类型白名单等 OAS 未声明规则；reset 默认密码除外，按主人已确认的动态规则 `123abc!!YYMM` 运行时生成。
8. 不直接导入已删除的 `api_test_framework.*`，不使用 `run_case` 模式 C。
9. 密码 MD5、明文密码、有效验证码和真实 Token 不写测试 YAML；真实身份与联系方式可按主人授权写入 YAML，但必须在全部报告通道脱敏。

---

## 三、Apifox OAS 契约清单

### 3.1 URL 与操作

| 序号 | Method | Path | operationId | OAS 摘要 | 响应模型 |
|------|--------|------|-------------|----------|----------|
| 01 | GET | `/api/monitor/web-users/info` | `getWebUserInfoUsingGET` | 获取 web 用户个人信息 | `CommonResult<WebUserInfoRespDto>` |
| 02 | GET | `/api/monitor/web-users/records` | `getRecordUsingGET` | 获取上次使用的地图图层 | `CommonResult<WebUserOpRecordRespDto>` |
| 03 | PUT | `/api/monitor/web-users/records` | `updateMapLayerUsingPUT` | 更新地图图层 | `CommonResult<string>` |
| 04 | PUT | `/api/monitor/web-users/name` | `updateWebUserNameUsingPUT` | 修改用户名/昵称 | `CommonResult<string>` |
| 05 | PUT | `/api/monitor/web-users/avatar` | `updateAvatarUsingPUT` | 修改头像，不超过 3M | `CommonResult<string>` |
| 06 | PUT | `/api/monitor/web-users/platform-name` | `updatePlatformNameUsingPUT` | 修改平台名称，最长 15 字符 | `CommonResult<string>` |
| 07 | PUT | `/api/monitor/web-users/platform-logo` | `updateLogoUsingPUT_1` | 修改平台 Logo，不超过 3M | `CommonResult<string>` |
| 08 | PUT | `/api/monitor/web-users/authentication` | `authenticationUsingPUT` | 实名认证 | `CommonResult<string>` |
| 09 | POST | `/api/monitor/web-users/pre-bind-validation` | `preBindValidationUsingPOST` | 绑定前校验当前联系方式验证码 | `CommonResult<string>` |
| 10 | PUT | `/api/monitor/web-users/phone` | `bindPhoneUsingPUT` | 绑定手机号码 | `CommonResult<string>` |
| 11 | PUT | `/api/monitor/web-users/email` | `bindEmailUsingPUT` | 绑定邮箱 | `CommonResult<string>` |
| 12 | PUT | `/api/monitor/web-users/pwd` | `updatePwdUsingPUT` | 通过旧密码修改新密码 | `CommonResult<string>` |
| 13 | PUT | `/api/monitor/web-users/code/pwd` | `updatePwdByCodeUsingPUT` | 通过验证码修改密码 | `CommonResult<string>` |
| 14 | PUT | `/api/monitor/web-users/reset-pwd` | `reset2DefaultPwdUsingPUT` | 重置为默认密码 | `CommonResult<string>` |
| 15 | DELETE | `/api/monitor/test/web-user/authentication` | `clearAuthenticationUsingDELETE` | 去掉指定账号实名认证（仅测试环境） | `CommonResult<string>` |

### 3.2 参数契约

| 操作 | 参数（全部由 OAS 声明为 query） | OAS 约束/说明 |
|------|----------------------------------|---------------|
| info GET | `Authorization*` | string |
| records GET | `Authorization*` | string |
| records PUT | `Authorization*`, `mapLayer*` | `mapLayer` 为 string，未声明 enum |
| name PUT | `Authorization*`, `name*` | 昵称最长 15 字符，仅写在 description |
| avatar PUT | `Authorization*`, `avatar*` | binary，文件不超过 3M；传输方式需探针确认 |
| platform-name PUT | `Authorization*`, `name*` | 平台名称最长 15 字符，仅写在 description |
| platform-logo PUT | `Authorization*`, `logo*` | binary，文件不超过 3M；传输方式需探针确认 |
| authentication PUT | `Authorization*`, `idCardNumber*`, `name*` | 身份证号、真实姓名；未声明 pattern |
| pre-bind-validation POST | `Authorization*`, `code*`, `mode*` | `mode` 描述为 `SHORT_MSG/EMAIL`，schema 未声明 enum |
| phone PUT | `Authorization*`, `code*`, `mode*`, `phone*` | 未声明手机号 pattern |
| email PUT | `Authorization*`, `code*`, `email*`, `mode*` | email regex：本地部分 + 域名 + 2~4 位后缀 |
| pwd PUT | `Authorization*`, `newPassword*`, `oldPassword*` | 均为 MD5 后的密码，未声明长度/pattern |
| code/pwd PUT | `Authorization*`, `code*`, `mode*`, `password*`, `to` | `to` 非必填；描述为原手机号；密码为 MD5 |
| reset-pwd PUT | `Authorization*` | 未声明默认密码值和恢复策略 |
| test authentication DELETE | `Authorization*`, `account*` | 仅测试环境；按账号取消实名认证；OAS 示例 Authorization 为 `1`，真实授权规则未声明，本轮只实测 A Token + A canonical account |

`*` 表示 OAS `required: true`。

### 3.3 GET info 结构断言依据

`data` 为对象，OAS 声明以下字段：

- `account: string`
- `authentication: boolean`
- `avatar/email/name/phone/platformLogo/platformName: string`
- `level: int32`，一级为企业账号，二级及以后为企业子账号
- `role: {name: string, value: string}`
- `starBeans: int32`
- `flowInfo`：`callPhoneNum/sendBdNum/sendEmailNum/sendSmsNum/subAccountNum/terminalNum`，均为 int32
- `loginPageInfo`：`loginFlag/loginImage1/loginImage2/loginImage3/platformLogo/platformName: string`，`valid: boolean`

自动化不应只断言字段存在，还应验证：

1. 当前 Token 返回的是当前账号，A/B 账号不可串数据。
2. `level >= 1`；数量、额度、星豆余额不得出现无业务依据的负数。
3. 手机号、邮箱等敏感信息只允许在受权响应中出现，日志和报告必须脱敏。
4. 角色、登录页信息允许按账号类型为空时，应先经基线确认，不凭 OAS 强制非空。

### 3.4 GET records 结构断言依据

`data` 为 `WebUserOpRecordRespDto`，OAS 仅声明：

- `mapId: string`：用户上次使用的地图 ID。

需要通过基线确认 `data` 或 `mapId` 是否允许为空，以及 PUT 的 `mapLayer` 与 GET 的 `mapId` 是否为同一值域。

---

## 四、框架落地方案

### 4.1 文件范围

计划新增：

- `testcases/test_web_user_controller.py`
- `yaml/test_web_user_controller.yaml`

按探针结果可能修改：

- `common/requests_util.py`：补 `idCardNumber`/身份证值脱敏。
- `common/logger_util.py`：若公共脱敏入口需要同步。
- `skills/api-test-framework/references/methods-reference.md`、`skills/api-test-framework/CHANGELOG.md`：公共能力变化时同步文档。
- `conftest.py` 或 `common/` 登录 helper：仅在复用可刷新登录上下文确有需要时调整；本轮不以 marker/开关关闭真实正向。

原则上不把业务登录或 OTP 写进 `conftest.py`；若密码生命周期需要复用登录能力，应优先把当前 `conftest._login_token` 的可复用部分下沉到 `common/`，再由 conftest 和本模块共同调用，禁止在 testcase 复制一套验证码登录逻辑。

### 4.2 用例模式

采用 **模式 A + 文件内生命周期 helper + 可刷新账号上下文**：

- GET info、GET records：纯模式 A，无状态。
- name/platform-name：账号 A 执行“读原值 → 写入 → 读回 → 恢复 → 再读回”。
- avatar/platform-logo：账号 A 上传主人提供的同一张图片，读回并验证资源；该图是经确认的最终保留状态，不恢复原图。
- records PUT：因业务用途和合法 `mapLayer` 未知，本轮只建契约/负向骨架，正向明确阻塞。
- authentication：运行时读取初始状态；`false → 认证 → true → 取消 → false`，或 `true → 取消 → false → 认证 → true`，最终恢复初始 boolean。
- test authentication DELETE：独立 Test 类，仅验证 A Token 清理 A canonical account，兼容 200 JSON 与 204 No Content；不建立跨 Test 类顺序依赖。
- pre-bind/phone/email/code-pwd：真实验证码发送默认执行；因当前无取码能力，验证码消费成功链明确阻塞，负向仍执行。
- pwd/reset-pwd：账号 A 的凭据状态机，每个成功场景在同一测试方法内完成登录验证、Token 刷新和恢复，不依赖 `extract.yaml`。

不使用 `extract.yaml` 传任何账号状态。密码、Token、有效验证码只保存在进程内存；主人授权的姓名、身份证、手机号和邮箱可以存于测试 YAML，但进入日志、Allure、异常和最近请求上下文前必须脱敏。

### 4.3 一操作一 Test 类

| 顺序 | Test 类 | YAML 顶层 key | 默认执行 |
|------|---------|---------------|----------|
| 01 | `TestWu01GetInfo` | `web_user_info_cases` | 真实正向与负向默认执行 |
| 02 | `TestWu02GetRecords` | `get_web_user_records_cases` | 真实正向与负向默认执行 |
| 03 | `TestWu03UpdateRecords` | `update_web_user_records_cases` | 仅契约/负向；正向因 mapLayer 未知而阻塞 |
| 04 | `TestWu04UpdateName` | `update_web_user_name_cases` | 账号 A 成功恢复链与负向默认执行 |
| 05 | `TestWu05UpdateAvatar` | `update_web_user_avatar_cases` | 账号 A 上传确认图片并保留，默认执行 |
| 06 | `TestWu06UpdatePlatformName` | `update_platform_name_cases` | 账号 A 成功恢复链与负向默认执行 |
| 07 | `TestWu07UpdatePlatformLogo` | `update_platform_logo_cases` | 账号 A 上传同一确认图片并保留，默认执行 |
| 08 | `TestWu08Authentication` | `web_user_authentication_cases` | 按初态双向恢复，默认执行 |
| 09 | `TestWu09PreBindValidation` | `pre_bind_validation_cases` | 真实发送与负向默认；有效码消费阻塞 |
| 10 | `TestWu10BindPhone` | `bind_web_user_phone_cases` | 向 B 手机真实发送；绑定成功阻塞 |
| 11 | `TestWu11BindEmail` | `bind_web_user_email_cases` | 向已提供邮箱真实发送；绑定成功阻塞 |
| 12 | `TestWu12UpdatePassword` | `update_web_user_password_cases` | 账号 A 改密与恢复默认执行 |
| 13 | `TestWu13UpdatePasswordByCode` | `update_password_by_code_cases` | 真实发送与负向默认；验证码改密阻塞 |
| 14 | `TestWu14ResetPassword` | `reset_web_user_password_cases` | 账号 A 重置与恢复默认执行 |
| 15 | `TestWu15ClearAuthentication` | `clear_web_user_authentication_cases` | 测试环境 A→A 默认执行，兼容 200/204 |

每个类：

- 一个测试方法。
- 一次 `@pytest.mark.parametrize("case", _TEST_DATA["..."])`。
- 不传中文 `ids=`。
- 不使用 `@allure.title(case["name"])`。
- 共享逻辑放 `_WebUserHelpers`，不以 `Test` 开头。

### 4.4 必须使用的框架能力

- HTTP：`from common.requests_util import BaseRequest`
- 普通 REST 信封：`from common.case_report_util import assert_response`
- YAML：`from common.yaml_util import read_yaml`
- 日志：`sep/key/print_request/print_response`，所有敏感值先走公共脱敏
- JSONPath：如需提取字段，使用 `jsonpath.jsonpath` 函数式 API，且基于 `assert_response` 返回的 `json_data`，不重复 `response.json()`

所有请求必须包含：

- `case_name=case["name"]`
- `log_level="none"` 或经确认安全的 `simple`
- `biz_context={"请求参数": 已脱敏参数, "接口": path}`

---

## 五、鉴权与数据通道设计

### 5.1 鉴权探针矩阵

优先在 **GET info** 和 **GET records** 上完成，不用高风险写接口重复全部组合：

| 模式 | Header Authorization | query Authorization | 目标 |
|------|----------------------|---------------------|------|
| `header_only` | 合法 Token | 缺失 | 验证当前框架惯例 |
| `query_only` | 缺失 | 合法 Token | 验证 OAS 声明 |
| `both_same` | 合法 Token A | 同 Token A | 验证兼容方式 |
| `both_conflict` | Token A | Token B/伪造值 | 确认服务端优先级，不允许串账号 |
| `missing` | 缺失 | 缺失 | 必须拒绝 |
| `empty` | 缺失 | 空串 | 必须拒绝 |
| `forged` | 伪造 Token | 伪造 Token | 必须拒绝 |
| `expired` | 过期 Token（如可构造） | 同值/缺失 | 必须拒绝 |

探针完成后，正常业务用例统一使用服务端真实契约；YAML 不保存 Token。

对写接口的未授权场景：

- 优先使用“同值写入”或能立即读回、恢复的值，防止鉴权缺陷导致意外副作用。
- reset-pwd、authentication 等不能安全 no-op 的接口也要执行真实正向，但必须先建立恢复路径；恢复失败时立即停止本 controller 后续写操作。
- 当前测试环境是执行前置，不再用业务开关默认关闭正向；若 `base_url` 不属于配置的测试环境 allowlist，应在发出任何高影响请求前直接失败。

### 5.2 账号、可刷新上下文与运行时数据

账号 A 是本 controller 的默认业务主体，查询、昵称、头像、平台名称、平台 Logo、旧密码改密、重置密码、实名认证和取消实名认证均使用 A。账号 B 本轮仅提供短信验证码接收手机号及只读隔离校验；不执行 B→A 取消认证权限场景。

不能继续把 session scope 的 `auth_token/auth_headers` 当作不可变事实。实现 `_WebUserHelpers` 时建立进程内可刷新上下文：

```text
WebUserAuthContext
├─ login_input             # JKPT_ACCOUNT
├─ canonical_account       # 登录或 GET info 返回的规范账号
├─ original_password_md5   # JKPT_PASSWORD，仅内存
├─ current_password_md5    # 每次改密/重置后更新，仅内存
├─ token                   # 当前有效 Token，仅内存
├─ headers                 # 由当前 Token 动态生成
├─ level / role
└─ profile_snapshot        # info 初始快照
```

规则：

1. 每次密码变化后，用新密码重新登录并刷新 `token/headers`，后续请求不得继续复用旧 session Header。
2. `canonical_account` 必须来自 A 的登录结果或 GET info，不把 `JKPT_ACCOUNT` 输入值直接假定为 DELETE 的目标账号。
3. 普通写操作执行前保存 info 快照；密码和认证恢复失败时设置 controller 级阻断标志，后续写 case 直接失败并给出脱敏恢复指引。
4. `JKPT_WEB_USER_ALT_PASSWORD` 是 `/pwd` 正向必需的备用密码 MD5；缺失代表测试数据前置未满足，应把该正向标记为 **blocked** 并向主人补数，不能记为覆盖完成。
5. reset 默认明文按运行月份动态生成：`"123abc!!" + YYMM`，仅在内存计算 MD5，不进入 YAML、日志、Allure 或失败信息。
6. 主人已提供真实姓名、身份证、邮箱和 B 手机号；实施时写入对应 YAML 数据，但本计划正文不重复明文敏感值。
7. 主人上传的同一张图片是 avatar 与 platform-logo 的测试资产及最终保留值；实施前将附件保存为仓库约定的稳定测试资产并在 YAML 只引用相对路径，不生成临时孤儿文件。
8. 有效 OTP 不放环境变量或 YAML；当前发送接口真实执行，消费链等待后续接入经授权的短时取码能力。

### 5.3 敏感信息规则

1. `password/newPassword/oldPassword/code/Authorization` 自动全掩码；密码、Token、有效验证码禁止写入 YAML。
2. `phone/email/to` 使用现有值级脱敏；经主人授权的真实手机号和邮箱可以写入测试 YAML，但不得在控制台、Allure、异常或最近请求上下文明文出现。
3. 实施前把 `idCardNumber/id_card/identity_number` 纳入公共敏感 key；经授权的身份证可进入 YAML，正文不得进入请求日志、响应日志、最近请求上下文、Allure 或断言错误。
4. 真实姓名不作为通用 `name` 全局脱敏，否则会误伤昵称/平台名；实名认证请求必须支持**请求级额外敏感字段**，让该请求的 `name` 在 `print_request`、BaseRequest 上下文和 `biz_context` 中统一显示为 `[REAL_NAME]`，不能只掩码报告附件。
5. 响应不得回显密码 MD5、验证码、完整 Token 或身份证号；info 中手机号/邮箱即使是合法字段，也只能输出脱敏值。
6. 本计划和普通执行报告不回显主人提供的具体身份与联系方式；仅测试数据文件保存授权值。

---

## 六、接口用例矩阵

> 所有 `expected.code/msg` 均在阶段 0 基线校准后写入 YAML。下表描述业务预期，不猜具体数值。

### 6.1 GET `/web-users/info`

**优先级：P0；默认执行。**

场景：

1. 合法鉴权获取当前账号信息。
2. Header/query 鉴权八模式基线矩阵。
3. A/B 两账号分别请求，`data.account` 必须与各自登录后建立的 canonical account 一致，不得直接用登录输入值臆断，也不得串数据。
4. 响应信封完整，`data` 为 object。
5. `authentication`、`level`、`starBeans`、`role`、`flowInfo`、`loginPageInfo` 类型校验。
6. 各剩余额度为整数；是否允许负值需按业务真源确认，默认把负值视为红线候选。
7. 手机、邮箱字段不应在日志/Allure 明文出现。
8. 响应不得包含密码、密码 MD5、Token、验证码、身份证号。

### 6.2 GET `/web-users/records`

**优先级：P1；默认执行。**

场景：

1. 合法鉴权获取操作记录。
2. `data`/`mapId` 的存在性、nullable 和类型基线。
3. 无 Token、伪造 Token。
4. A/B 账号记录隔离。
5. 连续查询结果稳定，无无关副作用。

### 6.3 PUT `/web-users/records`

**优先级：P1；正向明确阻塞。**

主人已确认目前不知道该接口的业务用途，OAS 又未说明 `mapLayer` 的合法值域，也不能证明 GET 返回的 `mapId` 可直接作为 PUT 的 `mapLayer`。因此本轮不得用猜测值执行真实写入，也不得把该 operation 计为完成。

本轮可执行：

1. 建立独立 Test 类和 YAML key，校验参数组装与响应分支。
2. 缺 `mapLayer`、空串、纯空格。
3. 超长字符串、控制字符、XSS/SQL 风格文本，要求稳定拒绝且不 5xx；仅在确认失败不会写入后执行。
4. 无 Token、伪造 Token，并用 GET records 旁证原状态未变。

解除阻塞条件：

1. 取得该接口业务用途说明。
2. 取得至少两个合法 `mapLayer` 值及其与 GET `mapId` 的映射关系。
3. 再执行“读原值 → 写合法新值 → GET 读回 → 恢复原值 → GET 复核”的 L3 闭环。

### 6.4 PUT `/web-users/name`

**优先级：P1；可恢复写操作。**

场景：

1. 合法昵称修改：GET info 取原值 → 修改 → GET 验证 → 恢复 → GET 验证。
2. 长度边界：1、15、16 字符。
3. 中文、英文、数字、混合字符。
4. Emoji/代理对的长度计数，确认“15 个字符”按 code point、UTF-16 还是字节。
5. 缺失、空串、纯空格、前后空格。
6. 控制字符、换行、XSS/SQL 风格文本。
7. 与原昵称相同的幂等更新。
8. 无 Token、伪造 Token，且原值不变。
9. 子账号修改自身昵称的权限边界。

### 6.5 PUT `/web-users/avatar`

**优先级：P1；账号 A 真实上传默认执行，传输契约需先校准。**

阶段 0 先确认 `files=` 的字段名、content-type 和 Authorization 位置。实施前把主人上传的图片保存为稳定测试资产；该图片同时是正向测试值和测试结束后的最终保留头像。确认后覆盖：

1. 账号 A 上传确认图片，响应成功后 GET info 验证 `avatar` 更新。
2. 请求头像 URL，验证可访问、内容类型为图片，并按内容哈希或像素内容确认是目标图片；不能只断言 URL 非空。
3. 对同一图片重复上传，验证接口幂等或最终内容稳定。
4. 文件大小边界：接近 3MiB、等于 3MiB、超过 3MiB；“3M”按 3,000,000 还是 3×1024×1024 由真源确认。
5. 空文件、非图片内容伪装扩展名、错误 MIME、无扩展名。
6. GIF/WebP/BMP/SVG 等未声明格式的兼容性基线。
7. 超长文件名、特殊字符文件名。
8. 无 Token、伪造 Token，失败后 GET info 确认头像未被异常改变。

**最终状态例外**：不恢复执行前头像；最终必须保留主人确认的目标图片。除稳定测试资产外不生成临时脚本或中间图片，避免遗留孤儿文件。

### 6.6 PUT `/web-users/platform-name`

**优先级：P0；账号 A 真实正向与恢复链默认执行。**

场景与昵称长度/字符边界类似，额外验证：

1. 执行前读取并保存 A 的原 `platformName`；确认 A 当前 `level/role`，不臆测一级企业账号权限。
2. 修改后 GET info 的 `platformName` 与 `loginPageInfo.platformName` 一致。
3. 如存在登录页公开信息接口，验证外部展示同步。
4. 修改 → 读回 → 恢复原平台名称 → 再读回，最终状态与执行前一致。
5. 并发/重复提交最终状态明确；本轮只做低次数串行，不做并发压测。
6. 若恢复失败，阻断后续平台 Logo、密码和实名认证等写操作。

### 6.7 PUT `/web-users/platform-logo`

**优先级：P0；账号 A 真实上传默认执行，目标图片最终保留。**

复用头像的文件边界，并额外验证：

1. 使用与头像相同的主人确认图片上传平台 Logo；执行前记录 A 的 `level/role`，按实测结果判断权限。
2. 修改后 `platformLogo` 与 `loginPageInfo.platformLogo` 一致。
3. Logo URL 可访问，内容类型正确，不返回 HTML 错误页；按内容哈希或像素内容确认是目标图片。
4. 重复上传同一图片后最终内容稳定，无重复副作用或异常状态。
5. **最终状态例外**：不恢复原 Logo，测试结束后保留主人确认的目标图片。若上传成功但读回/资源校验失败，立即失败并阻断后续高影响写操作。

### 6.8 PUT `/web-users/authentication`

**优先级：P0；账号 A 真实认证与状态恢复默认执行。**

正向状态机：

1. 用当前 A 的可刷新上下文调用 GET info，保存 `initial_authentication`。
2. 若初始为 `false`：`PUT authentication → info == true → DELETE clear → info == false`。
3. 若初始为 `true`：`DELETE clear → info == false → PUT authentication → info == true`。
4. PUT 使用主人已授权的真实姓名与身份证数据；数据可位于 YAML，但请求日志、响应日志、Allure 和异常必须脱敏。
5. DELETE 同时兼容 `200 CommonResult` 与 `204 No Content`：200 才调用 `assert_response`，204 只断言 HTTP 状态，并统一通过 GET info 判断业务结果。
6. `finally` 根据初始 boolean 恢复：初始 false 则确保清除，初始 true 则确保重新认证；最终 GET info 必须与初始 boolean 一致。
7. 初始 true 时，GET info 只暴露 boolean，无法证明重新认证后后台记录 ID 与原记录完全相同；本轮验收口径是认证状态和同一授权身份恢复成功，记录级等价作为已知盲区记录。
8. 重复提交同一身份应幂等或明确拒绝，不得产生冲突状态；具体业务码经基线回填。

负向与边界：

1. 缺 `idCardNumber`、缺 `name`、二者空串/纯空格。
2. 身份证长度不足/超长、非法字符、校验位错误。
3. 15 位旧格式、18 位格式、`x/X` 大小写兼容性按产品规则校准。
4. 非法出生日期、非法地区码、未来日期等格式校验。
5. 姓名过短/超长、数字、特殊字符、前后空格。
6. 合法格式但姓名证件不匹配，应拒绝。
7. 无 Token、伪造 Token；失败后 info 状态不得变化。
8. 企业账号/子账号/个人账号的适用范围按实际账号类型和业务真源判断。
9. 响应和报告不得回显身份证号或真实姓名。

### 6.9 POST `/web-users/pre-bind-validation`

**优先级：P0；OTP 发送默认执行，消费成功链阻塞。**

本轮先调用对应 ver-codes 接口真实发送验证码：短信发送到已确认的 B 手机号，邮件发送到主人已提供的真实邮箱。发送接口的成功只能证明验证码投递请求可用，不能证明本接口校验成功。

本轮执行：

1. 真实短信/邮件发送请求及其 HTTP、信封和收件目标脱敏断言。
2. 缺/空 `code`，缺/空 `mode`。
3. 非法 mode、大小写错误、前后空格。
4. 明确错误验证码与 mode 混用。
5. 无 Token、伪造 Token。
6. 连续错误验证码只做低次数安全探测，不做爆破。

明确阻塞且不计 L3：

1. 当前绑定手机验证码校验成功。
2. 当前绑定邮箱验证码校验成功。
3. 有效验证码的一次性、过期、账号归属和 mode 隔离。
4. 预校验成功后的状态有效期、作用域及后续绑定关系。

解除条件：接入经授权的短时 OTP 获取能力，验证码只驻留内存并在使用后立即失效，不写 YAML/日志/Allure。

### 6.10 PUT `/web-users/phone`

**优先级：P0；真实发送默认执行，绑定成功链阻塞。**

本轮向已确认的 B 手机号真实发送绑定验证码，但因无法自动取得验证码，不提交有效码到 phone 接口，不改变 A 的绑定手机号。

本轮执行：

1. ver-codes 手机验证码发送成功，收件号码在报告中脱敏。
2. 缺/空 `code`、`mode`、`phone`。
3. 手机号位数不足/超长、字母、特殊字符、国家码、前后空格。
4. mode 非法或 `EMAIL` 与手机号验证码语义不匹配。
5. 明确错误验证码。
6. 无 Token、伪造 Token；GET info 旁证 A 手机号未变化。

明确阻塞且不计 L3：

1. 有效验证码绑定 B 手机号。
2. 绑定后重新登录、GET info 验证 phone 及旧 Token 失效策略。
3. 原手机号恢复链。
4. 验证码过期、重复消费、账号归属与已绑定号码冲突。

解除条件：取得有效验证码和可恢复原手机号的完整链路；届时必须执行“快照原手机号 → 绑定测试手机号 → 读回 → 恢复原手机号 → 再读回”。

### 6.11 PUT `/web-users/email`

**优先级：P0；真实发送默认执行，绑定成功链阻塞。**

本轮向主人已提供的真实邮箱发送绑定验证码；因无法自动取得验证码，不提交有效码到 email 接口，不改变 A 的绑定邮箱。

本轮执行：

1. ver-codes 邮件验证码发送成功，邮箱在报告中脱敏。
2. 缺/空 `code`、`mode`、`email`。
3. 缺 `@`、缺本地部分、缺域名、连续点、空格。
4. 域名后缀 1/2/4/5 位，观察 OAS regex 与真实业务是否一致。
5. 大小写、前后空格、`+tag` 等兼容性负向/契约观察。
6. 明确错误验证码、mode 不匹配、无 Token、伪造 Token；GET info 旁证 A 邮箱未变化。

明确阻塞且不计 L3：有效验证码绑定、验证码一次性/过期/归属、绑定后读回与原邮箱恢复。解除条件与 phone 相同，必须具备有效取码及 OLD → NEW → OLD 的恢复能力。

### 6.12 PUT `/web-users/pwd`

**优先级：P0；账号 A 凭据闭环默认执行。**

正向闭环：

1. 原密码从现有 `JKPT_PASSWORD` 读取，备用新密码从运行时 `JKPT_WEB_USER_ALT_PASSWORD` 读取；二者均为 MD5 且只驻留内存。
2. 用 A 当前 Token 执行“原密码 → 备用密码”，断言成功。
3. 探测旧 Token 是否仍有效并记录实测行为；不能假定其立即失效。
4. 原密码登录应失败，备用密码登录应成功；用成功登录结果刷新 `WebUserAuthContext.token/headers/current_password_md5`。
5. 用刷新后的上下文执行“备用密码 → 原密码”恢复。
6. 备用密码登录应失败，原密码登录应成功；再次刷新上下文，最终密码与执行前一致。
7. 若改密请求超时、断链或响应不可解析，进入 **unknown commit state**：分别尝试原密码和备用密码登录判定服务端实际状态，再选择恢复动作，禁止盲目重复提交。
8. 整个生命周期串行、禁止 rerun；`finally` 恢复失败必须成为主失败并阻断后续写操作。

负向与边界：

1. 缺/空 `oldPassword`、`newPassword`。
2. 错误旧密码。
3. 非 32 位、非十六进制、明文密码、大小写十六进制。
4. 新旧密码相同。
5. 无 Token、伪造 Token，且原密码仍可登录。
6. 连续错误旧密码只做低次数安全观察，不做爆破。

不再使用“B Token + A 旧密码”场景：当前 B 默认可能与 A 使用相同密码，该用例无法证明目标主体，反而可能真实修改 B 密码。

### 6.13 PUT `/web-users/code/pwd`

**优先级：P0；真实发送默认执行，验证码改密成功链阻塞。**

本轮先调用 `/ver-codes/update/pwd` 真实发送验证码；短信目标使用已确认的 B 手机号，邮件目标使用主人已提供的真实邮箱。因当前不能自动取码，不提交有效码执行密码变更，A 的当前密码必须保持不变。

本轮执行：

1. update/pwd 验证码发送请求成功，联系方式全程脱敏。
2. 缺/空 `code`、`mode`、`password`。
3. 非法 mode、大小写错误、明确错误验证码。
4. password 非 32 位、非十六进制、明文值。
5. `to` 缺失、mode 与 `to` 类型不匹配的实际契约基线。
6. 无 Token、伪造 Token。
7. 所有失败场景后用原密码重新登录，旁证密码未变化。
8. 响应不得回显验证码、联系方式或密码 MD5。

明确阻塞且不计 L3：有效验证码改密、Token 失效、登录验证、验证码重复消费及恢复原密码。解除条件是接入短时 OTP 获取能力，并复用 `/pwd` 的 unknown commit state 判定和最终恢复机制。

### 6.14 PUT `/web-users/reset-pwd`

**优先级：P0 最高风险；账号 A 重置与恢复默认执行。**

主人已确认默认密码动态规则：

```python
default_plain = "123abc!!" + datetime.now().strftime("%y%m")
default_md5 = md5(default_plain)
```

明文和 MD5 只在运行时内存生成，不写 YAML、日志、Allure 或异常信息。

正向闭环：

1. 保存 A 的原密码 MD5 和当前可刷新上下文，调用 reset-pwd。
2. 原密码登录应失败，动态默认密码登录应成功；刷新 Token/headers/current_password_md5。
3. 记录 reset 后旧 Token 是否有效的实测行为。
4. 立即调用 `/pwd` 执行“动态默认密码 → 原密码”。
5. 默认密码登录应失败，原密码登录应成功；再次刷新上下文，最终密码与执行前一致。
6. 若 reset 请求进入 unknown commit state，分别尝试原密码和当月动态默认密码登录判定实际状态，再恢复，禁止盲目重复 reset。
7. `finally` 恢复失败必须阻断后续写操作，并输出不含密码的人工救援上下文。

负向与观察：

1. 无 Token、空 Token、伪造 Token 必须拒绝，随后原密码仍可登录。
2. 当前 A 账号类型下的权限行为；其他账号类型不在无数据时臆测覆盖。
3. 低次数重复 reset 的幂等行为仅在恢复链已验证后执行。
4. 动态默认密码是否强制首次改密、旧 Token 是否失效，按实测记录安全结论。

### 6.15 DELETE `/test/web-user/authentication`

**优先级：P0；测试支撑接口，A→A 真实正向默认执行。**

契约事实与目标规则必须分开：

- **OAS 已知**：测试环境接口；query 参数 `Authorization/account` 必填；响应可能为 200 `CommonResult<string>`、204 No Content、401 或 403；`security: []`。
- **主人确认的本轮范围**：只用 A Token 清理 A 自身，目标 `account` 从 A 的 `canonical_account` 取得，不写死登录输入值。
- **待实测目标**：伪造/随机非空 Authorization 应拒绝；重复取消的幂等性需按实际基线记录。
- **本轮不宣称**：A 是否管理员、管理员跨账号清理、B→A 越权、不存在账号幂等、防账号枚举。这些均不是 OAS 已证明事实，留作后续有明确账号与权限数据时扩展。

场景：

1. 保存 A 的初始认证状态；若为 false，先用授权身份认证为 true。
2. A 当前 Token + A canonical account 调 DELETE，随后 GET info 必须为 false。
3. 若响应为 200 且有 JSON，使用 `assert_response`；若为 204，不解析 JSON，只断言状态码并以 info 旁证成功。
4. 对已未认证的 A 再次 DELETE，记录实际 HTTP/业务响应并确认最终仍为 false；在基线确认前不硬编码“必须 code=0”。
5. 缺 `account`、空串、纯空格、超长账号、特殊字符。
6. 缺 Authorization、空 Authorization、伪造 Token、OAS 示例随机非空值 `1`；无论响应为何，A 的认证状态不得被未授权请求改变。
7. Header/query Token 同值与冲突行为；冲突不得导致身份主体混乱。
8. 响应不得泄露身份证号、真实姓名或账号内部 ID。
9. `finally` 恢复 A 的初始认证 boolean：初始 true 则重新认证，初始 false 则保持清除，并由 info 最终旁证。

执行门禁：

1. controller 启动时校验 `base_url` 属于配置的测试环境 allowlist；不匹配时在任何高影响请求前立即失败。
2. 当前测试环境内不再通过默认 false 开关跳过 A→A 正向。
3. 认证类和取消认证类各自在同一测试方法内建立前置并恢复，不依赖类执行顺序。
4. 生产/预生产的路由隔离属于发布门禁，不在本轮测试环境用例中伪造验证结果。

---

## 七、副作用、恢复与执行隔离

### 7.1 风险分组

| 分组 | 操作 | 默认策略 |
|------|------|----------|
| S0 只读 | info GET、records GET | 账号 A/B 真实查询默认执行 |
| S1 可恢复资料 | name PUT、platform-name PUT | 账号 A 正向默认执行，读前快照并恢复 |
| S1-F 最终值已确认 | avatar PUT、platform-logo PUT | 上传同一确认图片并保留，正向默认执行 |
| S2 明确阻塞 | records PUT | 用途和合法 mapLayer 未知，不执行正向、不计完成 |
| S3 OTP/绑定 | pre-bind、phone、email、code/pwd | 真实发送与负向默认执行；有效码消费阻塞 |
| S4 凭据 | pwd、reset-pwd | 账号 A 串行真实闭环，动态刷新 Token |
| S5 身份状态 | authentication、test authentication DELETE | 测试环境 A→A 默认执行，按初态恢复 |

### 7.2 恢复原则

1. **先读原值，再写测试值**；读不到原值时，除图片最终值已获明确批准外，不执行对应写入。
2. 用 `try/finally` 恢复；恢复失败必须使测试失败、设置后续写操作阻断标志，并输出脱敏人工恢复上下文。
3. 恢复动作本身也要验证：200 JSON 使用 `assert_response`，204 空体仅断言 HTTP；两者最终都以 GET info 或重新登录作为业务旁证。
4. avatar 和 platform-logo 是明确例外：不恢复原图，最终保留主人提供的同一目标图片；必须验证远端内容而非只比较 URL。
5. name 和 platform-name 最终恢复执行前值；records PUT 因参数未知不进入恢复链。
6. phone/email 本轮不消费验证码、不改变绑定状态；后续补齐时必须准备 NEW 与原联系方式的可恢复链。
7. 改密类最终验收不是“恢复接口返回成功”，而是原密码重新登录成功并刷新 AuthContext。
8. 实名认证最终状态必须等于执行前 boolean：初始 false 最终 clear，初始 true 最终用授权身份重新认证。
9. DELETE 重复行为先按基线观察，不把 OAS 未声明的幂等成功写成既定契约。
10. 此文件不启用 xdist；高副作用 case 不配置自动 rerun。

### 7.3 是否扩展 cleanup-framework

本模块多数资源是“账号自身状态”，不适合等到 session 末统一清理：密码、昵称、平台名称和实名认证必须在当前 case 的 `finally` 中立即恢复，避免后续用例继承脏状态。头像和平台 Logo 不进入清理队列，因为主人已确认目标图片就是最终保留状态；phone/email 本轮不发生绑定写入。

实名认证已有独立 DELETE 恢复 API，仍优先在当前生命周期内直接调用，而不是依赖 session 末清理。仅当后续出现跨 case 造数且确有兜底需求时，再按 cleanup-framework 模板 B 增加按账号登记的认证清理 domain。

---

## 八、分阶段实施

### 阶段 0：契约、数据与安全前置

1. 刷新 Apifox OAS，锁定业务 13 URL/14 operation、测试支撑 1 URL/1 operation。
2. 在 info/records GET 上确认 Header/query Token 读取规则和冲突优先级。
3. 记录真实 HTTP status、业务 `code/msg`、无 Token/伪造 Token 响应和 nullable 结构。
4. 校准 avatar/logo 的真实 multipart 方式，并把主人上传图片保存为稳定测试资产。
5. 补齐身份证和实名认证姓名的请求级脱敏，验证最近请求上下文、控制台、Allure 和失败信息均不泄露。
6. 建立 `WebUserAuthContext`，验证 A 登录、canonical account 获取和 Token 刷新能力。
7. 校验当前 `base_url` 属于测试环境 allowlist；非测试环境在高影响请求前失败。
8. 确认 `JKPT_WEB_USER_ALT_PASSWORD` 已提供；缺失则把 `/pwd` 标记 blocked 并主动补数，不记完成。
9. 固化 reset 动态默认密码 `123abc!!YYMM` 的运行时生成与 MD5 规则。
10. 将 records PUT 的用途和合法 mapLayer 列为明确阻塞，不使用猜测值探测写入。

产出：鉴权行为表、code/msg 基线、文件上传方式、敏感数据门禁、可执行/阻塞清单。

### 阶段 1：框架结构与通用负向

1. 新增 Python/YAML 两个文件和 15 个 Test 类、15 个 YAML key。
2. 完成 info、records GET 全量断言与 A/B 只读隔离。
3. 完成各接口的缺参、非法格式、无 Token、伪造 Token 等稳定负向。
4. 对写失败场景补读回或重新登录旁证，证明无异常副作用。
5. 验证日志和 Allure 脱敏。

### 阶段 2：账号 A 可闭环正向默认执行

1. name、platform-name：读前快照 → 修改 → 读回 → 恢复 → 复核。
2. avatar、platform-logo：上传同一确认图片 → GET info/资源内容旁证 → 保留该图为最终状态。
3. `/pwd`：原密码 → 备用密码 → 登录刷新 → 原密码恢复 → 再登录。
4. `/reset-pwd`：reset → 当月动态默认密码登录 → `/pwd` 恢复原密码 → 再登录。
5. authentication 与 clear-authentication：分别按执行前 boolean 建立前置、真实变更并恢复；DELETE 兼容 200/204。
6. 任一恢复失败立即阻断后续写操作，不以其他用例成功掩盖环境污染。

### 阶段 3：OTP 真实发送与消费阻塞

1. 明确 ver-codes 发送接口与 web-users 消费接口的对应关系。
2. 向已确认的 B 手机号和真实邮箱发送验证码，验证发送接口成功及日志脱敏。
3. 执行 pre-bind、phone、email、code/pwd 的缺参、格式和明确错误码场景，并旁证账号状态未变。
4. 将四个接口的有效码消费成功链标记 blocked，不计 L3，也不以发送成功替代消费成功。
5. 后续接入经授权的 OTP 获取能力后，再实现有效期、一次性、归属、绑定恢复与验证码改密恢复。

### 阶段 4：稳定性、报告与覆盖回填

1. `pytest --collect-only` 核对 15 个 operation 与 YAML 映射。
2. 串行执行 controller；确认可闭环正向实际运行，OTP 消费与 records PUT 以明确 blocker 呈现。
3. 检查 Allure、控制台、失败附件无 Token、密码、验证码、手机号、邮箱、身份证和实名姓名明文。
4. 执行静态断言门禁：`.\.venv\Scripts\python.exe -m tools.assertion_lint .\testcases`。
5. 按 L1/L2/L3 实际状态回填覆盖；先核对测试 DELETE 是否已在 P2 统计，避免与 4.7 重复计数。
6. 发布门禁另行确认非测试环境的测试清理路由不存在或返回 404/403；本轮不把它冒充已验证结论。

---

## 九、预计 YAML 场景规模

建议先按以下规模设计，阶段 0 后去重冻结：

| 操作类别 | 预计叶子数 |
|----------|------------|
| info GET | 8~12 |
| records GET/PUT | 12~18 |
| name/platform-name | 各 10~14 |
| avatar/platform-logo | 各 10~14 |
| authentication | 12~18 |
| clear authentication DELETE | 10~14 |
| pre-bind-validation | 10~14 |
| phone/email | 各 12~18 |
| pwd | 12~16 |
| code/pwd | 14~20 |
| reset-pwd | 6~10 |

总量预计约 **150~205 个叶子**。可闭环的真实正向与稳定负向默认执行；OTP 消费和 records PUT 必须以明确 blocker 记账，不能用 skip 数量制造覆盖率，也不能把同一场景机械复制到所有接口造成无效膨胀。

---

## 十、实施任务拆分

### 任务 A：契约与数据基线

- [ ] 核定业务 13 URL/14 operation、测试支撑 1 URL/1 operation。
- [ ] 核定鉴权通道和 Token 冲突优先级。
- [ ] 核定 avatar/logo multipart 方式、昵称/平台名长度和文件 3M 口径。
- [ ] 将主人上传图片保存为 avatar/logo 共用稳定测试资产。
- [ ] 验证 A canonical account、当前认证状态和可刷新登录能力。
- [ ] 记录 records PUT 的业务用途/mapLayer blocker，不猜值执行。
- [ ] 固化 reset 动态默认密码规则和 Token 失效观察项。

### 任务 B：安全与恢复前置

- [ ] 公共脱敏增加身份证字段和实名认证请求级姓名脱敏。
- [ ] 验证密码、验证码、手机号、邮箱、身份证、实名姓名在控制台/Allure/失败 Hook 中均被隐藏。
- [ ] 实现 `WebUserAuthContext` 与写操作失败阻断机制。
- [ ] 配置测试环境 allowlist，非测试环境在高影响请求前失败。
- [ ] 确认 `JKPT_WEB_USER_ALT_PASSWORD` 可用；缺失主动补数并标记 `/pwd` blocked。

### 任务 C：框架文件

- [ ] 新增 `testcases/test_web_user_controller.py`。
- [ ] 新增 `yaml/test_web_user_controller.yaml`。
- [ ] 实现 `_WebUserHelpers`：鉴权构建、脱敏、200/204 分支、读回、登录刷新与恢复。
- [ ] 实现 15 个 Test 类和 15 个 YAML key。

### 任务 D：默认执行

- [ ] info/records GET 结构和账号隔离。
- [ ] 公共缺参、非法值、未授权及失败后无副作用旁证。
- [ ] name/platform-name 修改与恢复闭环。
- [ ] avatar/platform-logo 上传、资源内容验证并保留目标图。
- [ ] pwd/reset-pwd 凭据闭环。
- [ ] authentication/clear-authentication 按初态恢复闭环。

### 任务 E：明确阻塞与后续闭环

- [ ] pre-bind/phone/email/code-pwd 真实发送验证码并验证脱敏。
- [ ] OTP 消费正向标记 blocked；取得授权取码能力后补消费、绑定和改密恢复。
- [ ] records PUT 标记 blocked；取得业务用途和合法 mapLayer 后补 L3。
- [ ] clear-authentication 的跨账号管理员权限、不存在账号、防枚举作为后续扩展，不在 A→A 结果上误报。
- [ ] 非测试环境路由 404/403 作为独立发布门禁。

### 任务 F：验收与回填

- [ ] collect 结构正确。
- [ ] 可闭环真实正向在 controller 运行时实际执行。
- [ ] 除确认保留的 avatar/logo 外，写操作最终状态与执行前一致。
- [ ] assertion_lint 0 violations。
- [ ] 按双口径更新覆盖状态，避免测试 DELETE 与 P2 重复计数。

---

## 十一、验收标准

### 11.1 结构验收

- [ ] 一个 controller 文件 + 一个 YAML 文件。
- [ ] 14 URL、15 操作各有独立 Test 类。
- [ ] 15 个 YAML key 均以 `_cases` 结尾并与类一一对应。
- [ ] 类名使用 `TestWu01...TestWu15...` 可排序前缀。
- [ ] `parametrize` 不传中文 `ids=`，不使用动态中文 `@allure.title`。
- [ ] Helpers 不以 `Test` 开头。

### 11.2 框架验收

- [ ] HTTP 只通过 `BaseRequest`。
- [ ] 普通响应只通过 `assert_response` 完成解析和信封断言。
- [ ] 领域断言消费 `assert_response` 返回的 `json_data`，不重复 `.json()`。
- [ ] 正向 `expected.msg`、负向 `expected.error_msg`。
- [ ] 无 `api_test_framework.*`、`run_case`、`pytest_plugin`、`assertions[]`。
- [ ] 无生产 URL、明文/MD5 密码、有效验证码或真实 Token 硬编码；YAML 中的真实身份与联系方式均有主人授权且全链路脱敏。

### 11.3 安全与副作用验收

- [ ] 鉴权 Header/query 行为有实测结论，A/B Token 冲突不会串账号。
- [ ] 所有实际写操作都有 GET info、资源内容或重新登录旁证。
- [ ] name、platform-name、密码和实名认证最终状态与执行前一致。
- [ ] avatar 与 platform-logo 最终均为主人确认的同一目标图片，不恢复原图。
- [ ] `/pwd` 完成原密码 → 备用密码 → 原密码，`reset-pwd` 完成动态默认密码 → 原密码；最终原密码重新登录成功。
- [ ] authentication/clear-authentication 按初始 boolean 双向恢复；DELETE 的 200 JSON 与 204 空体均由 info 旁证。
- [ ] clear-authentication 目标账号来自 A canonical account；A→A 结果不被表述为管理员跨账号权限已覆盖。
- [ ] 伪造和随机非空 Authorization 不得在 A 上产生清除副作用；重复删除行为按实测记录，不预写 OAS 未声明结论。
- [ ] controller 默认执行所有数据已具备且能闭环的真实正向，不依赖默认 false 业务开关。
- [ ] 非测试环境在高影响请求前被 allowlist 门禁阻断；路由 404/403 作为独立发布门禁。
- [ ] 恢复失败会阻断后续写操作；高风险用例不并发、不自动 rerun。
- [ ] 控制台、Allure、失败附件无密码、Token、验证码、完整手机/邮箱/身份证号和实名姓名。

### 11.4 覆盖验收

- [ ] info、records GET 达到 L2。
- [ ] name、platform-name 达到恢复型 L3。
- [ ] avatar、platform-logo 达到“真实上传 + 内容旁证 + 批准终态保留”的 L3。
- [ ] pwd/reset-pwd 达到账号 A 的“原密码 → 备用/动态默认密码 → 原密码”闭环。
- [ ] authentication 与 clear-authentication 均按运行时初态完成变更、旁证和 boolean 恢复。
- [ ] pre-bind/phone/email/code-pwd 的验证码发送真实成功；消费链保持 blocked、不计 L3。
- [ ] records PUT 保持 blocked、不计完成，直至取得业务用途和合法 mapLayer。
- [ ] clear-authentication 本轮只按 A→A 范围记账；管理员跨账号、B 越权、不存在账号和防枚举不计已覆盖。
- [ ] 业务 13 URL/14 operation 与测试支撑 1 URL/1 operation 分开记账；回填前核对 P2，杜绝重复计数和长期 skip 虚报。

---

## 十二、关键决策摘要

1. **双口径统计**：web-users 业务为 13 URL/14 operation，测试支撑 DELETE 为 1 URL/1 operation；本计划共 14 URL/15 operation、15 个 Test 类。
2. **真实正向默认执行**：账号 A 承担数据已具备且能闭环的查询与写操作，不再用高风险开关默认跳过。
3. **先校准 Authorization**：OAS query 必填与当前 Header 栈冲突，先用只读接口锁定实际通道。
4. **使用可刷新 AuthContext**：密码变化后重新登录并刷新 Token，canonical account 从服务端返回取得。
5. **写操作必须有业务旁证**：仅断言 `code=0` 不算完成；恢复失败阻断后续写操作。
6. **图片是批准终态**：avatar 与 platform-logo 使用主人上传的同一图片，验证远端内容并最终保留，不恢复原图。
7. **认证按初态双向恢复**：初始 false 走认证后清除，初始 true 走清除后重认证；DELETE 兼容 200/204。
8. **取消认证仅测 A→A**：不把自清理结果误报为管理员跨账号能力；权限、幂等、防枚举区分 OAS 事实与待实测目标。
9. **旧密码改密真实闭环**：`JKPT_PASSWORD → JKPT_WEB_USER_ALT_PASSWORD → JKPT_PASSWORD`，以最终登录为恢复证据。
10. **reset 动态默认密码**：运行时生成 `123abc!!YYMM` 并计算 MD5，重置后立即通过 `/pwd` 恢复原密码。
11. **OTP 发送与消费分账**：短信发往已确认 B 手机、邮件发往已提供邮箱；当前不消费有效码，相关接口不计 L3。
12. **records PUT 明确阻塞**：业务用途和合法 mapLayer 未知前不猜值写入、不计完成。
13. **真实数据允许入 YAML**：主人授权的姓名、手机号、邮箱、身份证可用于用例；密码、Token、有效验证码禁止入库，所有敏感值全链路脱敏。
14. **覆盖按 L1/L2/L3 如实记账**：回填前核对测试 DELETE 是否已在 P2，杜绝重复计数、永久 skip 和仅负向覆盖虚高。
