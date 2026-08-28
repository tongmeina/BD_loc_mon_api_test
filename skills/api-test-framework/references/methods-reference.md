# API测试框架 — 完整方法签名参考

> jkpt 只使用 `common/*`。`api_test_framework/` 已从仓库删除。生成代码时**仅引用 common 模块**。

## 目录

### 通用层（jkpt 实际使用 — 跨项目可复用）
- [8. common/requests_util.py](#8-commonrequests_utilpy)
- [9. common/yaml_util.py](#9-commonyaml_utilpy)
- [10. common/ipconfig.py](#10-commonipconfigpy)
- [11. common/common_data.py](#11-commoncommon_datapy)
- [12. common/allure_assert_util.py](#12-commonallure_assert_utilpy)
- [12a. common/case_report_util.py（统一响应信封入口）](#12a-commoncase_report_utilpy统一响应信封入口)
- [13. common/logger_util.py](#13-commonlogger_utilpy)
- [14. common/captcha_util.py](#14-commoncaptcha_utilpy)
- [16. common/bd_protocol_client.py（北斗协议客户端）](#16-commonbd_protocol_clientpy)
- [17. common/protocol_transport.py](#17-commonprotocol_transportpy)
- [18. common/protocol_codec.py](#18-commonprotocol_codecpy)
- [19. common/protocol_types.py](#19-commonprotocol_typespy)
- [20. common/export_assert_util.py（xlsx 导出断言）](#20-commonexport_assert_utilpy)
- [21. common/order_cleanup_util.py（待支付单登记）](#21-commonorder_cleanup_utilpy)
- [22. common/buy_cooldown_util.py（下单限频冷却）](#22-commonbuy_cooldown_utilpy)
- [23. common/run_artifact_util.py（开跑清空 Allure raw）](#23-commonrun_artifact_utilpy)

### 适配层（仅 jkpt）
- [15. conftest.py 常用fixture和hook](#15-conftestpy-常用fixture和hook)（详细见 [conftest-jkpt.md](conftest-jkpt.md)）

### 已移除

`api_test_framework/` Python 包已从仓库删除（2026-08-13）。**禁止**生成 `from api_test_framework import ...`、`run_case`、`pytest_plugins = ["api_test_framework.pytest_plugin"]`。用例只引用 `common.*`。

---

## 8. common/requests_util.py

### class `BaseRequest` (增强版)
⭐ **这是手写测试用例的主要入口类**

```python
class BaseRequest:
    def __init__(self, debug=True):
        self.session = requests.Session()
        self.debug = debug

    def send_request(self, **kwargs) -> requests.Response:
        """
        核心请求方法。
        
        标准requests参数: method, url, params, json, data, headers, files, timeout
        框架参数:
          - case_name: str  用例名称 (默认 '未知用例')；进日志与 Allure **附件标题**，不是 Suites 树节点
          - log_level: str  "full"|"simple"|"none" (默认 'full')
        
        附件标题形态：`[请求] METHOD /path · case_name`（见 `_allure_attach_title`）。
        Suites 目录结构由 Test 类拆分决定，见 SKILL 第4层「四层对齐」。
        
        与核心层client.py的区别:
          - 使用emoji风格日志 (🚀✅🟢🔴❌)
          - 自动识别业务码并带颜色标记
          - _safe_headers() 超长Authorization截断+隐藏关键字段
        """
    
    def enable_debug(self) -> None: ...   # 启用日志
    def disable_debug(self) -> None: ...  # 禁用日志
```

**日志输出示例** (log_level="simple"):
```
🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀 请求开始 🚀...
📋 用例: 登录测试
📍 方法: POST
📍 URL: http://192.168.1.100:9004/api/login
📍 参数: {'account': 'admin', 'password': '***'}
✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅ 响应开始 ✅...
📋 用例: 登录测试
📊 状态码: 200
📊 请求耗时: 0.153秒
📊 业务码: 0
📊 消息: success
🟢 业务状态: code=0, msg=success
✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅✅ 响应结束 ✅...
```

### `get_last_http_context() -> dict`

返回最近一次 HTTP 请求的上下文副本（request / response / error），供失败 hook 附加 Allure。

### `class NonJsonResponseError(ValueError)`

响应体为空或无法解析为 JSON 时抛出。属性：`response`、`context`。

### `get_response_json(response) -> Any`

读取并缓存响应 JSON。`BaseRequest`、日志和统一断言复用缓存，避免同一响应被重复解析。

### `parse_response_json(response, context: str = "") -> dict`

解析响应 JSON object；空体、非 JSON 或 JSON 非 object 时抛出 `NonJsonResponseError`。fixture 与普通响应信封优先用这个，而不是直接 `res.json()`。

### `sanitize_sensitive_data(data, parent_key: str = "") -> Any`

递归脱敏 Authorization、Token、Cookie、密码、验证码字段，以及手机号、邮箱等个人信息。请求上下文、响应上下文、控制台和 Allure 共用。

---

## 9. common/yaml_util.py

```python
def read_yaml(file_path: str) -> dict:
    """读取 YAML 文件，返回 dict/list（空文件返回 {}）"""

def write_yaml(file_path: str, data: dict, mode: str = "append") -> None:
    """写入 YAML。mode='append' 合并已有键；'overwrite' 覆盖整个文件。"""

def clear_yaml(file_path: str = "./extract.yaml") -> None:
    """清空 extract.yaml（写入空 dict）"""

def is_extract_placeholder(yaml_value) -> bool:
    """是否为整段 `{{var}}` 占位符"""

def resolve_extract_value(yaml_value, required: bool = False, extract_path: str = "./extract.yaml"):
    """解析 YAML 中整段 `{{var}}`，从 extract.yaml 取值。
    required=True 且变量不存在时 pytest.skip。非占位符原样返回。"""

def read_expected_msg(expected) -> str:
    """正向读 expected.msg，负向读 expected.error_msg；两者都有时优先 msg。"""
```

典型调用：

```python
from common.yaml_util import read_yaml, write_yaml, resolve_extract_value, read_expected_msg

write_yaml("./extract.yaml", {"devices_addr": addr}, mode="append")
addr = resolve_extract_value("{{devices_addr}}", required=True)
exp_msg = read_expected_msg(case["expected"])  # 正向 msg，负向 error_msg
```

---

## 10. common/ipconfig.py

```python
def get_local_ips() -> list[str]:
    """
    获取本机所有IPv4地址，排除127.x.x.x回环地址。
    返回: ["192.168.1.100"] 或 fallback ["127.0.0.1"]
    """
```

---

## 11. common/common_data.py

```python
def get_current_datetime(format: str = "%Y%m%d%H%M%S") -> str:
    """
    返回当前时间紧凑格式字符串。
    用于生成唯一的测试数据名称。
    返回示例: "20260427133000"
    """

def get_current_timestamp() -> int:
    """当前时间戳（13 位毫秒）"""
```

---

## 12. common/allure_assert_util.py

### `assert_api_result(case_name, expected_code, expected_msg, actual_code, actual_msg, biz_context=None, compare_message=True) -> None`

统一接口断言与 Allure 附件输出。

| 参数 | 类型 | 说明 |
|------|------|------|
| case_name | str | 用例名称（用于断言报错与附件） |
| expected_code | Any | 预期业务码 |
| expected_msg | str | 预期错误信息/提示 |
| actual_code | Any | 实际业务码 |
| actual_msg | str | 实际错误信息/提示 |
| biz_context | dict \| None | 业务上下文（可选，建议传请求参数、动态变量） |
| compare_message | bool | 是否比较消息；统一入口在 YAML 未声明消息时传 `False` |

**行为约定**:
- 作为底层 `code/msg` 比较器，由 `case_report_util.assert_response` 调用；普通 testcase 不直接调用
- 断言通过：打印成功日志并附加 `【成功】验证结果` 文本附件
- 断言失败：附加脱敏后的 `【失败】验证失败上下文` JSON 附件，并抛出带用例名的清晰断言错误

### `_attach_text(content, name) -> None`
内部辅助：安全附加 TEXT 附件（allure 不可用时自动跳过）。

### `_attach_json(data, name) -> None`
内部辅助：安全附加 JSON 附件（allure 不可用时自动跳过）。

---

## 12a. common/case_report_util.py（统一响应信封入口）

### `assert_response(case, response, biz_context=None, expected_http_status=None) -> dict`

普通 JSON REST 用例的默认入口：

1. 复用缓存安全解析响应 JSON object。
2. 仅在参数或 `expected.http_status` 明确配置时校验 HTTP 状态。
3. 明确区分 `msg` 缺失、`null` 与空串。
4. 校验 YAML `expected.code` 与可选 `msg/error_msg`。
5. 返回已解析 `json_data`，供领域字段和后置状态断言继续使用。

```python
from common.case_report_util import assert_response

json_data = assert_response(
    case,
    response,
    biz_context={"请求参数": payload},
)
```

### `assert_case(case, json_data, biz_context=None) -> tuple`

兼容入口。保留 intercom 既有 dict 入参和 `(code, msg)` 返回契约；负向用例可在信封通过后按 `code != 0` 提前返回。

### `send_case(http, method, url, case, headers, *, params=None, json=None) -> dict`

兼容 intercom 请求入口。安全解析一次并返回 dict；不改旧调用签名。

### `report_extra_and_assert(title, rows, summary) -> None`

领域 rows 扩展断言。公共层只负责脱敏报告和失败汇总，不解释报警状态、分页守恒、未读幂等等领域语义。

**边界：**

- 协议继续断言 `result.success`。
- xlsx/KML/二进制导出继续使用专用断言。
- 前置造数或动态提取失败继续使用 `pytest.fail`。
- 普通 testcase 不再自行解析 `$.code/$.msg`，也不直接调用底层 `assert_api_result`。

---

## 13. common/logger_util.py

```python
def sep(title="") -> None:
    """打印分隔线；有title时打印标题块"""

def key(key, value) -> None:
    """打印键值对"""

def print_request(method, url, params=None, headers=None) -> None:
    """格式化打印请求信息（包含基础脱敏）"""

def print_response(response) -> None:
    """格式化打印响应信息（优先输出JSON）"""

def print_result(success=True, message="") -> None:
    """打印测试结果（✅/❌）"""
```

**使用建议**:
- 用例日志统一走该模块，输出风格保持一致
- 请求、响应和 Allure 上下文中应始终对密码、token、手机号、邮箱和验证码等敏感字段脱敏
- `mask_log_data(data, field_name=None)`：递归脱敏结构化日志数据
- `mask_log_text(text)`：对非 JSON 文本中的手机号和邮箱做脱敏

---

## 14. common/captcha_util.py

### `generate_captcha_id() -> str`

生成 18 位 `captchaId`（毫秒时间戳 + 5 位随机数）。登录用例与 `auth_token` 共用，不要在 testcase 里再写一份。

### class `CaptchaRecognizer`

```python
class CaptchaRecognizer:
    def __init__(self) -> None:
        # 初始化 ddddocr 识别器
        ...

    def recognize(self, image_bytes: bytes) -> str:
        """识别验证码图片字节，返回字符串"""

    def recognize_from_response(self, response) -> str:
        """从 requests.Response.content 直接识别验证码"""
```

**典型调用**:
```python
ocr = CaptchaRecognizer()
captcha_text = ocr.recognize_from_response(resp)
```

---

## 15. conftest.py 常用fixture和hook

### `pytest_configure(config) -> None`
设置全局配置（如 `base_url`）并输出启动信息。

### `base_url(pytestconfig) -> str` (fixture, session)
返回基础 URL。

### `generate_captcha_id() -> str`
已迁到 `common.captcha_util`；`conftest.py` 再导出同名函数。生成验证码请求用 `captchaId`。

### `auth_token(base_url) -> str` (fixture, session)
验证码识别 + 登录获取 token（建议内置重试机制）。

### `auth_headers(auth_token) -> dict` (fixture, session)
基于 token 返回认证请求头。

### `pytest_runtest_makereport(item, call)` (hookimpl)
测试失败时附加请求/响应/错误/断言详情到 Allure。

### `clear_data_per_session()` (fixture, session, autouse)
测试会话前清理 `extract.yaml`，会话结束收尾日志输出。

> jkpt 项目的完整 fixture / hook 适配清单（含 `group_fixture`、`bd_test_terminal`、`bd_client`、`pytest_runtest_makereport` 等）见 [conftest-jkpt.md](conftest-jkpt.md)。

---

## 16. common/bd_protocol_client.py

> 北斗协议客户端层（属 `common/`，跨项目可复用；本项目通过 `bd_client` fixture 注入，详见 [conftest-jkpt.md](conftest-jkpt.md)）。

源文件：[../../jkpt_api_test/common/bd_protocol_client.py](../../jkpt_api_test/common/bd_protocol_client.py)

### class `BDProtocolClient`

```python
class BDProtocolClient:
    def __init__(
        self,
        transport: BDProtocolTransport,
        default_phone: str = "13250703582",
    ) -> None: ...
```

11 个 `send_*` 方法的统一签名约定：

- 第一个必填参数 `from_addr: str`（设备 SN / addr）
- 坐标 `lon` / `lat` 缺省 → 中心点 (113.466203, 23.170439) 半径 100m 随机
- 5 点轨迹 `points` 缺省 → 中心附近随机起点 + 等距 10m
- `phone` 缺省 → `default_phone`
- 返回 `ProtocolSendResult`（status_code / code / msg / raw_response / request_body / `.success`）

### `send_text_92(from_addr, case_name="协议-92短文本无位置") -> ProtocolSendResult`
0x92 短文本（无位置）。

### `send_text_93(from_addr, lon=None, lat=None, case_name="协议-93短文本有位置") -> ProtocolSendResult`
0x93 短文本（INT 坐标）。

### `send_voice_a6(from_addr, case_name="协议-A6神经语音") -> ProtocolSendResult`
0xA6 神经语音（固定 HEX 尾，无变量）。

### `send_alarm_13(from_addr, lon=None, lat=None, phone=None, case_name="协议-13报警") -> ProtocolSendResult`
0x13 EE 推送报警（INT 坐标 + phone HEX）。

### `send_safe_14(from_addr, lon=None, lat=None, phone=None, case_name="协议-14报平安") -> ProtocolSendResult`
0x14 报平安（INT 坐标 + phone HEX）。

### `send_location_a4(from_addr, points=None, case_name="协议-A4定位轨迹") -> ProtocolSendResult`
0xA4 推送定位（5 点 DMS 轨迹 + 各点独立随机方向角 + XOR 校验）。

### `send_image_aa(from_addr, case_name="协议-AA图片", interval_seconds=10) -> list[ProtocolSendResult]`
0xAA 图片分 7 包顺序发送（第 1 包按 JMX 重复一次）。**返回列表**，每包一个结果。`interval_seconds` 控制包间隔。

### `send_location_15(from_addr, points=None, case_name="协议-15多点定位") -> ProtocolSendResult`
0x15 多点定位（5 点 INT 坐标 + 各自时间戳 delta，每步 5 秒）。

### `send_alarm_ee(from_addr, lon=None, lat=None, case_name="协议-EE报警") -> ProtocolSendResult`
0xEE 报警（北京时间各分量 + DMS 坐标）。

### `send_safe_e1(from_addr, lon=None, lat=None, case_name="协议-E1报平安") -> ProtocolSendResult`
0xE1 报平安（北京时间 hh/mi/ss + DMS 坐标）。

### `send_sms_94(from_addr, phone=None, case_name="协议-94高级短信") -> ProtocolSendResult`
0x94 高级短信（phone HEX + 时间戳 HEX）。

### `resolve_phone_hex(phone) -> str`
便捷封装，等价于模块级 `resolve_phone_hex(phone, default_phone=self.default_phone)`。

### 最小用例片段

```python
def test_send_alarm(self, bd_client, bd_test_terminal):
    result = bd_client.send_alarm_13(from_addr=bd_test_terminal)
    assert result.success, f"code={result.code}, msg={result.msg}"
```

---

## 17. common/protocol_transport.py

源文件：[../../jkpt_api_test/common/protocol_transport.py](../../jkpt_api_test/common/protocol_transport.py)

### class `BDProtocolTransport`

```python
class BDProtocolTransport:
    DEFAULT_TO_ADDR = "110110110"
    DEFAULT_PATH = "/api/datas/bd"

    def __init__(
        self,
        base_url: str,
        headers: dict[str, str] | None = None,
        http: BaseRequest | None = None,
        to_addr: str = DEFAULT_TO_ADDR,
    ) -> None: ...

    def send_bd_content(
        self,
        content_hex: str,
        from_addr: str,
        case_name: str = "",
        to_addr: str | None = None,
    ) -> ProtocolSendResult: ...
```

**行为约定**：

- 请求体严格按 JMX 结构组装：`commInfos[0]` + `receipts[0]`
- `time` 字段使用北京时区 `YYYY-MM-DD HH:MM:SS`
- 接口 `/api/datas/bd` **不需要 Authorization**，发送前自动剥离
- 默认 `Content-Type: application/json`

通常无需直接调用，由 `BDProtocolClient` 各 `send_*` 内部使用。

### `_now_cst_str() -> str`
模块函数，返回当前北京时间字符串。

---

## 18. common/protocol_codec.py

源文件：[../../jkpt_api_test/common/protocol_codec.py](../../jkpt_api_test/common/protocol_codec.py)

### 常量

| 常量 | 值 |
|------|----|
| `DEFAULT_CENTER_LON` | `113.466203` |
| `DEFAULT_CENTER_LAT` | `23.170439` |
| `DEFAULT_RADIUS_M` | `100` |
| `DEFAULT_TRAJECTORY_STEP_M` | `10` |
| `DEFAULT_PHONE` | `"13250703582"` |

### class `ProtocolCodec`（全部 staticmethod）

```python
ProtocolCodec.hex_timestamp_up() -> str                         # 当前秒级 HEX (大写)
ProtocolCodec.hex_datetime_cst() -> dict                        # {yy, mm, dd, hh, mi, ss} 各 2 位 HEX
ProtocolCodec.hex_ts_deltas(count=5, step_sec=5) -> list[str]   # 过去 N 个点的 HEX，最近→最早
ProtocolCodec.lon_int_hex(lon) -> str                           # INT4 大端 HEX
ProtocolCodec.lat_int_hex(lat) -> str
ProtocolCodec.lon_dms_hex(lon) -> str                           # DMS 8 字符 HEX
ProtocolCodec.lat_dms_hex(lat) -> str
ProtocolCodec.phone_hex(phone) -> str                           # 5 字节 HEX；非法回退 DEFAULT_PHONE
ProtocolCodec.angle_hex(angle_deg) -> str                       # 4 字符 HEX
ProtocolCodec.calc_xor(hex_str) -> str                          # 异或校验，返 2 字符 HEX
ProtocolCodec.random_point(center_lon=..., center_lat=..., radius_m=...) -> (lon, lat)
ProtocolCodec.random_trajectory(count=5, ...) -> (points, angle_deg)
```

### `resolve_phone_hex(phone, default_phone="13250703582") -> str`
模块函数，空入参回退 `default_phone`。

---

## 19. common/protocol_types.py

源文件：[../../jkpt_api_test/common/protocol_types.py](../../jkpt_api_test/common/protocol_types.py)

### dataclass `GeoPoint`

```python
@dataclass
class GeoPoint:
    lon: float
    lat: float
    def as_tuple(self) -> tuple[float, float]: ...
```

### dataclass `ProtocolSendResult`

```python
@dataclass
class ProtocolSendResult:
    status_code: int
    code: int
    msg: str
    raw_response: dict = field(default_factory=dict)
    request_body: dict = field(default_factory=dict)

    @property
    def success(self) -> bool:
        # 仅当 HTTP 200 且业务 code == 0
        return self.status_code == 200 and self.code == 0
```

用例断言推荐：

```python
result = bd_client.send_xxx(...)
assert result.success, f"协议发送失败: code={result.code}, msg={result.msg}"
```

---

## 20. common/export_assert_util.py

二进制导出（xlsx）响应解析与结构断言，供 `test_batch_terminal_controller` 等设备/轨迹导出用例使用。

### dataclass `XlsxSheetSnapshot`

```python
@dataclass
class XlsxSheetSnapshot:
    sheet_name: str
    headers: list[str]
    data_row_count: int
    first_data_row: tuple[Any, ...] | None
    addr_column_values: list[str] | None = None
```

### `parse_xlsx(content: bytes) -> XlsxSheetSnapshot`

用 `openpyxl` 解析 xlsx 首 sheet：首行为表头，跳过全空行后统计数据行。

### `assert_xlsx_export_structure(...) -> XlsxSheetSnapshot`

| 参数 | 说明 |
|------|------|
| `case_name` | 用例名（失败消息前缀） |
| `content` | `res.content` 原始字节 |
| `expected` | YAML `expected` 块，支持 `headers`、`filename`、`addr_column`、`min_rows` |
| `addr_count` | 请求 addr 数量，未配 `min_rows` 时作为最小行数 |
| `content_disposition` | 响应头，校验 `filename` |

断言顺序：正文大小 → `PK` 魔数 → 文件名 → 表头完全一致 → 数据行数 → `addr_column` 非空行数。

### `assert_export_response(*, case_name, response, expected, require_binary=False, addr_count=None) -> None`

导出接口统一入口：响应体像 JSON 时走业务码断言；否则按二进制 xlsx 结构断言。`require_binary=True` 时若收到 JSON 直接失败。

---

## 21. common/order_cleanup_util.py

本 session 待支付订单登记。**进程内名单，不写 `extract.yaml`**（同 key last-wins 会漏星豆第一张）。conftest **禁止**写 extract；收尾由 `cleanup_test_data` 调用。

导入：`from common.order_cleanup_util import register_unpaid_order_no`

### `register_unpaid_order_no(order_no) -> None`

buy 成功后登记。空值忽略，同号去重。商城正向 buy、星豆**每条**正向 buy、订单 helper 两张 lifecycle 单都要调。

### `registered_unpaid_order_nos() -> list[str]`

返回当前名单副本。

### `cleanup_registered_unpaid_orders(base_url, auth_headers) -> None`

对名单逐张 `POST /api/monitor/order/cancel` 再 `DELETE /api/monitor/order/delete`（query `orderNo`，Header token）。单条失败只打日志。只动本轮登记单，不扫账号历史 UNPAID。`ENABLE_AUTO_CLEANUP=false` 时 conftest 不调用本函数。

---

## 22. common/buy_cooldown_util.py

同一测试账号连续 `POST .../buy`（套餐商城 / 星豆 / 订单 lifecycle helper）会返回 `999 下单过于频繁`。冷却约 65s（现网实测）。**进程内共享钟**，三个模块一起 wait/mark，不要各自记时间。

导入：`from common.buy_cooldown_util import wait_buy_cooldown, mark_bought`

### `wait_buy_cooldown() -> None`

距上次 `mark_bought` 不足 65s 则阻塞；从未 mark 则立即返回。

### `mark_bought() -> None`

一次 buy **请求已发出**后调用（成功、业务失败、999 都算）。`no_auth` / 未真正下单的参数校验负向不要 mark。

```python
wait_buy_cooldown()
try:
    res = http.send_request("post", buy_url, json=body, headers=headers, ...)
finally:
    mark_bought()
```

订单 lifecycle 遇 999 可再 wait+buy 一次；仍 999 再 skip。不要改去 cancel `combo_order_no` / `star_bean_order_no`。

---

## 23. common/run_artifact_util.py

开跑前删除项目根下 Allure raw 目录，避免 `temps/` 与 stray `allure-results/` 跨轮叠加。**不删** `reports/`。由 `pytest_configure` 调用；用例勿调。

导入：`from common.run_artifact_util import wipe_allure_raw_dirs`

### `wipe_allure_raw_dirs(root) -> list`

按 `root`（`config.rootpath`）删除 `temps/`、`allure-results/`（`ignore_errors`）。返回实际动手的目录名；缺目录返回 `[]`。


