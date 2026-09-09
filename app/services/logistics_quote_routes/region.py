"""收发地归一化：把省/市/区县文本转成用于线路匹配的规范短名。

报价表与买家消息里的地名写法不统一（"江西省"/"江西"、"北京市"/"北京"），
匹配前必须统一到同一形态；规范名同时用于导入入库和查询，两侧规则一致。
"""

from __future__ import annotations

import re
import unicodedata

# 后缀按长度优先剥离；自治区全称包含民族名，必须先于"自治区"剥离。
_REGION_SUFFIXES: tuple[str, ...] = (
    "特别行政区",
    "维吾尔自治区",
    "壮族自治区",
    "回族自治区",
    "自治区",
    "自治州",
    "省",
    "市",
    "地区",
    "盟",
)

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_region(value: str | None) -> str:
    """把地名文本归一化为规范短名；无法识别时返回空字符串。"""
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = _WHITESPACE_RE.sub("", text).strip()
    if not text:
        return ""
    for suffix in _REGION_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


def split_region_text(value: str | None) -> tuple[str, str]:
    """把一段收发地文本拆成（省, 市）。

    规则：
    - 命中规范省名（含省/市后缀）开头时按（省, 其余部分）拆分；
    - 其余情况整体按市处理，省留空，由线路库反查省份。
    """
    text = _WHITESPACE_RE.sub("", unicodedata.normalize("NFKC", str(value or ""))).strip()
    if not text:
        return "", ""
    # 直辖市既是省级行政区，也是市级线路的城市名。
    for municipality in ("北京", "上海", "天津", "重庆"):
        if text.startswith(municipality):
            return municipality, municipality
    for province in PROVINCE_NAMES:
        if normalize_region(text) == province:
            return province, ""
        prefixes = [f"{province}{suffix}" for suffix in _REGION_SUFFIXES] + [province]
        for prefix in prefixes:
            if text.startswith(prefix) and len(text) > len(prefix):
                return province, _city_text(text[len(prefix):])
    return "", _city_text(text)


def _city_text(text: str) -> str:
    # 市后详细地址不参与省市线路匹配；未出现市级标记时保留原名供反查。
    city = text.split("市", 1)[0] if "市" in text else text
    return normalize_region(city)


# 34 个省级行政区规范名（含港澳台），用于地址文本的省市拆分。
PROVINCE_NAMES: tuple[str, ...] = (
    "北京", "上海", "天津", "重庆",
    "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东",
    "河南", "湖北", "湖南", "广东", "广西", "海南",
    "四川", "贵州", "云南", "西藏", "陕西", "甘肃",
    "青海", "宁夏", "新疆", "香港", "澳门", "台湾",
)


def is_known_province(value: str | None) -> bool:
    """判断归一化后的文本是否为规范省名。"""
    return normalize_region(value) in PROVINCE_NAMES
