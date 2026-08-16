"""
MCP Geocode 地理编码服务模块
提供地址↔坐标转换、IP 定位、距离计算工具
使用免费 OpenStreetMap Nominatim API
"""

import math
import time
import urllib.parse

import requests as _requests
from flask import jsonify, request

from . import tool_registry

# ============================================================
# 工具定义
# ============================================================
GEOCODE_DEF = {
    "name": "geocode_address",
    "description": (
        "将地址转换为经纬度坐标（正向地理编码）。"
        "支持全球地址，使用 OpenStreetMap 免费服务。"
        "当用户询问某地点坐标、查找地址位置时使用。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "address": {"type": "string", "description": "地址，如 '北京市天安门'、'1600 Amphitheatre Parkway, Mountain View'"},
        },
        "required": ["address"],
    },
}

REVERSE_GEOCODE_DEF = {
    "name": "reverse_geocode",
    "description": "将经纬度坐标转换为地址（反向地理编码）。",
    "parameters": {
        "type": "object",
        "properties": {
            "lat": {"type": "number", "description": "纬度（-90 到 90）"},
            "lon": {"type": "number", "description": "经度（-180 到 180）"},
        },
        "required": ["lat", "lon"],
    },
}

IP_GEOLOCATION_DEF = {
    "name": "ip_geolocation",
    "description": "查询 IP 地址的归属地信息（国家、城市、ISP）。",
    "parameters": {
        "type": "object",
        "properties": {
            "ip": {"type": "string", "description": "IP 地址，不填则查询当前 IP", "default": ""},
        },
        "required": [],
    },
}

DISTANCE_DEF = {
    "name": "distance_calc",
    "description": "计算两个地点之间的距离（直线距离）。",
    "parameters": {
        "type": "object",
        "properties": {
            "place_a": {"type": "string", "description": "地点 A 的地址或坐标 'lat,lon'"},
            "place_b": {"type": "string", "description": "地点 B 的地址或坐标 'lat,lon'"},
        },
        "required": ["place_a", "place_b"],
    },
}


# ============================================================
# 执行器
# ============================================================
NOMINATIM_URL = "https://nominatim.openstreetmap.org"
HEADERS = {"User-Agent": "MCP-Geocode-Tool/1.0"}


def _exec_geocode(args: dict) -> str:
    address = (args.get("address") or "").strip()
    if not address:
        return "错误: address 不能为空"

    params = {"q": address, "format": "json", "limit": 3, "addressdetails": 1}
    try:
        resp = _requests.get(f"{NOMINATIM_URL}/search", params=params, headers=HEADERS, timeout=10)
        data = resp.json()
        if not data:
            return f"❌ 未找到地址 '{address}'。"

        lines = [f"📍 地理编码: {address}"]
        for i, r in enumerate(data, 1):
            lat, lon = r["lat"], r["lon"]
            display = r.get("display_name", "未知")
            lines.append(f"\n  [{i}] {display[:120]}")
            lines.append(f"      坐标: {lat}, {lon}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 地理编码失败: {str(e)}"


def _exec_reverse_geocode(args: dict) -> str:
    lat = float(args.get("lat", 0))
    lon = float(args.get("lon", 0))

    params = {"lat": lat, "lon": lon, "format": "json", "addressdetails": 1}
    try:
        resp = _requests.get(f"{NOMINATIM_URL}/reverse", params=params, headers=HEADERS, timeout=10)
        data = resp.json()
        if not data or "display_name" not in data:
            return f"❌ 未找到坐标 ({lat}, {lon}) 对应的地址。"

        addr = data.get("address", {})
        return (
            f"📍 反向地理编码 ({lat}, {lon}):\n"
            f"🏠 {data.get('display_name', '未知')[:200]}\n"
            f"🏙️ {addr.get('city', addr.get('town', addr.get('village', '未知')))}"
            f" / {addr.get('state', '')} / {addr.get('country', '')}"
        )
    except Exception as e:
        return f"❌ 反向地理编码失败: {str(e)}"


def _exec_ip_geolocation(args: dict) -> str:
    ip = (args.get("ip") or "").strip()

    url = f"http://ip-api.com/json/{ip}" if ip else "http://ip-api.com/json/"
    try:
        resp = _requests.get(url, timeout=5)
        data = resp.json()
        if data.get("status") != "success":
            return f"❌ IP 查询失败: {data.get('message', '未知错误')}"

        return (
            f"🌍 IP 定位: {data.get('query', '?')}\n"
            f"🏳️ 国家: {data.get('country', '?')} ({data.get('countryCode', '?')})\n"
            f"🏙️ 城市: {data.get('city', '?')}\n"
            f"📍 坐标: {data.get('lat', '?')}, {data.get('lon', '?')}\n"
            f"🏢 ISP: {data.get('isp', '?')}\n"
            f"⏱️ 时区: {data.get('timezone', '?')}"
        )
    except Exception as e:
        return f"❌ IP 查询失败: {str(e)}"


def _parse_location(place: str) -> tuple | None:
    """解析地点：地址文本或 lat,lon"""
    parts = place.split(",")
    if len(parts) == 2:
        try:
            return float(parts[0].strip()), float(parts[1].strip())
        except ValueError:
            pass
    # 地理编码
    params = {"q": place, "format": "json", "limit": 1}
    try:
        resp = _requests.get(f"{NOMINATIM_URL}/search", params=params, headers=HEADERS, timeout=5)
        data = resp.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass
    return None


def _haversine(lat1, lon1, lat2, lon2) -> float:
    """计算两点间球面距离（公里）"""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _exec_distance(args: dict) -> str:
    a = (args.get("place_a") or "").strip()
    b = (args.get("place_b") or "").strip()
    if not a or not b:
        return "错误: place_a 和 place_b 不能为空"

    loc_a = _parse_location(a)
    loc_b = _parse_location(b)
    if not loc_a:
        return f"❌ 无法解析地点 A: {a}"
    if not loc_b:
        return f"❌ 无法解析地点 B: {b}"

    km = _haversine(*loc_a, *loc_b)
    mi = km * 0.621371

    return (
        f"📏 距离: {a} ↔ {b}\n"
        f"📍 A: ({loc_a[0]:.4f}, {loc_a[1]:.4f})\n"
        f"📍 B: ({loc_b[0]:.4f}, {loc_b[1]:.4f})\n"
        f"➡️ 直线距离: {km:.2f} km ({mi:.2f} mi)"
    )


_tool_list = [
    (GEOCODE_DEF, _exec_geocode),
    (REVERSE_GEOCODE_DEF, _exec_reverse_geocode),
    (IP_GEOLOCATION_DEF, _exec_ip_geolocation),
    (DISTANCE_DEF, _exec_distance),
]

for tool_def, executor in _tool_list:
    tool_registry.register(tool_def["name"], tool_def, executor)


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app, http_session=None):
    @app.route("/api/geocode/test-connection", methods=["POST"])
    def geocode_test_connection():
        """测试地理编码服务可用性"""
        results = {}

        # Nominatim
        try:
            resp = _requests.get(f"{NOMINATIM_URL}/search",
                params={"q": "Beijing", "format": "json", "limit": 1},
                headers=HEADERS, timeout=8)
            results["nominatim"] = "可用" if resp.status_code == 200 else f"HTTP {resp.status_code}"
        except Exception as e:
            results["nominatim"] = f"不可用 ({e})"

        # IP-API
        try:
            resp = _requests.get("http://ip-api.com/json/", timeout=5)
            results["ip_api"] = "可用" if resp.status_code == 200 else f"HTTP {resp.status_code}"
        except Exception as e:
            results["ip_api"] = f"不可用 ({e})"

        return jsonify({
            "success": any(v == "可用" for v in results.values()),
            "message": "地理编码服务测试完成",
            "services": results,
        })
