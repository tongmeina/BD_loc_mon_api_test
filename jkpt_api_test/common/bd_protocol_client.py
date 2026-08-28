# common/bd_protocol_client.py
"""北斗协议客户端：覆盖 92/93/A6/13/14/A4/AA/15/EE/E1/94 共 11 种协议

测试用例只需注入 bd_client + bd_test_terminal 两个 fixture：
    bd_client.send_alarm_13(from_addr=bd_test_terminal)

所有变量（坐标 HEX、时间 HEX、xor、phone HEX 等）由内部自动计算，
未传入坐标时自动从中心点 (113.466203, 23.170439) 半径 100m 内随机生成。
"""
import time
from typing import List, Optional, Tuple

from common.protocol_codec import (
    DEFAULT_PHONE,
    ProtocolCodec,
    resolve_phone_hex,
)
from common.protocol_transport import BDProtocolTransport
from common.protocol_types import ProtocolSendResult

# A6 / AA 协议 content 中的固定 HEX 段（来源：监控平台.jmx）
_A6_FIXED_TAIL = (
    "0454CF920FD5B384C75F68BCEC8A4A46E6D2D3534F3D194A6BCC31C7FCC59F3D"
    "F5649B461ABD615B4B2DADB6E86A7FFEF927B07FF687279E78E6D218810456462"
    "794509AA1E700E544A402855453AD6677BDA8A0C29F3137B4C1C96060D3ECA0AC"
    "F852E45660A0124F463D35D96253F9DC92116BCEED534E39861A3A0BD586EA21"
    "DAA251454841078951AD5293BE305399CCC0DC82EA36DBA0FA67CC4D9613DE73"
    "CF6D5B69A5613456696DD34CC15E0645D03767626F52BD4A934D0663A82030C2"
    "382DB8F418EA4B93451461A38D36DA68A38D7FD2538E2F10BDFA2A"
)

# AA 协议固定头（不含 timestamp） + 6 段图片数据片段
_AA_HEADER_PREFIX = "AA000690259E"  # 后接 hex_timestamp_up
_AA_IMAGE_CHUNKS: List[str] = [
    "00000106000000000C6A5020200D0A870A00000014667479706A703220000000006A7032200000002D6A703268000000166968647200000281000001E00003070700000000000F636F6C7201000000000010000003AF6A703263FF4FFF51002F0000000001E0000002810000000000000000000001E00000028100000000000000000003070101070101070101FF52000C00000001010504040001FF5C00134040484850484850484850484850484850FF640025000143726561746564206279204F70656E4A50454720766572",
    "000001060173696F6E20322E352E30FF90000A0000000003280001FF93DF4688874024364A549C098A472414757C1971E19858F34E4B8A8FDB86E49BB3B227E3A7CB508C51B3F9CCDDDFE9360B640C3306EAFA0AD6961441768433ED6D516299D0A3E169796D12FD1B4ED40F17FCC366D0BB89CC5217589146A6EA8A02A0281F1D40B9B2F3B2D5A6C4C7BC4054599D5822A9AD26FC84504C54633213D8703FE8F2DA8E7FB1B421DFC7C3A080062FD5E0FA5D18143D0E01511FB4DF5310503DD39337F71656F4A8E2C98DA12B92",
    "00000106026A3B6EC3CAB3316D80A88B11321B83ACCF7E8286C7A6E5F9237C29C6113D3157C79D08DFDDE0FA1E714BC3519847818B11D47964168DA9EEABE6FB5A9DD006C7C94C8F928D1F23104A30319E7AB1BA72C3EC6D2269E4F31176F9B5374D77F470A82FE739DA78B93EDE7043F0AA306F13CD836DBBB3835B6DA165C34514BBD8111908BE73AFF4AC43CD22AB6A2637E3E5DF65B11116A3F541E792F62B214AD951794EC6B239AFB10EE8E03368DD0B40464AB35F9A6E4C61A7FDFF7D820C574797C415E7E795165543",
    "00000106039C5FF6B84FF71B92B11238BB36C58B7831F48A051BC176F423A77637F3230E06AC92CAC277D081D35055503E816280A7C31CA6C206739ED4BBE5548D67FC3C4DC25B25A1C30015FF40AA2A1980C7C3B2CF92DD1F0340CAB10E2E099DC2D3323A35A0925B2386714A7BFD0997B1C47F3E6612846FA16EA86EF273C67387F7CE2A632A2E83D15E9C440848D4D58F3D22F888554AD81774B5A6602F32DB7A1F4061B28AA10F983B5BA67ACAAA84BD2E24A9E31744BA2BB28F5C04F886CA92CDCE911299FC8F98C7C493",
    "0000010604D376D2E81DD43B85E2A528947FBD61DE1FB29B46227EBD3C9D587BAFBCB5C9E8E914603BD13DC99E213730FB71A07784073ECAC1D1F9E0C7724D25B34530BA86A152CBEAA0DA06D1950A5BC983AABF74DB6C31CD92A99E9069067557EC1BEC3394CA717D3CAF520942F60598130249E29F27BAB51CEA0FB867C2518080E7E0A2B171D4FC4E3C40F1B8649A89FEA47450C3EB9C7A6271B51185455F7D20118B3DBB18719A1320CB105CE1C568A188E10E7FD6F1D72B155D96AEBA3F19B4DB593DCA8AEA5BD991687B",
    "00000106055DAFF16F0D66F3A1A55F8080808080808080FFD9",
]


def _ensure_lonlat(
    lon: Optional[float],
    lat: Optional[float],
) -> Tuple[float, float]:
    """坐标缺省自动从中心点半径 100m 随机"""
    if lon is None or lat is None:
        return ProtocolCodec.random_point()
    return (lon, lat)


def _ensure_points(
    points: Optional[List[Tuple[float, float]]],
    count: int,
) -> Tuple[List[Tuple[float, float]], int]:
    """轨迹点缺省自动随机生成 count 个，返回 (points, angle_deg)"""
    if points is None:
        return ProtocolCodec.random_trajectory(count=count)
    if len(points) < count:
        raise ValueError(f"points 数量不足，需要 {count}，实际 {len(points)}")
    return points[:count], 0


class BDProtocolClient:
    """北斗协议客户端，覆盖 11 种 content 模板。

    所有 send_xxx 方法仅需 from_addr，其余参数皆可选；不传时自动生成业务数据。
    """

    def __init__(
        self,
        transport: BDProtocolTransport,
        default_phone: str = DEFAULT_PHONE,
    ):
        self.transport = transport
        self.default_phone = default_phone

    # ============================================================
    # 0x92 - 短文本（无位置）
    # ============================================================
    @staticmethod
    def build_text_92_content(hex_ts_up: str) -> str:
        # 来源 JMX：92000690259E${hexTimestamp_up}C2E9B7B3...CEBBD6C3
        return f"92000690259E{hex_ts_up}C2E9B7B3B8F7CEBBB6D3D3D1B1A8D2BBCFC2D7D4BCBAB5C4CEBBD6C3"

    def send_text_92(
        self,
        from_addr: str,
        case_name: str = "协议-92短文本无位置",
    ) -> ProtocolSendResult:
        content = self.build_text_92_content(ProtocolCodec.hex_timestamp_up())
        return self.transport.send_bd_content(
            content_hex=content, from_addr=from_addr, case_name=case_name
        )

    # ============================================================
    # 0x93 - 短文本（有位置，INT 坐标）
    # ============================================================
    @staticmethod
    def build_text_93_content(hex_ts_up: str, lon_hex: str, lat_hex: str) -> str:
        # 来源：93000690259E${hexTimestamp_up}${loc1_hex_lon}${loc1_hex_lat}0017...
        return (
            f"93000690259E{hex_ts_up}{lon_hex}{lat_hex}"
            f"0017C2E9B7B3B8F7CEBBB6D3D3D1B1A8D2BBCFC2D7D4BCBAB5C4CEBBD6C3"
        )

    def send_text_93(
        self,
        from_addr: str,
        lon: Optional[float] = None,
        lat: Optional[float] = None,
        case_name: str = "协议-93短文本有位置",
    ) -> ProtocolSendResult:
        lon_v, lat_v = _ensure_lonlat(lon, lat)
        content = self.build_text_93_content(
            hex_ts_up=ProtocolCodec.hex_timestamp_up(),
            lon_hex=ProtocolCodec.lon_int_hex(lon_v),
            lat_hex=ProtocolCodec.lat_int_hex(lat_v),
        )
        return self.transport.send_bd_content(
            content_hex=content, from_addr=from_addr, case_name=case_name
        )

    # ============================================================
    # 0xA6 - 神经语音（固定 HEX，无变量）
    # ============================================================
    @staticmethod
    def build_voice_a6_content() -> str:
        return f"A6{_A6_FIXED_TAIL}"

    def send_voice_a6(
        self,
        from_addr: str,
        case_name: str = "协议-A6神经语音",
    ) -> ProtocolSendResult:
        return self.transport.send_bd_content(
            content_hex=self.build_voice_a6_content(),
            from_addr=from_addr,
            case_name=case_name,
        )

    # ============================================================
    # 0x13 - EE 推送报警（有定位，INT 坐标 + phone）
    # ============================================================
    @staticmethod
    def build_alarm_13_content(phone_hex: str, lon_hex: str, lat_hex: str) -> str:
        return f"1300{phone_hex}{lon_hex}{lat_hex}0024000001CED2C3D4C2B7C1CBA3ACC7EBC7F3B0EFD6FAA1A3"

    def send_alarm_13(
        self,
        from_addr: str,
        lon: Optional[float] = None,
        lat: Optional[float] = None,
        phone: Optional[str] = None,
        case_name: str = "协议-13报警",
    ) -> ProtocolSendResult:
        lon_v, lat_v = _ensure_lonlat(lon, lat)
        phone_hex = resolve_phone_hex(phone, default_phone=self.default_phone)
        content = self.build_alarm_13_content(
            phone_hex=phone_hex,
            lon_hex=ProtocolCodec.lon_int_hex(lon_v),
            lat_hex=ProtocolCodec.lat_int_hex(lat_v),
        )
        return self.transport.send_bd_content(
            content_hex=content, from_addr=from_addr, case_name=case_name
        )

    def send_alarm_13_batch(
        self,
        from_addrs: List[str],
        lon: Optional[float] = None,
        lat: Optional[float] = None,
        phone: Optional[str] = None,
        case_name: str = "协议-13报警-批量",
    ) -> ProtocolSendResult:
        """一次 HTTP 请求，向多个不同卡号发送 13 报警"""
        lon_v, lat_v = _ensure_lonlat(lon, lat)
        phone_hex = resolve_phone_hex(phone, default_phone=self.default_phone)
        content = self.build_alarm_13_content(
            phone_hex=phone_hex,
            lon_hex=ProtocolCodec.lon_int_hex(lon_v),
            lat_hex=ProtocolCodec.lat_int_hex(lat_v),
        )
        return self.transport.send_bd_content_batch(
            content_hexes=[content] * len(from_addrs),
            from_addrs=from_addrs,
            case_name=case_name,
        )

    # ============================================================
    # 0x14 - 报平安（有定位，INT 坐标 + phone）
    # ============================================================
    @staticmethod
    def build_safe_14_content(phone_hex: str, lon_hex: str, lat_hex: str) -> str:
        return f"140000{phone_hex}{lon_hex}{lat_hex}0034CED2D2D1C6BDB0B2B5BDB4EFA3ACC7EBB7C5D0C4A3A1"

    def send_safe_14(
        self,
        from_addr: str,
        lon: Optional[float] = None,
        lat: Optional[float] = None,
        phone: Optional[str] = None,
        case_name: str = "协议-14报平安",
    ) -> ProtocolSendResult:
        lon_v, lat_v = _ensure_lonlat(lon, lat)
        phone_hex = resolve_phone_hex(phone, default_phone=self.default_phone)
        content = self.build_safe_14_content(
            phone_hex=phone_hex,
            lon_hex=ProtocolCodec.lon_int_hex(lon_v),
            lat_hex=ProtocolCodec.lat_int_hex(lat_v),
        )
        return self.transport.send_bd_content(
            content_hex=content, from_addr=from_addr, case_name=case_name
        )

    # ============================================================
    # 0xA4 - 推送定位（5 点 DMS 轨迹 + 方向角 + xor）
    # ============================================================
    def build_location_a4_content(
        self,
        dt_hex: dict,
        lon_dms_hexes: List[str],
        lat_dms_hexes: List[str],
        angle_hexes: List[str],
    ) -> str:
        # 头：00A4 ${yy}${mm}${dd}${hh}${mi}${ss} 0005 0545
        head = f"00A4{dt_hex['yy']}{dt_hex['mm']}{dt_hex['dd']}{dt_hex['hh']}{dt_hex['mi']}{dt_hex['ss']}00050545"
        # JMX 中各点段间隔参数（前缀分隔）：
        #  loc5: 0005 ${angle1} 01
        #  loc6: 002C ${angle2} 01
        #  loc7: 001C ${angle3} 01
        #  loc8: 001C ${angle4} 01
        #  loc9: 003A ${angle5} 01
        prefixes = ["0005", "002C", "001C", "001C", "003A"]
        body_parts: List[str] = []
        for i in range(5):
            body_parts.append(
                f"{lon_dms_hexes[i]}4E{lat_dms_hexes[i]}{prefixes[i]}{angle_hexes[i]}01"
            )
        # JMX 模板：head + lon[0]4Elat[0]0005 angle1 01 (45 lon[1]4Elat[1]002C angle2 01) ...
        # 实际拼接见 JMX：${loc5}4E${loc5_lat}0005${angle1}0145${loc6}...
        # 即 4 个 “45” 是相邻段间分隔
        joined = body_parts[0]
        for p in body_parts[1:]:
            joined += "45" + p

        without_xor = head + joined
        # JMX 仅对 hexData[2:24]（即 yy mm dd hh mi ss 00 05 05 45）的 22 字符做 xor
        xor_segment = without_xor[2:24]
        xor = ProtocolCodec.calc_xor(xor_segment)
        return without_xor + xor

    def send_location_a4(
        self,
        from_addr: str,
        points: Optional[List[Tuple[float, float]]] = None,
        case_name: str = "协议-A4定位轨迹",
    ) -> ProtocolSendResult:
        pts, _ = _ensure_points(points, count=5)
        # 与 JMX“随机获取方向”一致：5 个点的 angle_hex 独立随机
        import random
        angles_deg = [random.randint(0, 360) for _ in range(5)]

        dt_hex = ProtocolCodec.hex_datetime_cst()
        lon_dms = [ProtocolCodec.lon_dms_hex(p[0]) for p in pts]
        lat_dms = [ProtocolCodec.lat_dms_hex(p[1]) for p in pts]
        angle_hexes = [ProtocolCodec.angle_hex(a) for a in angles_deg]

        content = self.build_location_a4_content(
            dt_hex=dt_hex,
            lon_dms_hexes=lon_dms,
            lat_dms_hexes=lat_dms,
            angle_hexes=angle_hexes,
        )
        return self.transport.send_bd_content(
            content_hex=content, from_addr=from_addr, case_name=case_name
        )

    # ============================================================
    # 0xAA - 图片（6 个分包，每包独立 POST）
    # ============================================================
    def send_image_aa(
        self,
        from_addr: str,
        case_name: str = "协议-AA图片",
        interval_seconds: int = 10,
    ) -> List[ProtocolSendResult]:
        """图片分 7 包顺序发送（第1包按 JMX 重复一次），返回每包结果列表"""
        results: List[ProtocolSendResult] = []
        # 与 JMX 一致：同一轮图片分包共用一个 hexTimestamp_up
        ts = ProtocolCodec.hex_timestamp_up()
        # 与 JMX 一致：图片1发送两次，然后图片2..6
        chunks = [_AA_IMAGE_CHUNKS[0], _AA_IMAGE_CHUNKS[0], *_AA_IMAGE_CHUNKS[1:]]

        for idx, chunk in enumerate(chunks, start=1):
            content = f"{_AA_HEADER_PREFIX}{ts}{chunk}"
            print(f"  📦 {case_name} 分包 {idx}/{len(chunks)} 开始发送", flush=True)
            r = self.transport.send_bd_content(
                content_hex=content,
                from_addr=from_addr,
                case_name=f"{case_name}-分包{idx}",
                timeout=15,
            )
            results.append(r)
            print(
                f"  📦 {case_name} 分包 {idx}/{len(chunks)} 完成: "
                f"status={r.status_code}, code={r.code}",
                flush=True,
            )
            if interval_seconds > 0 and idx < len(chunks):
                time.sleep(interval_seconds)
        return results

    # ============================================================
    # 0x15 - 多点定位（5 点 INT 坐标 + 各自时间戳 delta）
    # ============================================================
    def build_location_15_content(
        self,
        lon_int_hexes: List[str],
        lat_int_hexes: List[str],
        ts_hexes: List[str],
    ) -> str:
        # 头：1500 0000 0000 0505
        head = "1500000000000505"
        # 各点段：${lon_int}${lat_int}0022${ts}
        # JMX 中各段长度字段为：0022 0022 0020 0021 0021，依次对应 5 段
        len_fields = ["0022", "0022", "0020", "0021", "0021"]
        # JMX 中时间使用 hexMin5..hexMin1 顺序（最早到最近）
        body = ""
        for i in range(5):
            body += f"{lon_int_hexes[i]}{lat_int_hexes[i]}{len_fields[i]}{ts_hexes[i]}"
        return head + body

    def send_location_15(
        self,
        from_addr: str,
        points: Optional[List[Tuple[float, float]]] = None,
        case_name: str = "协议-15多点定位",
    ) -> ProtocolSendResult:
        pts, _ = _ensure_points(points, count=5)
        # 时间戳：JMX 用 hexMin5..hexMin1 = [now-25s, now-20s, now-15s, now-10s, now-5s]
        ts_list = ProtocolCodec.hex_ts_deltas(count=5, step_sec=5)
        # ts_list[0]=最近(now-5s)，ts_list[4]=最早(now-25s)
        # JMX 顺序为 hexMin5,hexMin4,hexMin3,hexMin2,hexMin1 → 即从最早到最近
        ts_hexes = list(reversed(ts_list))

        lon_hexes = [ProtocolCodec.lon_int_hex(p[0]) for p in pts]
        lat_hexes = [ProtocolCodec.lat_int_hex(p[1]) for p in pts]

        content = self.build_location_15_content(
            lon_int_hexes=lon_hexes,
            lat_int_hexes=lat_hexes,
            ts_hexes=ts_hexes,
        )
        return self.transport.send_bd_content(
            content_hex=content, from_addr=from_addr, case_name=case_name
        )

    # ============================================================
    # 0xEE - 报警（北京时间 + DMS 坐标）
    # ============================================================
    @staticmethod
    def build_alarm_ee_content(dt_hex: dict, lon_dms: str, lat_dms: str) -> str:
        # 来源 JMX：01EE${hexyear}${hexMonth}${hexday}${hexhour}${hexminute}${hexsecond}45${loc17_lon_dms}4E${loc17_lat_dms}0012011A001741AF
        return (
            f"01EE{dt_hex['yy']}{dt_hex['mm']}{dt_hex['dd']}"
            f"{dt_hex['hh']}{dt_hex['mi']}{dt_hex['ss']}"
            f"45{lon_dms}4E{lat_dms}0012011A001741AF"
        )

    def send_alarm_ee(
        self,
        from_addr: str,
        lon: Optional[float] = None,
        lat: Optional[float] = None,
        case_name: str = "协议-EE报警",
    ) -> ProtocolSendResult:
        lon_v, lat_v = _ensure_lonlat(lon, lat)
        content = self.build_alarm_ee_content(
            dt_hex=ProtocolCodec.hex_datetime_cst(),
            lon_dms=ProtocolCodec.lon_dms_hex(lon_v),
            lat_dms=ProtocolCodec.lat_dms_hex(lat_v),
        )
        return self.transport.send_bd_content(
            content_hex=content, from_addr=from_addr, case_name=case_name
        )

    # ============================================================
    # 0xE1 - 报平安（北京时间 + DMS 坐标）
    # ============================================================
    @staticmethod
    def build_safe_e1_content(dt_hex: dict, lon_dms: str, lat_dms: str) -> str:
        # 来源 JMX：01E1${hexhour}${hexminute}${hexsecond}00${loc16_lon_dms}${loc16_lat_dms}00160000CED2D2D1C6BDB0B2A3A1
        return (
            f"01E1{dt_hex['hh']}{dt_hex['mi']}{dt_hex['ss']}00"
            f"{lon_dms}{lat_dms}00160000CED2D2D1C6BDB0B2A3A1"
        )

    def send_safe_e1(
        self,
        from_addr: str,
        lon: Optional[float] = None,
        lat: Optional[float] = None,
        case_name: str = "协议-E1报平安",
    ) -> ProtocolSendResult:
        lon_v, lat_v = _ensure_lonlat(lon, lat)
        content = self.build_safe_e1_content(
            dt_hex=ProtocolCodec.hex_datetime_cst(),
            lon_dms=ProtocolCodec.lon_dms_hex(lon_v),
            lat_dms=ProtocolCodec.lat_dms_hex(lat_v),
        )
        return self.transport.send_bd_content(
            content_hex=content, from_addr=from_addr, case_name=case_name
        )

    # ============================================================
    # 0x94 - 高级短信（phone + 时间戳）
    # ============================================================
    @staticmethod
    def build_sms_94_content(phone_hex: str, hex_ts_up: str) -> str:
        # 来源 JMX：94${phone}${hexTimestamp_up}B8DFBCB6B6CCD0C5
        return f"94{phone_hex}{hex_ts_up}B8DFBCB6B6CCD0C5"

    def send_sms_94(
        self,
        from_addr: str,
        phone: Optional[str] = None,
        case_name: str = "协议-94高级短信",
    ) -> ProtocolSendResult:
        phone_hex = resolve_phone_hex(phone, default_phone=self.default_phone)
        content = self.build_sms_94_content(
            phone_hex=phone_hex,
            hex_ts_up=ProtocolCodec.hex_timestamp_up(),
        )
        return self.transport.send_bd_content(
            content_hex=content, from_addr=from_addr, case_name=case_name
        )

    # ============================================================
    # 工具：解析 phone 入参
    # ============================================================
    def resolve_phone_hex(self, phone: Optional[str]) -> str:
        return resolve_phone_hex(phone=phone, default_phone=self.default_phone)
