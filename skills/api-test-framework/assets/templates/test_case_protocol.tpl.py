"""
test_xxx_protocol.tpl.py — 北斗协议用例模板（jkpt 协议层）
从 api-test-framework Skill 生成

适用场景：
  - 需要向后端发送二进制协议（92/93/A6/13/14/A4/AA/15/EE/E1/94），
    验证服务侧解码、入库、与 HTTP 接口的联动。

依赖：
  - common/bd_protocol_client.py（BDProtocolClient + 11 个 send_*）
  - common/protocol_*：transport / codec / types
  - conftest.py 提供 bd_client、bd_test_terminal 两个 session fixture

约定：
  - 仅注入 bd_client + bd_test_terminal，**不要**注入 auth_headers
  - 协议返回 ProtocolSendResult；统一用 .success 断言
  - 坐标 / 手机号 / 时间戳缺省时由 codec 自动生成，仅测试边界场景才传入
  - 单接口文件允许一类到底（与 SKILL 四层对齐的豁免一致）
"""

import pytest

from common.yaml_util import read_yaml


class TestXxxProtocol:
    """
    XXX 协议测试

    数据来源（可选）: yaml/test_xxx_protocol.yaml，顶层 key 如 protocol_alarm_cases
    """

    # ----------- 方式 A：无数据驱动（最小用例） -----------
    def test_send_alarm_13(self, bd_client, bd_test_terminal):
        result = bd_client.send_alarm_13(from_addr=bd_test_terminal)
        assert result.success, (
            f"协议 0x13 发送失败: status={result.status_code}, "
            f"code={result.code}, msg={result.msg}"
        )

    def test_send_voice_a6(self, bd_client, bd_test_terminal):
        result = bd_client.send_voice_a6(from_addr=bd_test_terminal)
        assert result.success, f"协议 0xA6 失败: code={result.code}, msg={result.msg}"

    def test_send_location_a4(self, bd_client, bd_test_terminal):
        # 不传 points → codec 自动生成中心点附近的 5 点轨迹
        result = bd_client.send_location_a4(from_addr=bd_test_terminal)
        assert result.success, f"协议 0xA4 失败: code={result.code}, msg={result.msg}"

    def test_send_image_aa(self, bd_client, bd_test_terminal):
        # 图片协议返回 list[ProtocolSendResult]
        results = bd_client.send_image_aa(from_addr=bd_test_terminal, interval_seconds=0)
        for idx, r in enumerate(results, start=1):
            assert r.success, f"分包 {idx} 失败: code={r.code}, msg={r.msg}"

    # ----------- 方式 B：YAML 数据驱动 -----------
    # YAML 顶层 key（与文件 yaml/test_xxx_protocol.yaml 对应），示例：
    #
    # protocol_alarm_cases:
    #   - name: "13报警-正向-默认坐标"
    #     protocol: "13"
    #     expected:
    #       code: 0
    #       msg: "成功"
    #
    #   - name: "13报警-负向-坐标越界"
    #     protocol: "13"
    #     lon: 200.0
    #     lat: 100.0
    #     expected:
    #       code: 999
    #       error_msg: "失败"
    #
    # test_data = read_yaml("./yaml/test_xxx_protocol.yaml")["protocol_alarm_cases"]
    #
    # @pytest.mark.parametrize("case", test_data)
    # def test_send_by_yaml(self, bd_client, bd_test_terminal, case):
    #     kwargs = {"from_addr": bd_test_terminal, "case_name": case["name"]}
    #     if "lon" in case and "lat" in case:
    #         kwargs.update(lon=case["lon"], lat=case["lat"])
    #     if case.get("phone"):
    #         kwargs["phone"] = case["phone"]
    #
    #     result = bd_client.send_alarm_13(**kwargs)
    #
    #     assert result.success, (
    #         f"[{case['name']}] 协议发送失败: "
    #         f"status={result.status_code}, code={result.code}, msg={result.msg}"
    #     )
