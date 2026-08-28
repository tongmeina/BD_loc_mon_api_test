# conftest.py
import pytest
import time
import datetime
import logging
import json
import os
from common.requests_util import (
    BaseRequest,
    NonJsonResponseError,
    get_last_http_context,
    parse_response_json,
    sanitize_sensitive_data,
)
from common.run_artifact_util import wipe_allure_raw_dirs
from common.yaml_util import clear_yaml
from common.captcha_util import CaptchaRecognizer, generate_captcha_id
from common.logger_util import sep, key, print_request, print_response
from common.bd_protocol_client import BDProtocolClient
from common.protocol_transport import BDProtocolTransport
from common.rescue_platform_client import (
    RescuePlatformSession,
    RescueUplinkClient,
    generate_rescue_sn,
)
import jsonpath

# 修复 jsonpath API 兼容性
_jsonpath_parse = jsonpath.jsonpath

# Allure 附件
try:
    import allure
except Exception:
    allure = None

# ==================== 日志配置 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== 全局实例 ====================
http = BaseRequest()
ocr = CaptchaRecognizer()

# ==================== 配置清理行为 ====================
ENABLE_AUTO_CLEANUP = os.getenv("ENABLE_AUTO_CLEANUP", "true").lower() == "true"

JKPT_ACCOUNT = os.getenv("JKPT_ACCOUNT", "user1752216001906")
JKPT_PASSWORD = os.getenv("JKPT_PASSWORD", "4f9cb165cd6249312e5804fcf9416c5e")
JKPT_ACCOUNT_B = os.getenv("JKPT_ACCOUNT_B", "user13128251672")
JKPT_PASSWORD_B = os.getenv("JKPT_PASSWORD_B", JKPT_PASSWORD)  # 同 A 的 MD5
# GLHT_* 常量与 ENABLE_GLHT_CLEANUP 已挪进 common/cleanup/glht.py（域模块自读环境变量）

# ==================== 配置 ====================
def pytest_configure(config):
    config.base_url = os.getenv("JKPT_BASE_URL", "http://back.tdwtv2.pg8.ink")
    config.accept_language = "zh-CN"
    wiped = wipe_allure_raw_dirs(config.rootpath)
    sep(" 配置信息 ")
    key("🌐 base_url", config.base_url)
    key("🌐 Accept-Language", config.accept_language)
    if wiped:
        key("🧹 已清空 Allure raw", ", ".join(wiped))


@pytest.fixture(scope="session")
def base_url(pytestconfig):
    return pytestconfig.base_url

@pytest.fixture(scope="session")
def accept_language(pytestconfig):
    return pytestconfig.accept_language

def _login_token(base_url, account, password, label):
    """验证码 OCR + 登录，最多 5 次。失败 pytest.fail。"""
    sep(f" 🔐 认证流程 - {label} 获取Token ")
    print()
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        print(f"  ▶️  第 {attempt}/{max_attempts} 次尝试")
        captcha_id = generate_captcha_id()
        key("🔑 captchaId", captcha_id)
        captcha_url = f"{base_url}/api/monitor/captcha?captchaId={captcha_id}"
        resp = http.send_request(
            method="get", url=captcha_url, case_name=f"{label}获取验证码", log_level="none",
        )
        key("🖼️ 验证码图片", "获取成功")
        captcha_text = ocr.recognize_from_response(resp)
        key("🔤 识别结果", captcha_text)
        login_url = f"{base_url}/api/monitor/web-user/login"
        login_data = {
            "account": account, "password": password,
            "captcha": captcha_text, "captchaId": captcha_id,
        }
        print_request("POST", login_url, params=login_data)
        login_resp = http.send_request(
            method="post", url=login_url, params=login_data,
            case_name=f"{label}用户登录", log_level="none",
        )
        print_response(login_resp)
        json_data = parse_response_json(login_resp, context=f"{label}用户登录")
        code = json_data["code"]
        if code == 0:
            token = _jsonpath_parse(json_data, "$.data.token")[0]
            key("🎫 Token", f"{token[:30]}...")
            key("✅ 结果", f"{label}登录成功!")
            return token
        msg = json_data.get("msg") or "未知错误"
        key("❌ 失败原因", f"code={code}, msg={msg}")
        if attempt < max_attempts:
            print("  ⏳ 1秒后重试...")
            time.sleep(1)
    pytest.fail(f"{label}登录失败，已重试5次仍未成功")


# ==================== 认证核心：auth_token fixture ====================
@pytest.fixture(scope="session")
def auth_token(base_url):
    """A 账号 token（验证码 OCR + 重试）"""
    return _login_token(base_url, JKPT_ACCOUNT, JKPT_PASSWORD, "A")

# ==================== 认证头：auth_headers fixture ====================
@pytest.fixture(scope="session")
def auth_headers(auth_token, accept_language):
    """构造认证请求头"""
    sep(" 🔑 认证头信息 ")
    key("Authorization", f"Bearer {auth_token[:20]}...")
    key("Accept-Language", accept_language)
    return {
        "Authorization": f"{auth_token}",
        "Accept-Language": accept_language
    }


@pytest.fixture(scope="session")
def auth_token_b(base_url):
    """B 账号 token。仅批 2 注入时拉活，不影响批 1。"""
    return _login_token(base_url, JKPT_ACCOUNT_B, JKPT_PASSWORD_B, "B")


@pytest.fixture(scope="session")
def auth_headers_b(auth_token_b, accept_language):
    """B 认证头。仅 TestIg04 B 支路 / Ig11 / Ig12 注入。"""
    sep(" 🔑 B 认证头信息 ")
    key("Authorization", f"Bearer {auth_token_b[:20]}...")
    key("Accept-Language", accept_language)
    return {
        "Authorization": f"{auth_token_b}",
        "Accept-Language": accept_language,
    }

# ==================== 失败上下文钩子 ====================
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """在测试失败时自动附加请求/响应上下文到Allure"""
    outcome = yield
    report = outcome.get_result()

    # 只在测试失败时执行
    if report.when == "call" and report.failed:
        context = get_last_http_context()

        if context and allure:
            transport_allure_attached = context.get("transport_allure_attached", False)

            # BaseRequest 已附请求/响应时，失败 Hook 不再重复；仅为非标准请求兜底。
            if not transport_allure_attached and "request" in context:
                request_info = sanitize_sensitive_data(context["request"])
                allure.attach(
                    json.dumps(request_info, indent=2, ensure_ascii=False),
                    name="【失败】请求信息",
                    attachment_type=allure.attachment_type.JSON,
                )

            if not transport_allure_attached and "response" in context:
                response_info = sanitize_sensitive_data(context["response"])
                allure.attach(
                    json.dumps(response_info, indent=2, ensure_ascii=False),
                    name="【失败】响应信息",
                    attachment_type=allure.attachment_type.JSON,
                )

            if "error" in context:
                error_info = sanitize_sensitive_data(context["error"])
                allure.attach(
                    json.dumps(error_info, indent=2, ensure_ascii=False),
                    name="【失败】错误信息",
                    attachment_type=allure.attachment_type.JSON,
                )

            if hasattr(report.longrepr, "reprcrash"):
                failure_msg = sanitize_sensitive_data(
                    str(report.longrepr.reprcrash.message)
                )
                allure.attach(
                    str(failure_msg),
                    name="【失败】断言详情",
                    attachment_type=allure.attachment_type.TEXT,
                )

# ==================== 全局分组 Fixture ====================
@pytest.fixture(scope="session")
def group_fixture(base_url, auth_headers, pytestconfig):
    """自动创建分组数据，供其他测试复用"""
    sep(" 📦 创建全局分组数据 ")

    groups_url = f"{base_url}/api/monitor/groups"
    group_ids = {"one_id": None, "two_id": None, "three_id": None}
    suffix = str(int(time.time() * 1000))[-8:]

    # 1. 创建一级分组
    resp = http.send_request(
        method="post",
        url=groups_url,
        params={"groupName": f"L1_{suffix}", "parentId": 0},
        headers=auth_headers,
        case_name="创建一级分组",
        log_level="none"
    )
    try:
        json_data = parse_response_json(resp, context="group_fixture创建一级分组")
    except NonJsonResponseError as e:
        pytest.fail(str(e))
    code = json_data["code"]
    if code == 0:
        group_ids["one_id"] = _jsonpath_parse(json_data, "$.data.id")[0]
        key("一级分组ID", group_ids["one_id"])
    else:
        msg = json_data.get("msg") or "未知错误" if _jsonpath_parse(json_data, "$.msg") else "未知错误"
        pytest.fail(f"group_fixture创建一级分组失败: code={code}, msg={msg}")

    # 2. 创建二级分组
    resp = http.send_request(
        method="post",
        url=groups_url,
        params={"groupName": f"L2_{suffix}", "parentId": group_ids["one_id"]},
        headers=auth_headers,
        case_name="创建二级分组",
        log_level="none"
    )
    try:
        json_data = parse_response_json(resp, context="group_fixture创建二级分组")
    except NonJsonResponseError as e:
        pytest.fail(str(e))
    code = json_data["code"]
    if code == 0:
        group_ids["two_id"] = _jsonpath_parse(json_data, "$.data.id")[0]
        key("二级分组ID", group_ids["two_id"])
    else:
        msg = json_data.get("msg") or "未知错误" if _jsonpath_parse(json_data, "$.msg") else "未知错误"
        pytest.fail(f"group_fixture创建二级分组失败: code={code}, msg={msg}")

    # 3. 创建三级分组
    resp = http.send_request(
        method="post",
        url=groups_url,
        params={"groupName": f"L3_{suffix}", "parentId": group_ids["two_id"]},
        headers=auth_headers,
        case_name="创建三级分组",
        log_level="none"
    )
    try:
        json_data = parse_response_json(resp, context="group_fixture创建三级分组")
    except NonJsonResponseError as e:
        pytest.fail(str(e))
    code = json_data["code"]
    if code == 0:
        group_ids["three_id"] = _jsonpath_parse(json_data, "$.data.id")[0]
        key("三级分组ID", group_ids["three_id"])
    else:
        msg = json_data.get("msg") or "未知错误" if _jsonpath_parse(json_data, "$.msg") else "未知错误"
        pytest.fail(f"group_fixture创建三级分组失败: code={code}, msg={msg}")

    # 存储到 stash，供 session 结束时清理使用
    pytestconfig.stash["test_group_ids"] = group_ids.copy()

    # 副作用落地即注册（纪律 1）：三级分组建好即挂 cleaner
    # （tier 200 设备 → 300 分组，同 payload；顺序由 registry 保证）
    from common.cleanup import register_cleanup, group as _g, terminal as _t
    register_cleanup("groups", group_ids, _g.cleaner, tier=300)
    register_cleanup("terminals", group_ids, _t.cleaner, tier=200)

    return group_ids

# ==================== 设备类型 Fixture ====================
@pytest.fixture(scope="session")
def terminal_types(base_url, auth_headers):
    """获取所有设备类型枚举，session级别只调用一次"""
    sep(" 📋 获取设备类型枚举 ")
    url = f"{base_url}/api/monitor/enums/terminal-types"

    resp = http.send_request(
        method="get",
        url=url,
        headers=auth_headers,
        case_name="获取设备类型枚举",
        log_level="none"
    )

    json_data = parse_response_json(resp, context="获取设备类型枚举")
    code = json_data["code"]

    if code == 0:
        # 返回字典列表: [{"name": "PN07", "value": "PN07设备"}, ...]
        types = _jsonpath_parse(json_data, "$.data[*]")
        if types:
            key("设备类型列表", types)
            return types
        else:
            key("设备类型列表", "未获取到类型")
            return []
    else:
        msg = json_data.get("msg") or "未知错误"
        key("获取设备类型失败", f"code={code}, msg={msg}")
        return []


@pytest.fixture(scope="session")
def terminal_use_scopes(base_url, auth_headers):
    """获取所有使用范围枚举，session级别只调用一次"""
    sep(" 📋 获取使用范围枚举 ")
    url = f"{base_url}/api/monitor/enums/terminal-use-scopes"
    resp = http.send_request(
        method="get",
        url=url,
        headers=auth_headers,
        case_name="获取使用范围枚举",
        log_level="none",
    )
    json_data = parse_response_json(resp, context="获取使用范围枚举")
    code = json_data["code"]
    if code == 0:
        scopes = _jsonpath_parse(json_data, "$.data[*]")
        if scopes:
            key("使用范围列表", scopes)
            return scopes
        key("使用范围列表", "未获取到")
        return []
    msg = json_data.get("msg") or "未知错误"
    key("获取使用范围失败", f"code={code}, msg={msg}")
    return []


@pytest.fixture(scope="session")
def terminal_type_enum_cases(terminal_types, terminal_use_scopes):
    """生成 N 条枚举用例（useScope 循环选取，SN 防碰撞）"""
    if not terminal_types or not terminal_use_scopes:
        pytest.skip("terminal_types 或 terminal_use_scopes 为空，跳过枚举用例")
    base_sn = datetime.datetime.now().strftime("%Y%m%d")
    salt = str(int(time.time()) % 10000).zfill(4)
    cases = []
    for i, t in enumerate(terminal_types, start=1):
        scope = terminal_use_scopes[i % len(terminal_use_scopes)]
        sn = f"{base_sn}{salt}{i:03d}"
        cases.append({
            "sn": sn,
            "terminalType": t["name"],
            "remark": t["value"],
            "useScope": scope["name"],
        })
    key("枚举用例数量", len(cases))
    return cases


# ==================== 测试设备 Fixture ====================
TEST_TERMINALS = [
    {"sn": "20260430200104", "remark": "bd协议测试", "icon": "🛰️", "name": "BD协议测试设备"},
    {"sn": "20260430200105", "remark": "消息测试",    "icon": "📬", "name": "消息测试设备"},
]
# 添加设备必填网关字段。空 {} 现网会 999「失败」（救援棒造数踩过；枚举添加用本结构成功）。
_GATEWAY_PARAM = {
    "colorCodeId": 1,
    "gid": 0,
    "radioRcvChn": "",
    "radioSndChn": "",
    "radioPower": 0,
    "rxCss": "",
    "txCss": "",
    "width": 0,
}


def _create_terminal(base_url, auth_headers, group_id, addr, remark, icon, name):
    """在指定分组下创建设备，若已存在则复用。"""
    sep(f" {icon} 创建{name} ")
    url = f"{base_url}/api/monitor/groups/{group_id}/terminals"
    body = {
        "sn": addr,
        "remark": remark,
        "groupId": group_id,
        "terminalType": "PD18",
        "useScope": "STEAMER",
        "fromAddr": "",
        "trackColor": "#141323",
        "trackSize": 5,
        "groupCallNumber": "",
        "ipAddress": "",
        "gatewayParam": _GATEWAY_PARAM,
        "fieldJson": "",
    }
    resp = http.send_request(
        method="post", url=url, json=body, headers=auth_headers,
        case_name=f"创建{name}", log_level="none",
    )
    json_data = parse_response_json(resp, context=f"创建{name}")
    code = json_data["code"]
    if code == 0:
        key(name, f"创建成功 addr={addr}")
    else:
        msg = json_data.get("msg") or "未知错误" if _jsonpath_parse(json_data, "$.msg") else "未知错误"
        key(f"⚠️ {name}创建失败(将复用)", f"code={code}, msg={msg}")
    return addr


@pytest.fixture(scope="session")
def bd_test_terminal(base_url, auth_headers, group_fixture):
    group_id = group_fixture["one_id"]
    t = TEST_TERMINALS[0]
    return _create_terminal(base_url, auth_headers, group_id, t["sn"], t["remark"], t["icon"], t["name"])


@pytest.fixture(scope="session")
def msg_test_terminal(base_url, auth_headers, group_fixture):
    group_id = group_fixture["one_id"]
    t = TEST_TERMINALS[1]
    return _create_terminal(base_url, auth_headers, group_id, t["sn"], t["remark"], t["icon"], t["name"])


@pytest.fixture(scope="session")
def bd_client(base_url, auth_headers):
    """北斗协议客户端（11 种 content 一站式发送）"""
    transport = BDProtocolTransport(base_url=base_url, headers=auth_headers, http=http)
    return BDProtocolClient(transport=transport)


# ==================== 卫星救援终端（10304）造数 fixtures ====================
RESCUE_PLATFORM_USER = os.getenv("RESCUE_PLATFORM_USER", "admin")
RESCUE_PLATFORM_PASSWORD = os.getenv("RESCUE_PLATFORM_PASSWORD", "admin@0415")


@pytest.fixture(scope="session")
def rescue_client():
    """10304 上行模拟造数客户端（U0~U5 报文一站式发送）。

    session 级单例；结束时自动断开所有活跃模拟会话。
    语音样本注入：用例侧如需 send_speech，先调 set_speech_sample()。
    """
    sep(" 🛰️ 初始化救援平台客户端 ")
    mgr = RescuePlatformSession(RESCUE_PLATFORM_USER, RESCUE_PLATFORM_PASSWORD)
    client = RescueUplinkClient(mgr, http=http)
    key("救援平台", "120.77.17.225:10304")
    yield client
    # session 末：断开所有活跃模拟会话
    n = client.disconnect_all()
    if n:
        key("救援平台会话清理", f"断开 {n} 个会话")


def _provision_a_rescue_stick(base_url, auth_headers, group_id, label):
    """A 名下救援棒：GET mock-in-storage → POST groups/{group_id}/terminals，返回 sn。

    任一步失败 pytest.fail（不静默复用）。入库成功即登记（rescue_chat + glht 入库记录）。
    label 只影响日志/用例名，便于多根棒在报告里区分归属。
    """
    sep(f" 🛰️ 创建卫星救援终端（{label}） ")
    sn = generate_rescue_sn()
    key(f"{label} sn", sn)

    # ① 入库
    r = http.send_request(
        method="get",
        url=f"{base_url}/api/monitor/mock-in-storage",
        params={
            "Authorization": auth_headers.get("Authorization"),
            "addr": sn, "sn": sn, "name": "救援测试",
            "remark": "天通救援棒-tmn",
            "terminalType": "TT_RESCUE_STICK",
            "useScope": "STEAMER",
        },
        headers=auth_headers,
        case_name=f"{label}入库",
        log_level="none",
    )
    json_data = parse_response_json(r, context=f"{label}入库")
    code = json_data["code"]
    if code != 0:
        msg = _jsonpath_parse(json_data, "$.msg")
        pytest.fail(f"{label}入库失败: code={code}, msg={msg[0] if msg else '未知'}")
    key("入库", f"sn={sn} type=TT_RESCUE_STICK")

    # 副作用落地即注册（纪律 1）：入库成功立刻登记——
    # 即便下一步「添加设备」失败，session 末也有据可收（真正堵住 glht 入库记录泄漏，
    # 不再依赖"日期猜格式"）。
    from common.cleanup import register_cleanup, register_glht_inventory, rescue_chat as _rc
    register_cleanup(f"rescue_chat_{sn}", [sn], _rc.cleaner, tier=100)
    register_glht_inventory(sn)

    # ② 添加到 one_id 分组（复用 _create_terminal 模板，仅换类型）
    body = {
        "sn": sn, "remark": "天通救援棒-tmn", "groupId": group_id,
        "terminalType": "TT_RESCUE_STICK", "useScope": "STEAMER",
        "fromAddr": "", "trackColor": "#141323", "trackSize": 5,
        "groupCallNumber": "", "ipAddress": "",
        "gatewayParam": _GATEWAY_PARAM, "fieldJson": "",
    }
    r = http.send_request(
        method="post",
        url=f"{base_url}/api/monitor/groups/{group_id}/terminals",
        json=body, headers=auth_headers,
        case_name=f"{label}添加", log_level="none",
    )
    json_data = parse_response_json(r, context=f"{label}添加")
    code = json_data["code"]
    if code != 0:
        msg = _jsonpath_parse(json_data, "$.msg")
        pytest.fail(f"{label}添加失败: code={code}, msg={msg[0] if msg else '未知'}")
    key("添加", f"sn={sn} → group={group_id}")
    return sn


@pytest.fixture(scope="session")
def rescue_sat_terminal(base_url, auth_headers, group_fixture):
    """求救群聊模块用的 A 名下救援棒（TT_RESCUE_STICK），返回 sn（12位纯数字）。"""
    return _provision_a_rescue_stick(
        base_url, auth_headers, group_fixture["one_id"], "救援终端",
    )


@pytest.fixture(scope="session")
def rescue_sat_terminal_c(base_url, auth_headers, group_fixture):
    """对讲群消息域专用 A 名下救援棒，与 rescue_sat_terminal 隔离。

    隔离理由（intercom-message-tests.plan.md §5.1）：同一根棒同一时刻只能在一个活跃
    对讲群，且本域的 flag=1/2 上行会自动伴生 SOS 求救群——复用会与求救群聊模块抢设备。
    """
    return _provision_a_rescue_stick(
        base_url, auth_headers, group_fixture["one_id"], "A棒C",
    )


@pytest.fixture(scope="session")
def rescue_sat_terminal_c2(base_url, auth_headers, group_fixture):
    """对讲群多设备探针专用第二根 A 名下救援棒。

    与 rescue_sat_terminal_c 隔离，避免同一终端在两个活跃对讲/SOS 群之间互斥。
    """
    return _provision_a_rescue_stick(
        base_url, auth_headers, group_fixture["one_id"], "A棒C2",
    )


# B 测试分组（session 内两根棒共用一个 L1）。payload 自带 B headers——
# cleanup_test_data 的 ctx.auth_headers 是 A 的，不能拿来删 B 的组/设备。
_B_STACK = {"one_id": None, "auth_headers": None}


def _ensure_b_l1_group(base_url, auth_headers_b):
    """B token 建一级测试分组；测试棒共用。cleaner 只登记一次。"""
    if _B_STACK["one_id"]:
        return _B_STACK["one_id"]
    sep(" 📦 创建 B 测试一级分组 ")
    suffix = str(int(time.time() * 1000))[-8:]
    resp = http.send_request(
        method="post",
        url=f"{base_url}/api/monitor/groups",
        params={"groupName": f"L1_{suffix}", "parentId": 0},
        headers=auth_headers_b,
        case_name="创建B一级分组",
        log_level="none",
    )
    json_data = parse_response_json(resp, context="创建B一级分组")
    code = json_data["code"]
    if code != 0:
        msg = _jsonpath_parse(json_data, "$.msg")
        pytest.fail(f"B一级分组创建失败: code={code}, msg={msg[0] if msg else '未知'}")
    gid = _jsonpath_parse(json_data, "$.data.id")[0]
    key("B一级分组ID", gid)
    _B_STACK["one_id"] = gid
    _B_STACK["auth_headers"] = auth_headers_b
    from common.cleanup import register_cleanup, terminal as _t, group as _g
    register_cleanup("b_terminals", _B_STACK, _t.cleaner_b, tier=200)
    register_cleanup("b_groups", _B_STACK, _g.cleaner_b, tier=300)
    return gid


def _provision_b_rescue_stick(base_url, auth_headers_b, label):
    """B 名下救援棒：与 A 同款 web 链。建 L1 → mock-in-storage → POST groups/{id}/terminals。

    不走小程序 pre-bind / bind/addr（会把 webAccount 写成 useruser…）。
    收尾用 B token 删组内设备再删测试分组，不动 B 原「我的分组」。
    """
    group_id = _ensure_b_l1_group(base_url, auth_headers_b)
    sep(f" 🛰️ 创建 B 卫星救援终端 ({label}) ")
    sn = generate_rescue_sn()
    key(f"{label} sn", sn)

    r = http.send_request(
        "get", f"{base_url}/api/monitor/mock-in-storage",
        params={
            "Authorization": auth_headers_b.get("Authorization"),
            "addr": sn, "sn": sn, "name": "救援测试B",
            "remark": "天通救援棒-tmn",
            "terminalType": "TT_RESCUE_STICK",
            "useScope": "STEAMER",
        },
        headers=auth_headers_b, case_name=f"{label}入库", log_level="none",
    )
    json_data = parse_response_json(r, context=f"{label}入库")
    code = json_data["code"]
    if code != 0:
        msg = _jsonpath_parse(json_data, "$.msg")
        pytest.fail(f"{label}入库失败: code={code}, msg={msg[0] if msg else '未知'}")
    key(f"{label}入库", f"sn={sn} type=TT_RESCUE_STICK")

    from common.cleanup import register_cleanup, register_glht_inventory, rescue_chat as _rc
    register_cleanup(f"rescue_chat_{sn}", [sn], _rc.cleaner, tier=100)
    register_glht_inventory(sn)

    body = {
        "sn": sn, "remark": "天通救援棒-tmn", "groupId": group_id,
        "terminalType": "TT_RESCUE_STICK", "useScope": "STEAMER",
        "fromAddr": "", "trackColor": "#141323", "trackSize": 5,
        "groupCallNumber": "", "ipAddress": "",
        "gatewayParam": _GATEWAY_PARAM, "fieldJson": "",
    }
    r = http.send_request(
        method="post",
        url=f"{base_url}/api/monitor/groups/{group_id}/terminals",
        json=body, headers=auth_headers_b,
        case_name=f"{label}添加", log_level="none",
    )
    json_data = parse_response_json(r, context=f"{label}添加")
    code = json_data["code"]
    if code != 0:
        msg = _jsonpath_parse(json_data, "$.msg")
        pytest.fail(f"{label}添加失败: code={code}, msg={msg[0] if msg else '未知'}")
    key(f"{label}添加", f"sn={sn} → group={group_id}")
    return sn


@pytest.fixture(scope="session")
def rescue_sat_terminal_b(base_url, auth_headers_b):
    """B 名下救援棒（批 2）。仅被 B 支路 getfixturevalue / 注入时拉活。"""
    return _provision_b_rescue_stick(base_url, auth_headers_b, "B棒1")


@pytest.fixture(scope="session")
def rescue_sat_terminal_b2(base_url, auth_headers_b):
    """B 第二根棒（拒绝支路）。仅拒绝用例注入时拉活。"""
    return _provision_b_rescue_stick(base_url, auth_headers_b, "B棒2")


@pytest.fixture(scope="session")
def rescue_sat_terminal_b3(base_url, auth_headers_b):
    """B 第三根棒（关群非群主-被邀请人）。仅 Ig09 invitee 拉活，勿复用 B棒1。"""
    return _provision_b_rescue_stick(base_url, auth_headers_b, "B棒3")


@pytest.fixture(scope="session")
def rescue_sat_terminal_b4(base_url, auth_headers_b):
    """B 第四根棒（对讲群消息域双账号已读验证）。勿复用 B棒1~3：设备互斥，
    一根棒只能在一个活跃对讲群，复用会把它从对讲群 suite 的群里拽走。"""
    return _provision_b_rescue_stick(base_url, auth_headers_b, "B棒4")


@pytest.fixture(scope="session")
def emergency_chat_item(base_url, auth_headers, rescue_sat_terminal, rescue_client):
    """造一个求救群聊并提取 chatItemId。

    链：rescue_client.send_sos(sn, kind=1) → 轮询 item/page?itemName=sn（3次×2s）。
    返回 {"chatItemId": ..., "sn": ..., "itemName": ..., "status": 1}。
    失败 pytest.fail 并附 10304 会话/消息日志上下文（归因依据）。
    """
    sn = rescue_sat_terminal
    sep(" 🆘 造求救群聊 ")

    result = rescue_client.send_sos(sn, kind=1)
    if not result.success:
        # 归因：打 10304 会话记录与消息日志
        records = rescue_client.session_records(terminal_id=sn, page_size=3)
        logs = rescue_client.message_logs(terminal_id=sn, page_size=3)
        pytest.fail(
            f"SOS发送失败: code={result.code}, msg={result.message}\n"
            f"  会话记录: {records}\n  消息日志: {logs}"
        )
    key("SOS已发", f"sn={sn} sid={result.session_id}")

    # 轮询搜群（3次×2s，复用 alarm 短轮询模式）
    chat_item = None
    for i in range(3):
        time.sleep(2)
        r = http.send_request(
            method="get",
            url=f"{base_url}/api/monitor/emergency/chat/item/page",
            params={"Authorization": auth_headers.get("Authorization"),
                    "itemName": sn, "page": 1, "pageSize": 10},
            headers=auth_headers,
            case_name=f"搜群第{i+1}轮",
            log_level="none",
        )
        json_data = parse_response_json(r, context="搜群")
        items = _jsonpath_parse(json_data, "$.data.items[*]") or \
                _jsonpath_parse(json_data, "$.data.records[*]") or []
        if items:
            chat_item = items[0]
            break

    if not chat_item:
        records = rescue_client.session_records(terminal_id=sn, page_size=3)
        pytest.fail(f"搜群超时: sn={sn} 未找到群聊。10304会话记录: {records}")

    chat_id = chat_item.get("id")
    item_name = chat_item.get("itemName")
    status = chat_item.get("status")
    key("群聊创建成功", f"chatItemId={chat_id} itemName={item_name} status={status}")

    # chatItemId 写 extract.yaml 供同文件下游用例消费
    from common.yaml_util import write_yaml
    write_yaml("./extract.yaml", {
        "emergency_chat_item_id": chat_id,
        "emergency_chat_sn": sn,
        "emergency_chat_item_name": item_name,
    }, mode="append")

    return {
        "chatItemId": chat_id,
        "sn": sn,
        "itemName": item_name,
        "status": status,
        "created_at": time.time(),  # 建群时刻（U2上报时刻近似）——供上报间隔合规计算
    }


@pytest.fixture(scope="session")
def emergency_chat_voice(base_url, auth_headers, emergency_chat_item, rescue_client) -> dict:
    """主群 complete 前上行一条终端语音（U5）——TestEc10ItemComplete 正向 case 消费。

    协议约束（2026-08-17 主人定稿）：终端上报消息间隔必须 >60s。
    - 间隔合规：距建群（U2 SOS 上报）不足 VOICE_DELAY_SECONDS(默认60s) 时补足等待；
      全量跑 Ec01~Ec09 天然间隔足够，仅单跑 Ec10 时会真正等待。
    - 落库闸门：轮询 record/page 确认新增 sendType=VOICE 记录后才放行 complete
      （complete 是状态机闸门，语音必须在途完成落库，否则完结拦截行为未验证）。
    - 会话兜底：60s 空闲后 uplink-sim 会话可能超时——send_speech 失败时
      login_terminal(sn) 重建会话后重发 1 次。
    返回 {"voiceRecordId":..., "chatItemId":..., "sn":...}。
    """
    import os as _os
    sn = emergency_chat_item["sn"]
    chat_id = emergency_chat_item["chatItemId"]
    delay = float(_os.getenv("VOICE_DELAY_SECONDS", "60"))

    elapsed = time.time() - emergency_chat_item.get("created_at", 0)
    wait = delay - elapsed
    if wait > 0:
        sep(f" 🎙️ 终端语音上报间隔合规等待 {wait:.0f}s（协议约束：上报间隔>60s） ")
        time.sleep(wait)
    else:
        key("间隔合规", f"距建群已 {elapsed:.0f}s，满足 >{delay:.0f}s 约束，无需等待")

    # 上报（失败→重建会话→重发1次）
    result = rescue_client.send_speech(sn)
    if not result.success:
        key("会话兜底", f"send_speech 失败(code={result.code})，login_terminal 重建后重发")
        rescue_client.login_terminal(sn)
        result = rescue_client.send_speech(sn)
    if not result.success:
        pytest.fail(f"终端语音上报失败(含会话重建重试): code={result.code}, msg={result.message}")

    # 落库闸门：轮询 record 确认 VOICE 落库（发送成功≠落地，机制认知#1）
    voice_record = None
    for i in range(3):
        time.sleep(2)
        r = http.send_request(
            method="get",
            url=f"{base_url}/api/monitor/emergency/chat/record/page",
            params={"Authorization": auth_headers.get("Authorization"),
                    "chatItemId": chat_id, "page": 1, "pageSize": 20},
            headers=auth_headers,
            case_name=f"语音落库确认第{i+1}轮",
            log_level="none",
        )
        record_page = parse_response_json(r, context=f"语音落库确认第{i+1}轮")
        items = _jsonpath_parse(record_page, "$.data.items[*]") or []
        voice_record = next((it for it in items if it.get("sendType") == "VOICE"
                             and str(it.get("avatarInfo", {}).get("memberAccount") or "") == sn), None)
        if voice_record:
            break
    if not voice_record:
        records = rescue_client.session_records(terminal_id=sn, page_size=3)
        pytest.fail(f"终端语音未落库(3×2s轮询超时): sn={sn} chatItemId={chat_id}。"
                    f"10304会话记录: {records}")

    key("终端语音已落库", f"recordId={voice_record.get('id')}")
    return {
        "voiceRecordId": voice_record.get("id"),
        "chatItemId": chat_id,
        "sn": sn,
    }


# ==================== 对讲群消息域造数 ====================
IM_UPLINK_GAP = float(os.getenv("IM_UPLINK_GAP", "62"))


def _im_jp1(data, expr):
    found = _jsonpath_parse(data, expr)
    return found[0] if found else None


@pytest.fixture(scope="session")
def intercom_message_group(base_url, auth_headers, auth_headers_b,
                           rescue_sat_terminal_c, rescue_sat_terminal_c2,
                           rescue_sat_terminal_b4, rescue_client) -> dict:
    """对讲群「消息域」三设备造数主链（session 级，实测约 80~90s；
    plan/intercom-message-multi-device.plan.md，2026-08-24 探针实测）。

    设备分工（62s 间隔为终端级——探针实测跨设备仅 0.03s 即被接受）：
      A账号 key_sos  (A棒C):  flag=1 按键SOS → flag=10 取消SOS
      A账号 water_sos(A棒C2): flag=2 落水SOS → flag=0 心跳解除
      B账号 voice    (B棒4):  跨账号入群后发 VOICE，复用成员侧已读能力

    ① 建群（20 豆）→ register_intercom_group（tier 100）
    ② A棒C/C2 先入群并完成第一波 SOS 上行；双 TEXT 已落库后，B 仍是非成员。
    ③ 用已存在的 msg_a 分别采 B 非成员 page 与 receive/info 权限证据，再邀请 B棒4
       走 PENDING→B AGREED；这样权限证据具备“目标消息真实存在”的 required 前提。
    ④ 冷却后 A棒C2 flag0、A棒C flag10 结束双 SOS；B棒4 speech 产生 VOICE，
       复核三设备成员、A/B 两侧可见性及 VOICE 不得落入任一 SOS 记录。

    seed 一次性切换为多设备结构（devices/messagesByRole/sosGroups/snapshots/…），
    不保留 sn/sosChatItemId/sosRecords 旧字段——漏改以 KeyError 显性暴露。
    """
    from common.cleanup import register_intercom_group

    roles = {
        "key_sos": {"sn": rescue_sat_terminal_c, "account": "A"},
        "water_sos": {"sn": rescue_sat_terminal_c2, "account": "A"},
        "voice": {"sn": rescue_sat_terminal_b4, "account": "B"},
    }
    sn_a = roles["key_sos"]["sn"]
    sn_b = roles["water_sos"]["sn"]
    sn_c = roles["voice"]["sn"]
    name = f"AUTO_IM_{time.strftime('%H%M%S')}"  # 群名上限 15 字符
    timing = {"startedAt": time.monotonic()}
    sep(" 📣 对讲群消息域三设备造数 ")

    def _fail(reason, **_kwargs):
        detail = {}
        for role, info in roles.items():
            sn = info["sn"]
            detail[role] = {
                "sn": sn,
                "sessions": rescue_client.session_records(terminal_id=sn, page_size=3),
                "messages": rescue_client.message_logs(terminal_id=sn, page_size=3),
            }
        pytest.fail(f"{reason}\n  10304诊断: {detail}")

    def _msg_page():
        res = http.send_request(
            "get", f"{base_url}/api/monitor/intercom/message/page",
            params={"intercomGroupId": gid, "page": 1, "pageSize": 100},
            headers=auth_headers, case_name="消息域分页", log_level="none",
        )
        return parse_response_json(res, context="消息域分页")

    def _items():
        return _jsonpath_parse(_msg_page(), "$.data.items[*]") or []

    def _member_sns():
        res = http.send_request(
            "get", f"{base_url}/api/monitor/intercom/group/terminal/list",
            params={"intercomGroupId": gid}, headers=auth_headers,
            case_name="消息域成员列表", log_level="none",
        )
        data = parse_response_json(res, context="消息域成员列表")
        return [str(x) for x in (_jsonpath_parse(data, "$.data[*].addr") or [])]

    def _snapshot(tag):
        body = _msg_page()
        its = _jsonpath_parse(body, "$.data.items[*]") or []
        snap = {"total": _im_jp1(body, "$.data.total"), "count": len(its),
                "sendTypes": [i.get("sendType") for i in its], "items": its}
        key(f"快照-{tag}", f"total={snap['total']} {snap['sendTypes']}")
        return snap

    def _find(rows, sn, send_type, token, baseline):
        for m in rows:
            if m.get("id") in baseline:
                continue
            if str((m.get("avatarInfo") or {}).get("memberAccount")) != str(sn):
                continue
            if m.get("sendType") != send_type:
                continue
            if token and token not in str(m.get("content") or ""):
                continue
            return m
        return None

    def _wait(label, fn, rounds=10, interval=2):
        last = None
        for _ in range(rounds):
            last = fn()
            if last:
                return last
            time.sleep(interval)
        _fail(f"等待超时({label}): last={last}")

    def _sos_items(sn):
        res = http.send_request(
            "get", f"{base_url}/api/monitor/emergency/chat/item/page",
            params={"itemName": sn, "page": 1, "pageSize": 10}, headers=auth_headers,
            case_name=f"SOS伴生群查询-{sn}", log_level="none",
        )
        data = parse_response_json(res, context=f"SOS伴生群查询-{sn}")
        return _jsonpath_parse(data, "$.data.items[*]") or []

    def _send(tag, sn, kind):
        result = (rescue_client.send_speech(sn) if kind == "speech"
                  else rescue_client.send_position(sn, report_flag=kind))
        if not result.success:
            key("会话兜底", f"{tag} 失败(code={result.code})，login_terminal 重建后重发")
            rescue_client.login_terminal(sn)
            result = (rescue_client.send_speech(sn) if kind == "speech"
                      else rescue_client.send_position(sn, report_flag=kind))
        if not result.success:
            _fail(f"{tag} 上行失败: code={result.code}, msg={result.message}")
        key(f"上行-{tag}", f"sn={sn} sid={result.session_id}")
        return time.monotonic()

    def _invite(sn):
        r = http.send_request(
            "post", f"{base_url}/api/monitor/intercom/group/invitation",
            json={"intercomGroupId": gid, "addrInfos": [{"addr": sn}], "force": False},
            headers=auth_headers, case_name=f"消息域邀请-{sn}", log_level="none",
        )
        data = parse_response_json(r, context=f"消息域邀请-{sn}")
        if _im_jp1(data, "$.code") != 0:
            _fail(
                f"邀请 {sn} 失败",
                name="intercom member invitation",
                expected=0, actual=data, evidence="intercom/group/invitation",
            )

    # ① 建群
    r = http.send_request(
        "put", f"{base_url}/api/monitor/intercom/group/create",
        params={"intercomGroupName": name}, headers=auth_headers,
        case_name="消息域建群", log_level="none",
    )
    data = parse_response_json(r, context="消息域建群")
    gid = _im_jp1(data, "$.data.id")
    if _im_jp1(data, "$.code") != 0 or not gid:
        _fail(
            "消息域建群失败",
            name="intercom group creation",
            expected={"code": 0, "id": "non-empty"}, actual=data,
            evidence="intercom/group/create",
        )
    register_intercom_group(gid)
    key("消息域对讲群", f"{gid} name={name}")
    timing["groupCreated"] = time.monotonic()

    # ② 先让两台 A 设备入群；B 保持非成员，待真实消息落库后再取权限证据。
    _invite(sn_a)
    _invite(sn_b)
    members_before_b = _member_sns()
    expected_before_b = {sn_a, sn_b}
    if set(members_before_b) != expected_before_b:
        _fail(
            "B入群前成员集合不符",
            name="membership before non-member evidence",
            expected=expected_before_b, actual=set(members_before_b), evidence="group terminal/list",
        )
    timing["membershipA"] = time.monotonic()

    # ③ 第一波上行先造出可读取的消息，再采 B 非成员 page/receive-info 权限证据。
    baseline = {m.get("id") for m in _items()}
    totals = {"baseline": len(baseline)}
    sent_at = {}

    sent_at[sn_a] = _send("flag=1按键SOS", sn_a, 1)
    sent_at[sn_b] = _send("flag=2落水SOS", sn_b, 2)
    key("跨设备间隔", f"{sent_at[sn_b] - sent_at[sn_a]:.2f}s（终端级限制已探针证实）")

    msg_a = _wait("key_sos TEXT 落库", lambda: _find(
        _items(), sn_a, "TEXT", "触发SOS报警", baseline))
    msg_b = _wait("water_sos TEXT 落库", lambda: _find(
        _items(), sn_b, "TEXT", "触发落水报警", baseline))
    totals["afterSos"] = len(_items())

    sos_a = _wait("SOS-A 捕获", lambda: next(
        (x for x in _sos_items(sn_a) if x.get("status") == 1), None))
    sos_b = _wait("SOS-B 捕获", lambda: next(
        (x for x in _sos_items(sn_b) if x.get("status") == 1), None))
    key("双SOS伴生群", f"A={sos_a.get('id')} B={sos_b.get('id')}")
    timing["sosLanding"] = time.monotonic()

    # 消息存在性是权限证据的 required 前提；禁止在空群上用 code=0 冒充越权读取证据。
    if not msg_a.get("id") or not msg_b.get("id"):
        _fail(
            "非成员权限取证前消息不存在",
            name="message exists before authorization evidence",
            expected="two landed message ids", actual={"key_sos": msg_a, "water_sos": msg_b},
            evidence="message/page",
        )
    non_member_page_response = http.send_request(
        "get", f"{base_url}/api/monitor/intercom/message/page",
        params={"intercomGroupId": gid, "page": 1, "pageSize": 100},
        headers=auth_headers_b, case_name="B非成员查询消息快照", log_level="none",
    )
    non_member_body = parse_response_json(
        non_member_page_response, context="B非成员查询消息快照",
    )
    non_member_items = _jsonpath_parse(non_member_body, "$.data.items[*]") or []
    access_b_non_member_page = {
        "code": _im_jp1(non_member_body, "$.code"),
        "msg": _im_jp1(non_member_body, "$.msg"),
        "count": len(non_member_items),
        "ids": [item.get("id") for item in non_member_items],
        "evidenceMessageIds": [msg_a.get("id"), msg_b.get("id")],
    }
    non_member_receive_response = http.send_request(
        "get", f"{base_url}/api/monitor/intercom/message/receive/info",
        params={"intercomMessageId": msg_a["id"]}, headers=auth_headers_b,
        case_name="B非成员查询接收明细快照", log_level="none",
    )
    parse_response_json(non_member_receive_response, context="B非成员查询接收明细快照")
    timing["authorizationEvidence"] = time.monotonic()

    # 权限证据完成后再邀请 B棒4，保持三设备与 B 成员侧后续验证链。
    _invite(sn_c)
    notice = None
    for _ in range(10):
        res = http.send_request(
            "get", f"{base_url}/api/monitor/intercom/message/send/invitation/list",
            params={"intercomGroupId": gid, "status": "PENDING",
                    "page": 1, "pageSize": 50},
            headers=auth_headers, case_name="消息域查PENDING通知", log_level="none",
        )
        invitation_page = parse_response_json(res, context="消息域查PENDING通知")
        notice = next((item for item in (_jsonpath_parse(invitation_page, "$.data.items[*]") or [])
                       if item.get("addr") == sn_c), None)
        if notice:
            break
        time.sleep(1)
    if not notice:
        _fail(
            "B棒4 PENDING 通知未出现",
            name="B invitation notice",
            expected=sn_c, actual=notice, evidence="invitation/list",
        )
    r = http.send_request(
        "put", f"{base_url}/api/monitor/intercom/message/invitation/handler",
        params={"handlerType": "AGREED", "invitationNoticeId": notice["id"]},
        headers=auth_headers_b, case_name="消息域B同意入群", log_level="none",
    )
    data = parse_response_json(r, context="消息域B同意入群")
    if _im_jp1(data, "$.code") != 0:
        _fail(
            "B棒4 同意入群失败",
            name="B invitation accepted",
            expected=0, actual=data, evidence="invitation/handler",
        )
    members = _member_sns()
    expected = {sn_a, sn_b, sn_c}
    if set(members) != expected:
        _fail(
            "三设备成员集合不符",
            name="exact three-device membership",
            expected=expected, actual=set(members), evidence="group terminal/list",
        )
    key("入群复核", f"三设备满员 {sorted(members)}")
    timing["membership"] = time.monotonic()

    remain = max(IM_UPLINK_GAP - (time.monotonic() - sent_at[sn]) for sn in (sn_a, sn_b))
    if remain > 0:
        sep(f" ⏳ 双设备冷却钟 {remain:.0f}s ")
        time.sleep(remain)
    timing["cooldown"] = time.monotonic()

    _send("flag=0心跳", sn_b, 0)
    _send("flag=10取消SOS", sn_a, 10)

    def _closed(sn, chat_id):
        return next((x for x in _sos_items(sn)
                     if str(x.get("id")) == str(chat_id) and x.get("status") == 0), None)

    sos_a_end = _wait("SOS-A 关闭", lambda: _closed(sn_a, sos_a["id"]))
    sos_b_end = _wait("SOS-B 关闭", lambda: _closed(sn_b, sos_b["id"]))
    totals["afterClose"] = _snapshot("双SOS关闭后")["total"]
    timing["sosClosed"] = time.monotonic()

    # ④ B棒4 语音
    _send("语音", sn_c, "speech")
    msg_c = _wait("voice VOICE 落库", lambda: _find(
        _items(), sn_c, "VOICE", None, baseline))
    b_res = http.send_request(
        "get", f"{base_url}/api/monitor/intercom/message/page",
        params={"intercomGroupId": gid, "page": 1, "pageSize": 100},
        headers=auth_headers_b, case_name="B成员侧查语音", log_level="none",
    )
    b_items = _jsonpath_parse(parse_response_json(
        b_res, context="B成员侧查语音"), "$.data.items[*]") or []
    if not any(m.get("id") == msg_c.get("id") for m in b_items):
        _fail(
            "B成员侧看不到 VOICE",
            name="B member voice visibility",
            expected=msg_c.get("id"), actual=[m.get("id") for m in b_items],
            evidence="message/page E4",
        )
    totals["speech"] = _snapshot("语音后")["total"]
    final_items = _items()
    timing["voiceLanding"] = time.monotonic()
    timing["total"] = timing["voiceLanding"] - timing["startedAt"]

    # SOS 侧记录（按设备分别取证）
    def _sos_records(chat_id):
        res = http.send_request(
            "get", f"{base_url}/api/monitor/emergency/chat/record/page",
            params={"chatItemId": chat_id, "page": 1, "pageSize": 50},
            headers=auth_headers, case_name=f"SOS侧记录-{chat_id}", log_level="none",
        )
        body = parse_response_json(res, context=f"SOS侧记录-{chat_id}")
        its = _jsonpath_parse(body, "$.data.items[*]") or []
        return {
            "total": _im_jp1(body, "$.data.total"),
            "sendTypes": [i.get("sendType") for i in its],
            "chatTimes": [i.get("chatTime") for i in its],
            "items": its,
        }

    sos_groups = {
        "key_sos": {"chatItemId": sos_a["id"], "terminalSn": sn_a,
                    "statusAfterEnd": sos_a_end.get("status"),
                    "records": _sos_records(sos_a["id"])},
        "water_sos": {"chatItemId": sos_b["id"], "terminalSn": sn_b,
                      "statusAfterEnd": sos_b_end.get("status"),
                      "records": _sos_records(sos_b["id"])},
    }
    leaked_voice = [
        role for role, g in sos_groups.items()
        if any(r.get("sendType") == "VOICE" for r in g["records"]["items"])
    ]
    if leaked_voice:
        _fail(
            "VOICE 泄漏到 SOS 群",
            name="voice absent from non-target SOS groups",
            expected=[], actual=leaked_voice, evidence="emergency chat record/page E3",
        )

    for role in roles:
        roles[role]["actions"] = (["flag=1", "flag=10"] if role == "key_sos"
                                  else ["flag=2", "flag=0"] if role == "water_sos"
                                  else ["speech"])
    key("造数完成", f"对讲群 {totals['speech']} 条；耗时 {timing['total']:.0f}s；"
                    f"VOICE 仅落对讲群")
    if timing["total"] > 90:
        key("⚠️ 耗时超标(观测项)", f"{timing['total']:.0f}s > 90s 目标，分段 {timing}")

    return {
        "group": {"id": gid, "name": name, "members": members},
        "devices": roles,
        "messagesByRole": {
            "key_sos": msg_a,
            "water_sos": msg_b,
            "voice": msg_c,
        },
        "messages": final_items,
        "messageIds": [m.get("id") for m in final_items],
        "sosGroups": sos_groups,
        "totals": totals,
        "snapshots": {
            "baseline": totals["baseline"],
            "afterSos": totals["afterSos"],
            "afterClose": totals["afterClose"],
            "speech": totals["speech"],
        },
        "accessSnapshots": {
            "bNonMemberPage": access_b_non_member_page,
            "bNonMemberReceiveResponse": non_member_receive_response,
            "bNonMemberReceiveMessageId": msg_a["id"],
            "bMemberVoiceVisible": any(m.get("id") == msg_c.get("id") for m in b_items),
        },
        "timing": timing,
    }


# ==================== 自动清理 ====================
@pytest.fixture(scope="session", autouse=True)
def clear_data_per_session():
    """在 session 开始和结束时清理临时数据文件"""
    sep(" 🚀 测试开始 ")
    clear_yaml()
    yield
    sep(" 🏁 测试结束 ")


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_data(base_url, auth_headers, group_fixture, pytestconfig):
    """session 末统一清理：一行调度（清理逻辑见 common/cleanup/ 子包）。

    注册来源（副作用落地即注册）：
      group_fixture → groups(tier300) + terminals(tier200)  # A token
      rescue_sat_terminal → rescue_chat_{sn}(tier100，入库成功即注册)
      rescue_sat_terminal_b → b_terminals(200) + b_groups(300)（payload 自带 B headers）
      用例 buy → unpaid_orders(tier100，经包级入口 register_unpaid_order_no)
      4 处 mock-in-storage 入库点 → glht_inventory_{sn}(tier400) + glht_inventory_flush(tier410，
        经包级入口 register_glht_inventory，按 sn 精确查删，格式无关)
    执行序由 registry tier 保证：群/订单(100) → 设备(200) → 分组(300) → 外部系统(400/410)。
    """
    yield

    if not ENABLE_AUTO_CLEANUP:
        sep(" ⚠️  自动清理已禁用 (ENABLE_AUTO_CLEANUP=false)")
        return

    sep(" 🧹 开始清理测试数据 ")
    from common.cleanup import CleanupContext, run_session_cleanup
    ctx = CleanupContext(base_url=base_url, auth_headers=auth_headers)
    report = run_session_cleanup(ctx)  # 订单默认收走；keep_orders 参数位留待扫码场景

    # report 落盘：allure 附件 + cleanup-report.yaml 追写（泄漏可归因物证）
    try:
        import yaml
        with open("./cleanup-report.yaml", "a", encoding="utf-8") as f:
            f.write(yaml.safe_dump(
                {"session_cleanup": report}, allow_unicode=True, sort_keys=True))
        if allure:
            allure.attach(
                json.dumps(report, indent=2, ensure_ascii=False),
                name="【收尾】清理报告",
                attachment_type=allure.attachment_type.JSON,
            )
        key("清理报告", report)
    except Exception as exc:
        key("⚠️ 清理报告落盘失败", str(exc))

    sep(" 🎉 清理完成 ")
