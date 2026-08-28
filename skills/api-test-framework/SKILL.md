---
name: api-test-framework
description: >
  API自动化测试框架编码参考规范。当用户需要编写API接口自动化测试用例、
  生成测试代码、搭建新项目测试框架、或涉及pytest+YAML数据驱动的接口测试时触发。
  覆盖BaseRequest请求类、conftest.py fixture编写、YAML测试数据格式、
  参数化断言模式、Allure报告集成等全流程。触发词：
  写接口测试、API自动化、写测试用例、pytest参数化、YAML数据驱动、
  搭建测试框架、生成测试代码、接口断言、conftest fixture、
  BaseRequest
---

# API自动化测试框架 — AI编码参考规范

## jkpt 标准栈声明（生成约束）

**通用层**（跨项目可复用，本 SKILL 主体描述）：

- HTTP 客户端：`from common.requests_util import BaseRequest`
- 普通 REST 信封断言：`from common.case_report_util import assert_response`
- 底层 code/msg 比较：`common.allure_assert_util.assert_api_result`（普通 testcase 不直接调用）
- 日志：`from common.logger_util import sep, key, print_request, print_response`
- 数据：`from common.yaml_util import read_yaml, write_yaml, clear_yaml, resolve_extract_value, read_expected_msg`
- 用例模式：模式 A（无状态）/ 模式 B′（文件内多类 + extract）；模式 B 单类切片勿用于 Suites
- 协议层（如项目使用）：`bd_client` + `bd_test_terminal`（详见 [conftest-jkpt.md](references/conftest-jkpt.md)）

**适配层**（仅 jkpt，其他项目参考格式自建）：

- [references/conftest-jkpt.md](references/conftest-jkpt.md) — jkpt 专属 fixture 与依赖链
- [references/yaml-conventions.md](references/yaml-conventions.md) — jkpt YAML 命名约定
- `.cursor/rules/jkpt-api-test.mdc` — 生成约束

**禁止生成**（不在 jkpt 真实运行栈中）：

- `from api_test_framework.runner import run_case` / 模式 C（包已删除）
- `pytest_plugins = ["api_test_framework.pytest_plugin"]`
- 全局 Cursor 技能的 YAML `version: "1.0"` + `assertions[]` 格式

---

## 框架概述

基于 pytest + requests + YAML 的5层分层API自动化测试框架。AI在编写测试用例时，必须严格遵循以下层级调用约定和编码模式。

### 层级依赖关系

```
yaml/*.yaml(测试数据) → test_*.py(用例) → common/(公共工具)
                                           ↑
                                      conftest.py(fixture配置)
```

**调用规则**：
- 用例层 → 只调用 `common/` 的方法
- `common/requests_util.py` 是手写用例的**唯一 HTTP 入口**
- `api_test_framework/` 已从仓库删除，禁止 import

---

## 第1层：`api_test_framework/` — 已移除

> ⚠️ 该 Python 包已删除。不要生成 `from api_test_framework.* import ...`，也不存在「经 common 间接使用引擎」这层调用。

---

## 第2层：公共工具 (`common/`) — ⭐ 用例代码主要调用此层

### 2.1 `BaseRequest` — 增强版请求类（手写用例首选）

**文件**: `common/requests_util.py`
**导入**: `from common.requests_util import BaseRequest`

#### 构造与发送

```python
# 创建实例（默认debug=True）
http = BaseRequest()              # 默认超时30s，开启日志
http = BaseRequest(debug=False)   # 关闭日志

# 发送请求 — 核心方法
response = http.send_request(
    method="post",                # str: get/post/put/delete/patch
    url="https://...",            # str: 完整URL或相对路径
    params={},                    # dict: URL查询参数（GET/query风格）
    json={},                      # dict: JSON请求体
    data={},                      # dict: 表单请求体
    headers={},                   # dict: 请求头
    files={},                     # dict: 文件上传
    timeout=30,                   # float: 超时秒数
    case_name="登录测试",          # str: 用例名称（用于日志标识）
    log_level="full"             # str: "full"|"simple"|"none"
)
# 返回: requests.Response 对象
```

#### log_level 三种模式

| 模式 | 请求日志 | 响应日志 | 适用场景 |
|------|---------|---------|---------|
| `"full"` | 完整headers/body | 完整JSON body | 调试问题 |
| `"simple"` | 只显示params/data | 只显示code+msg | **日常运行（推荐）** |
| `"none"` | 无 | 无 | 批量性能测试 |

#### 敏感信息脱敏（自动处理）

请求、响应、日志和 Allure 上下文递归隐藏凭据、密码、验证码字段，并按值脱敏手机号和邮箱。

#### 典型调用模式

```python
# 模式A：GET带查询参数
res = BaseRequest().send_request(
    method="get",
    url=f"{base_url}/api/users",
    params={"page": 1, "size": 10},
    headers=auth_headers,
    case_name="获取用户列表",
    log_level="simple"
)

# 模式B：POST JSON body
res = BaseRequest().send_request(
    method="post",
    url=f"{base_url}/api/users",
    json={"name": "test", "role": "admin"},
    headers=auth_headers,
    case_name="创建用户",
    log_level="simple"
)

# 模式C：POST query参数风格（你的项目常用）
res = BaseRequest().send_request(
    method="post",
    url=f"{base_url}/api/login",
    params={"account": "admin", "password": "xxx"},
    case_name="登录",
    log_level="simple"
)
```

---

### 2.2 YAML工具

**文件**: `common/yaml_util.py`
**导入**: `from common.yaml_util import read_yaml, write_yaml, clear_yaml, resolve_extract_value, read_expected_msg`

```python
# 读取YAML → 返回dict/list
data = read_yaml("./yaml/test_login.yaml")
# data = {"login_cases": [{"name": "...", ...}, ...]}

# 写入extract.yaml（追加模式，跨用例持久化变量）
write_yaml("./extract.yaml", {"user_id": 123}, mode="append")

# 下游解析 YAML 中的 {{user_id}}
user_id = resolve_extract_value("{{user_id}}", required=True)

# 正向 expected.msg / 负向 expected.error_msg
exp_msg = read_expected_msg(case["expected"])

# 清空extract.yaml（每轮测试前调用）
clear_yaml()
```

### 2.2b 待支付单登记（jkpt 订单收尾）

**文件**: `common/order_cleanup_util.py`
**导入**: `from common.order_cleanup_util import register_unpaid_order_no`

buy 成功后登记（进程内名单，避免 extract last-wins 漏单）。session 末由 `cleanup_test_data` 收；`ENABLE_AUTO_CLEANUP=false` 时保留给人工扫码。

```python
register_unpaid_order_no(order_no)
```

### 2.2c 下单限频冷却（jkpt 同一账号 buy）

**文件**: `common/buy_cooldown_util.py`
**导入**: `from common.buy_cooldown_util import wait_buy_cooldown, mark_bought`

同一账号连续套餐/星豆 buy 会 `999 下单过于频繁`（约 65s）。商城、星豆、订单 lifecycle helper **共用**这根钟；`no_auth` 不要 mark。

```python
wait_buy_cooldown()
try:
    res = http.send_request("post", buy_url, json=body, headers=headers, ...)
finally:
    mark_bought()
```

---

### 2.3 IP获取

**文件**: `common/ipconfig.py`
**导入**: `from common.ipconfig import get_local_ips`

```python
ips = get_local_ips()
# 返回: ["192.168.1.100"]  排除127.x.x.x，默认取第一个
```

---

### 2.4 公共数据

**文件**: `common/common_data.py`
**导入**: `from common.common_data import get_current_datetime`

```python
ts = get_current_datetime()
# 返回: "20260427133000"  用于生成唯一测试数据名称
```

### 2.5 统一响应信封入口（普通 REST 必须）

**文件**: `common/case_report_util.py`
**导入**: `from common.case_report_util import assert_response`

```python
json_data = assert_response(
    case,
    response,
    biz_context={"请求参数": payload},
)
```

**用途**:
- 安全解析并缓存 JSON object，非 JSON、空体、缺 `code` 形成清晰失败
- 统一读取 YAML `expected.code` 与 `msg/error_msg`
- 仅在 `expected.http_status` 明确配置时校验 HTTP 状态
- 返回 `json_data`，供领域字段、分页、状态和副作用断言继续使用
- 请求、响应和失败上下文统一递归脱敏

**兼容入口**:
- `assert_case(case, json_data, biz_context)`：保留 intercom dict 入参和 `(code, msg)` 返回
- `send_case(...)`：保留 intercom 请求签名和 dict 返回
- `report_extra_and_assert(...)`：保留领域 rows 断言

`common.allure_assert_util.assert_api_result` 是底层比较器，普通 testcase 不直接调用。

**biz_context 建议字段**:
- `请求参数`: 用例关键请求字段
- `关键中间变量`: 动态 ID 等非敏感变量；验证码不得写入上下文

**静态门禁**:

```powershell
.\\.venv\\Scripts\\python.exe -m tools.assertion_lint .\\testcases
```

普通 testcase 扫描必须为 0 violations；协议、导出、fixture 和 cleanup 的专用解析不由该门禁机械替换。

---

### 2.6 日志工具

**文件**: `common/logger_util.py`  
**导入**: `from common.logger_util import sep, key, print_request, print_response, print_result`

```python
sep(" 测试用例: 登录失败 ")
key("captchaId", captcha_id)
print_request("POST", url, params=payload, headers=headers)
print_response(res)
print_result(True, "验证通过!")
```

**约定**:
- 统一使用该工具输出关键日志，避免各用例日志风格不一致
- 敏感字段（password/token/authorization 等）应做脱敏处理

---

### 2.7 验证码识别工具

**文件**: `common/captcha_util.py`  
**导入**: `from common.captcha_util import CaptchaRecognizer`

```python
ocr = CaptchaRecognizer()
captcha_text = ocr.recognize_from_response(resp)
```

**建议**:
- 验证码登录场景通过 fixture（如 `auth_token`）统一处理，不在每个测试重复识别逻辑
- 当识别失败导致登录失败时，使用重试机制而非直接失败

---

### 2.8 协议层（北斗 / 自定义二进制协议）— 可选

> 适用项目：仓库中存在 `common/bd_protocol_client.py` 等协议模块。**HTTP 项目可跳过本节**。

| 模块 | 用途 |
|------|------|
| `common/bd_protocol_client.py` | `BDProtocolClient` + 11 个 `send_*` 协议方法 |
| `common/protocol_transport.py` | `BDProtocolTransport`：POST `/api/datas/bd` 底层传输 |
| `common/protocol_codec.py` | `ProtocolCodec` HEX 编解码 + 随机坐标 / 轨迹 |
| `common/protocol_types.py` | `GeoPoint`、`ProtocolSendResult` 数据类 |

**何时用协议层**：

- 用例需要向后端发**二进制协议**，验证服务侧解码 / 持久化 / 联动业务
- 普通 HTTP 用例使用 `assert_response`；协议用例只关心 `ProtocolSendResult.success`

**用例最小骨架**（详细方法签名见 [methods-reference.md §16-19](references/methods-reference.md)；fixture 见 [conftest-jkpt.md](references/conftest-jkpt.md)）：

```python
class TestProtocolXXX:
    def test_send_alarm(self, bd_client, bd_test_terminal):
        result = bd_client.send_alarm_13(from_addr=bd_test_terminal)
        assert result.success, f"协议发送失败: code={result.code}, msg={result.msg}"
```

**约定**：

- 仅注入 `bd_client` 与 `bd_test_terminal`，**不要**再注入 `auth_headers`（transport 已剥离 Authorization）
- 坐标 / 手机号 / 时间戳缺省时由 codec 自动生成；只在明确测试边界场景才传入
- 模板：[assets/templates/test_case_protocol.tpl.py](assets/templates/test_case_protocol.tpl.py)

---

## 第3层：`conftest.py` 编码规范

### 必须提供的 Fixture

| Fixture名 | 作用域 | 用途 | 是否必须实现 |
|-----------|--------|------|-------------|
| `base_url` | session | 动态基础URL | ✅ 必须 |
| `auth_token` / `access_token` | session | 登录认证凭据 | ✅ 必须（按实际认证方式命名） |
| `auth_headers` / `api_headers` | session | 认证请求头字典 | ✅ 必须 |
| 业务前置数据(groupid/deviceid等) | session | 预创建的资源ID | ⚠️ 按需 |
| `device_manager` | session | GlobalData全局容器 | ✅ 推荐 |
| `clear_data_per_session` | session autouse | 清空extract.yaml | ✅ 必须（直接复制） |
| `log_all_requests_and_responses` | function autouse | Allure记录请求响应 | ✅ 必须（直接复制） |
| `pytest_runtest_makereport` | hookimpl | 测试结果日志 | ✅ 必须（直接复制） |

### 推荐通用能力（可直接复用）

- `generate_captcha_id()`（`common.captcha_util`）：统一生成验证码 `captchaId`（时间戳 + 随机数）
- `auth_token`：验证码识别 + 登录获取 token（失败自动重试）
- `auth_headers`：统一返回鉴权头，如 `{"Authorization": token}`
- `pytest_runtest_makereport`：失败时自动附加请求/响应/错误/断言详情到 Allure
- `clear_data_per_session`：会话级测试前清理、测试后收尾

### conftest.py 定制清单（改这3处就行）

```python
# 【位置1】pytest_configure() — 改端口号
base_url = f"http://{ip}:9004"        # ← 你的服务端口

# 【位置2】auth_token fixture — 改登录接口
url = f"{base_url}/api/xxx/login"     # ← 你的登录路径
payload = {"account": "admin", "password": "xxx"}  # ← 你的凭据

# 【位置3】auth_headers fixture — 改header格式
return {"Authorization": f"{token}"}  # 可能是Bearer/Token/其他格式
```

### 命令行参数支持

```bash
pytest --host=192.168.1.100    # 手动指定目标主机IP
```

---

## 第4层：用例编码模式

模式 A / B′ 管 **数据怎么流**。下面四层管 **Allure Suites 怎么长**。两件事正交：有状态用文件级 `extract.yaml`，不要靠「一个 Test 类装下整个控制器」。

完整骨架见 [assets/templates/test_case_simple.tpl.py](assets/templates/test_case_simple.tpl.py)（单接口）与 [test_case_crud.tpl.py](assets/templates/test_case_crud.tpl.py)（多接口 + extract）。

### Allure Suites 四层对齐（本技能栈默认）

allure-pytest 的 Suites 按 pytest 收集产物分层，**最后一层文件夹是 class**。同一类里再写多少个 `test_*`，报告里都还是平铺叶子。文件夹和叶子都按 **显示名** 排序，不是按源码顺序。

| 层 | pytest 产物 | Suites | 默认代表 |
|----|-------------|--------|----------|
| 文件 | `test_*.py` + 一份 YAML | suite | 一个模块 / 一个 controller |
| 类 | `class Test*` | **最后一层文件夹** | 一个**报告分组单元** |
| 方法 | `def test_*` | 叶子前缀 | 一个 YAML 顶层 `*_cases` |
| 参数化 | `@pytest.mark.parametrize("case", …)` | 叶子 | YAML 一行 = 一片叶子 |

**默认（pytest + YAML + 以 Suites 为主视图）：**

- 一个 YAML 顶层 `*_cases` ↔ **一个 class** ↔ **一个方法** ↔ **一次** `parametrize("case", …)`。禁止把多个接口的 case 切成 `test_data[:N]` 塞进同一类。
- 多接口文件必须拆类。单接口文件（登录、一个协议探测）一类即可，不必为拆而拆。
- class 名带 **可排序前缀**（补零数字，如 `Test01` / `Test02`）。前缀字母表由项目适配层定义，**不要**把某项目的 `TestEc` 抄到新项目。
- 共享逻辑放在不以 `Test` 开头的 Helpers（`python_classes = Test*` 时不会被收集）。
- YAML `name` 给人读：日志、`send_request(case_name=…)` 附件、`assert_response` 失败上下文。**不是** Suites 树标题。
- 叶子 id：不要用中文场景名当 `ids=` 或 `@allure.title`（Unicode 转义后按字符串排序会乱序）。默认 **不传 `ids=`**；不传并不保证所有 pytest 版本都显示 `[case0]`，换项目或升级后应核一次 nodeid。超过 9 条时注意 `case10` 会排到 `case2` 前。
- 场景名插到 YAML 列表 **开头** 会平移下标，Allure 历史会错位；接受，或改用 ASCII slug（适配层定）。
- extract 作用域是 **文件**。写 extract 的那一类用类级/模块级「只写一次」标志；**不要**用单类上的 `created_id` 跨类共享。
- 清理用 **module / session** fixture，不要只挂在「最后一个 Test 类」（`-k` 不跑该类时 teardown 不会走）。
- 文件内有 extract 链时，不要按 class 做 pytest-xdist；有副作用的叶子慎用 rerun。

`@allure.epic` / `feature` / `story` 可选，**不能代替**拆类。团队主视图若是 Behaviors，先改适配层，不要假定 Suites 规则失效。

换项目时只改「每一层代表什么」（适配层），不改这根轴。jkpt 填法见 [yaml-conventions.md](references/yaml-conventions.md)。

### 模式A：简单无状态接口（如登录、查询）

**适用**: 接口之间无依赖。单接口 → 一类；同一文件多个查询接口 → 仍按上一节拆类（无状态也可以拆）。

**文件结构**: 一个 `test_xxx.py` + 一个 `yaml/test_xxx.yaml`

**Python模板**（单接口；多接口用 crud 模板的多类骨架，每类绑定自己的 `*_cases`）:
```python
import pytest
from common.case_report_util import assert_response
from common.requests_util import BaseRequest
from common.yaml_util import read_yaml

_TEST_DATA = read_yaml("./yaml/test_xxx.yaml")

class Test01Xxx:
    @pytest.mark.parametrize("case", _TEST_DATA["xxx_cases"])  # 不要 ids=
    def test_xxx(self, base_url, auth_headers, case):
        url = f"{base_url}/your/api/path"
        payload = { /* 从 case 构建，不要改 case 字典 */ }
        response = BaseRequest().send_request(
            method="post",
            url=url,
            params=payload,
            headers=auth_headers,
            case_name=case["name"],
            log_level="simple",
        )
        json_data = assert_response(
            case,
            response,
            biz_context={"请求参数": payload},
        )
        # 领域字段按需继续断言 json_data；不要重复解析 $.code/$.msg。
```

### 模式B：单类 + 类变量 + 切片 — 勿用于 Suites 主视图

> ⚠️ 同一 `Test` 类里 `test_data[:N]` / `[N:M]` 切 CREATE/UPDATE/DELETE，Allure Suites 会把所有接口摊在一个文件夹。类变量也无法跨拆开的类共享。
>
> **本技能栈有状态默认用模式 B′**（文件内多类 + `extract.yaml`）。仅当项目明确不以 Suites 分组、且坚持一类到底时，才允许单类切片。

### 模式B′：`conftest` fixture + `extract.yaml`（有状态默认）

本仓库真实用例（如 `test_group_controller.py`）用**两条数据通道**：**fixture 注入** 与 **`extract.yaml` + `{{占位符}}`**。每个 `*_cases` 对应一个带排序前缀的 Test 类，不要退回模式 B 单类。

下面先写**原则与扩展方式**，再给出**参照示例**（示例仅对齐现有风格，**不是**唯一命名或唯一写法；新模块可自行约定 fixture 名、`extract` 键名与 YAML 占位符）。

#### 两条通道（原则）

| 通道 | 用途 | 典型做法 |
|------|------|----------|
| **Fixture** | session / 模块级前置，跨文件复用 | 在 `conftest.py` 中 `@pytest.fixture`，测试方法**参数注入**，方法体内读取返回值 |
| **`extract.yaml`** | 同文件内「接口 A 响应 → 接口 B 请求」 | 上游 `write_yaml("./extract.yaml", {"键": 值}, mode="append")`，下游 `resolve_extract_value` 解析 YAML 中的 `{{键}}` |

**不要在 `conftest` 里写 `extract.yaml`**（与项目习惯、清理职责分离一致）。**不要在测试里重复创建**已有 fixture 已提供的**同类**资源（避免重复造数）。

#### 方式一：Fixture（不固定 fixture 名与返回结构）

- 任意 pytest fixture（如本仓库的 `group_fixture`、`terminal_types`，或你新增的 `order_fixture`）只要在方法签名中声明，即可在方法体内使用。
- 返回值形态由项目约定（常见为 `dict`）；**fixture 名、字段名不由 SKILL 规定**。

**YAML 里如何表达「值来自 fixture」**（两种常见做法，可并存）：

- **做法 A（魔法串）**：YAML 某字段写 `{{three_id}}` 等，Python 中判断后从 fixture 取键，例如 `if "{{three_id}}" in str(case.get("groupId")): ... group_fixture.get("three_id")`。占位中的键名须与 fixture 返回结构一致。
- **做法 B（不进 YAML）**：YAML 只写字面量或空，由测试方法根据 `case["name"]` 或路由，直接从 fixture 返回值取字段组装 URL/body。

#### 方式二：`extract.yaml`（不固定键名）

- **写入**：上游 `code == 0` 时 `write_yaml("./extract.yaml", {"变量名": 值}, mode="append")`；键名自定，须与 YAML 里 `{{变量名}}` 一致。
- **读取**：`resolve_extract_value(case.get("某字段"), required=True)` 或 `resolve_extract_value("{{devices_addr}}", required=True)`。
- **跳过**：`required=True` 且变量不存在时 `pytest.skip`。
- **只写一次**：写 extract 的那一个 Test 类上用类级布尔，或用模块级变量（如 `_first_addr_extracted`）。拆类后不要指望「另一个 Test 类上的类变量」还能读到。

#### 分组 ID 也可走 extract

「分组 ID」不一定只来自 fixture：例如 `test_group_controller` 在创建成功后把 `one_id` / `two_id` / `three_id` 写入 `extract.yaml`，下游 YAML 写 `{{one_id}}` 等并由 `resolve_extract_value` 解析。与「fixture 预置分组」是**并列手段**，按接口依赖选用或组合。

#### 参照示例（后续 AI 对齐用；非强制）

**示例 1：分组 ID（fixture 通道，与 `test_terminal_controller` 常见写法对齐）**

- YAML（节选）：`groupId: "{{three_id}}"`（键名可换成你 fixture dict 中已有的任意一级，如 `two_id`）。
- Python（节选）：

```python
def test_xxx(self, base_url, auth_headers, group_fixture, case):
    gid = case.get("groupId")
    if "{{three_id}}" in str(gid):
        group_id = group_fixture.get("three_id")
    else:
        group_id = gid
```

**示例 2：设备 addr（extract 通道，与 `test_terminal_controller` 常见写法对齐）**

- 写入（节选）：创建成功且 `code == 0` 时 `write_yaml("./extract.yaml", {"devices_addr": addr}, mode="append")`（可配合「只写第一次」的类级标志）。
- 读取（节选）：`devices_addr = resolve_extract_value("{{devices_addr}}", required=True)`。

订单 ID、`addrList` 等其它链路变量：**同一模式**，替换键名与 JSONPath 即可。

#### 新接口依赖：快速自检

- 依赖来自**某次接口响应** → `write_yaml` + YAML `{{key}}` + `resolve_extract_value`。
- 依赖来自**环境 / session 预置** → `conftest` 定义 fixture → 方法签名注入 → 方法体内取用。
- 两者都要 → 方法体内分别组装；**仍不在 `conftest` 写 extract**。


#### 编写新用例时的统一约定

1. **session / 模块级环境数据** → 在 `conftest.py` 定义**对应 fixture** 并注入；名称与返回结构以项目为准。
2. **同文件链路动态值** → `extract.yaml` + YAML `{{占位符}}`；避免重复创建与已有 fixture **同职责**的资源。
3. **优先不修改** `parametrize` 注入的 `case` 字典，保持「方法体内组装参数」，与现有 `_assert_and_report` 一致。
4. 「只保留第一次成功提取」→ 写 extract 的那一类（或模块级）布尔；不要用单类 `created_id` 跨类传递。
5. 多接口文件按「四层对齐」拆类；`parametrize` 不要传中文 `ids=`，不要 `@allure.title(case["name"])`。

### 模式C：已移除

> `run_case` / `api_test_framework` 已从仓库删除。jkpt **禁止**生成该模式。无状态用模式 A，有依赖用模式 B′（文件内多类 + extract），协议用 `bd_client`。

### 断言标准模式

普通 REST 用例必须先通过统一响应入口完成响应解析和 `code/msg` 信封断言，再做领域字段断言：

```python
from common.case_report_util import assert_response

json_data = assert_response(
    case,
    res,
    biz_context={"请求参数": payload},
)

# 仅按领域需要继续断言 data；不要重复解析 $.code/$.msg
items = json_data.get("data") or []
assert isinstance(items, list)
```

`common.allure_assert_util.assert_api_result` 只作为底层比较器，由
`common.case_report_util.assert_response` 调用；普通 testcase 不得直接导入或调用。

### JSONPath 提取常用写法

项目使用 `jsonpath.jsonpath`（函数式 API），统一在文件顶部定义别名后使用，不使用 `jsonpath.JSONPath(...).parse(...)` 的 OOP 写法。

```python
import jsonpath

_jsonpath_parse = jsonpath.jsonpath   # ← 文件顶部声明一次，下面直接用

# json_data 已由 assert_response 或 parse_response_json 得到；不要再次 res.json()

# 领域字段提取（不重复读取 code/msg）
token = _jsonpath_parse(json_data, "$.data.token")
user_id = _jsonpath_parse(json_data, "$.data.userList[0].id")
addr_list = _jsonpath_parse(json_data, "$.data.items[*].addr") or []
```

---

## 第5层：YAML 数据文件格式规范

本节以仓库内 [yaml/test_group_controller.yaml](../../jkpt_api_test/yaml/test_group_controller.yaml) 为**参照**（非唯一文件名）：多段业务、多顶层 key、占位符与 `expected` 形态与当前项目一致即可。

### 标准结构

```yaml
# yaml/test_xxx.yaml
# 可选：首行注释写路径 + 本文件覆盖的接口/场景

# 按场景拆成多个顶层 key，各自对应 Python 里 read_yaml(...)["该key"] 与一组 @pytest.mark.parametrize
add_xxx_l1_cases:
  - name: "某模块-一级-正向"
    groupName: "AUTO_GROUP_L1"
    parentId: 0
    expected:
      code: 0
      msg: "成功"

  - name: "某模块-一级-负向-名称为空"
    groupName: ""
    parentId: 0
    expected:
      code: 1001
      error_msg: "分组名称不能为空"

add_xxx_l2_cases:
  - name: "某模块-二级-正向"
    groupName: "AUTO_GROUP_L2"
    parentId: "{{one_id}}"     # 与 extract.yaml 中写入的键名一致
    expected:
      code: 0
      msg: "成功"

update_xxx_cases:
  - name: "某模块-编辑-正向"
    groupId: "{{one_id}}"
    groupName: "Updated_{int(time.time())}"   # 由 Python 方法体内 replace，不在 YAML 执行代码
    expected:
      code: 0
      msg: "成功"

get_xxx_cases:
  - name: "某模块-查询-正向"
    expected:
      code: 0
      msg: "成功"

  - name: "某模块-查询-负向-缺少Token"
    no_auth: true               # 用例级开关：测试中分支处理 headers
    expected:
      code: 3001
      error_msg: "没有访问权限"

delete_xxx_cases:

  - name: "某模块-删除-正向"
    groupId: "{{three_id}}"
    expected:
      code: 0
      msg: "成功"
```

说明：`delete_xxx_cases:` 后空一行再写列表项的写法合法，与现有分组 YAML 一致。

### 设计规则

| 规则 | 说明 |
|------|------|
| 文件头注释 | 推荐写清路径与覆盖范围，便于检索 |
| 多顶层 `*_cases` | 按场景分块；Python 中 `read_yaml("./yaml/...yaml")["某key"]` 与各 `@pytest.mark.parametrize` 一一对应；**不必**强行合并为单一 `xxx_cases` |
| `name` | 语义化，建议含模块、行为、正向/负向；用于日志、`case_name` 附件、断言。**不是** Allure Suites 树标题 |
| 业务字段 | 与真实接口参数名一致（如 `groupName`、`parentId`、`groupId`、`groupIds`） |
| `expected` | 正向用 `code` + `msg`；负向用 `code` + `error_msg`。断言走 `read_expected_msg(case["expected"])`，禁止正向写 `error_msg: "成功"` |
| `{{变量名}}` | 与 `extract.yaml` 写入键一致；须为整段占位（如 `{{one_id}}`），由 `resolve_extract_value` 解析 |
| 运行时占位串 | 如 `Updated_{int(time.time())}`，在测试代码里 `replace` 替换，**不要**在 YAML 中写可执行表达式 |
| 开关字段 | 如 `no_auth: true`，用于分支构造请求头或鉴权 |
| 用例顺序 | 正向在前、负向在后；每个 `*_cases` 整段交给一个 Test 类，**不要**再 `test_data[:N]` 切片塞进同一类 |

---

## AI编写用例的工作流

当用户要求"帮我写XX接口的测试用例"时，按以下步骤执行：

### Step 1: 收集接口信息
- 接口URL路径
- HTTP方法(GET/POST/PUT/DELETE)
- 请求参数（query params or JSON body）
- 认证方式（是否需要token/header）
- 预期的正向返回和各类错误返回

### Step 2: 判断使用哪种模式
- 无状态接口 → **模式A**（多接口仍拆类）
- CRUD有关联 → **模式B′**（文件内多类 + extract）；不要用模式 B 单类切片
- 二进制协议 → **协议层**（`bd_client`）
- 不要使用已删除的模式C（`run_case`）

### Step 3: 生成两个文件
1. `yaml/test_xxx.yaml` — 测试数据
2. `testcases/test_xxx.py` — 测试逻辑

### Step 4: 检查清单
- [ ] 导入是否正确（`BaseRequest` from `common.requests_util`）
- [ ] `read_yaml` 路径是否正确（`./yaml/test_xxx.yaml`）
- [ ] `@pytest.mark.parametrize` 数据源是否匹配 YAML 顶层 key（以 `_cases` 结尾）；**一个 key 对一个 class**，不要 `ids=` 中文、不要 `@allure.title` 用 `name`
- [ ] 多接口文件是否一类一报告分组单元、类名是否带补零前缀；Helpers 是否不以 `Test` 开头
- [ ] 有 extract 时清理是否在 module/session，而不是只挂在最后一个 Test 类
- [ ] fixture 注入是否完整（`base_url`、`auth_headers`、业务 fixture）
- [ ] 普通 REST 断言是否使用 `assert_response(...)` 并传 `biz_context`；领域断言只消费返回的 `json_data`
- [ ] 关键字匹配逻辑是否覆盖了所有 case name
- [ ] 有动态数据的场景是否用了 `get_current_datetime()`
- [ ] `case_name` 和 `log_level` 参数是否传入 `send_request`
- [ ] **协议用例**：注入 `bd_client` + `bd_test_terminal`，**不**注入 `auth_headers`；断言 `result.success`
- [ ] **YAML 约定**：顶层 key 以 `_cases` 结尾；正向 `expected.msg`、负向 `expected.error_msg`；占位符 `{{xxx}}` 与解析路径一一对应（见 [yaml-conventions.md](references/yaml-conventions.md)）
- [ ] **禁止**：未生成 `run_case` / `pytest_plugin` / `assertions[]` 数组
- [ ] 没有硬编码生产 URL、明文密码、真实手机号 / 身份证

---

## 项目文件结构（新项目骨架）

本技能位于仓库根目录 `skills/api-test-framework/`（`SKILL.md` 在此，一眼可辨），**不是** Python 包 `api_test_framework/`。

```
repo-root/
├── skills/api-test-framework/     # 本技能（生成依据，含 SKILL.md）
└── jkpt_api_test/                 # 运行时项目
    ├── common/                    # 公共工具（用例唯一调用层）
    │   ├── requests_util.py
    │   ├── allure_assert_util.py
    │   ├── logger_util.py
    │   ├── captcha_util.py
    │   ├── yaml_util.py
    │   ├── order_cleanup_util.py
    │   ├── buy_cooldown_util.py
    │   ├── run_artifact_util.py
    │   ├── ipconfig.py
    │   ├── common_data.py
    │   ├── bd_protocol_client.py
    │   ├── protocol_transport.py
    │   ├── protocol_codec.py
    │   └── protocol_types.py
    ├── conftest.py
    ├── pytest.ini
    ├── pyproject.toml
    ├── run.py
    ├── extract.yaml
    ├── testcases/
    └── yaml/
```

> jkpt 适配层文档：[references/conftest-jkpt.md](references/conftest-jkpt.md) · [references/yaml-conventions.md](references/yaml-conventions.md)

---

## 详细方法签名与源码

> 各层完整的方法签名、参数说明、源码实现见 `references/methods-reference.md`
> 代码模板文件见 `assets/templates/` 目录（可直接复制到新项目使用）
