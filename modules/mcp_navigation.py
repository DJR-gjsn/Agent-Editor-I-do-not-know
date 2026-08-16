"""
MCP Navigation 导航服务模块
整合主流地图 API: 高德/百度/Google/OpenStreetMap
提供路线规划、地点搜索、距离时间估算
"""

import math
import time
import urllib.parse

import requests as _requests
from flask import jsonify, request

from . import tool_registry

# ============================================================
# 提供商配置
# ============================================================
NAV_PROVIDERS = {
    "amap": {
        "name": "高德地图",
        "icon": "map",
        "geocode_url": "https://restapi.amap.com/v3/geocode/geo",
        "regeo_url": "https://restapi.amap.com/v3/geocode/regeo",
        "search_url": "https://restapi.amap.com/v3/place/text",
        "driving_url": "https://restapi.amap.com/v3/direction/driving",
        "walking_url": "https://restapi.amap.com/v3/direction/walking",
        "transit_url": "https://restapi.amap.com/v3/direction/transit/integrated",
        "bicycling_url": "https://restapi.amap.com/v3/direction/bicycling",
        "key_param": "key",
        "api_key_hint": "高德开放平台 Web服务 Key",
        "register_url": "https://developer.amap.com",
    },
    "baidu": {
        "name": "百度地图",
        "icon": "compass",
        "geocode_url": "https://api.map.baidu.com/geocoding/v3",
        "regeo_url": "https://api.map.baidu.com/reverse_geocoding/v3",
        "search_url": "https://api.map.baidu.com/place/v2/search",
        "driving_url": "https://api.map.baidu.com/direction/v2/driving",
        "walking_url": "https://api.map.baidu.com/direction/v2/walking",
        "transit_url": "https://api.map.baidu.com/direction/v2/transit",
        "bicycling_url": "https://api.map.baidu.com/direction/v2/riding",
        "key_param": "ak",
        "api_key_hint": "百度地图开放平台 AK",
        "register_url": "https://lbsyun.baidu.com",
    },
    "google": {
        "name": "Google Maps",
        "icon": "globe",
        "geocode_url": "https://maps.googleapis.com/maps/api/geocode/json",
        "search_url": "https://maps.googleapis.com/maps/api/place/textsearch/json",
        "driving_url": "https://maps.googleapis.com/maps/api/directions/json",
        "key_param": "key",
        "api_key_hint": "Google Maps API Key",
        "register_url": "https://console.cloud.google.com",
    },
    "osrm": {
        "name": "OpenStreetMap (OSRM)",
        "icon": "heart",
        "driving_url": "https://router.project-osrm.org/route/v1/driving",
        "walking_url": "https://router.project-osrm.org/route/v1/walking",
        "bicycling_url": "https://router.project-osrm.org/route/v1/cycling",
        "key_param": None,
        "api_key_hint": "免费，无需 API Key",
        "register_url": None,
    },
}

# 出行方式
TRAVEL_MODES = {
    "driving": "驾车",
    "walking": "步行",
    "transit": "公交/地铁",
    "bicycling": "骑行",
}

# ============================================================
# 会话配置
# ============================================================
_connections = {}


def _get_conn(session_id: str) -> dict:
    if session_id not in _connections:
        _connections[session_id] = {
            "provider": "osrm",  # 默认使用免费 OSRM，无需 API Key
            "api_key": "",
            "connected": False,
            "last_test": None,
        }
    return _connections[session_id]


# ============================================================
# 工具定义
# ============================================================
NAV_ROUTE_DEF = {
    "name": "nav_route",
    "description": (
        "规划两点之间的出行路线，返回距离、预估时间和路线步骤。"
        "支持驾车、步行、公交、骑行四种出行方式。"
        "起点和终点可以是地址文本或 'lat,lng' 坐标。"
        "使用前需在导航服务面板中选择地图提供商并配置 API Key（OSRM 免费无需 Key）。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "origin": {"type": "string", "description": "起点，地址或坐标如 '北京市朝阳区' 或 '116.397,39.908'"},
            "destination": {"type": "string", "description": "终点，地址或坐标"},
            "mode": {
                "type": "string",
                "enum": ["driving", "walking", "transit", "bicycling"],
                "description": "出行方式: driving=驾车, walking=步行, transit=公交, bicycling=骑行",
                "default": "driving",
            },
            "session_id": {"type": "string", "description": "会话 ID"},
        },
        "required": ["origin", "destination"],
    },
}

NAV_SEARCH_DEF = {
    "name": "nav_search_place",
    "description": (
        "在地图上搜索地点/POI。可以搜索餐厅、酒店、加油站、商场等。"
        "返回地点名称、地址、坐标。"
        "⚠️ 需要先切换到非 OSRM 提供商（高德/百度/Google）并配置 API Key，OSRM 不支持此功能。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词，如 '咖啡厅'、'北京西站'"},
            "city": {"type": "string", "description": "限定城市，如 '北京'、'上海'（可选）"},
            "session_id": {"type": "string", "description": "会话 ID"},
        },
        "required": ["query"],
    },
}


# ============================================================
# 辅助函数
# ============================================================
def _geocode_nav(address: str, provider: str, api_key: str) -> tuple | None:
    """根据提供商对地址进行地理编码，返回 (lat, lng)"""
    # 已经是坐标格式
    parts = address.split(",")
    if len(parts) == 2:
        try:
            lat, lng = float(parts[0].strip()), float(parts[1].strip())
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return (lat, lng)
        except ValueError:
            pass

    cfg = NAV_PROVIDERS.get(provider, {})
    if provider == "amap":
        params = {"key": api_key, "address": address, "output": "JSON"}
        try:
            resp = _requests.get(cfg["geocode_url"], params=params, timeout=8)
            data = resp.json()
            geocodes = data.get("geocodes", [])
            if geocodes:
                loc = geocodes[0].get("location", "")
                parts = loc.split(",")
                if len(parts) == 2:
                    return (float(parts[1]), float(parts[0]))
        except Exception:
            pass

    elif provider == "baidu":
        params = {"ak": api_key, "address": address, "output": "json"}
        try:
            resp = _requests.get(cfg["geocode_url"], params=params, timeout=8)
            data = resp.json()
            if data.get("status") == 0 and data.get("result"):
                loc = data["result"].get("location", {})
                return (loc.get("lat"), loc.get("lng"))
        except Exception:
            pass

    elif provider == "google":
        params = {"key": api_key, "address": address}
        try:
            resp = _requests.get(cfg["geocode_url"], params=params, timeout=8)
            data = resp.json()
            if data.get("status") == "OK" and data.get("results"):
                loc = data["results"][0]["geometry"]["location"]
                return (loc["lat"], loc["lng"])
        except Exception:
            pass

    # OSRM / fallback: 使用 Nominatim 免费地理编码
    try:
        params = {"q": address, "format": "json", "limit": 1}
        resp = _requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers={"User-Agent": "MCP-Nav/1.0"},
            timeout=8,
        )
        data = resp.json()
        if data:
            return (float(data[0]["lat"]), float(data[0]["lon"]))
    except Exception:
        pass

    return None


# ============================================================
# 路线规划
# ============================================================
def _exec_nav_route(args: dict) -> str:
    session_id = args.get("session_id", "default")
    conn = _get_conn(session_id)
    provider = conn.get("provider", "amap")
    api_key = conn.get("api_key", "")
    origin = (args.get("origin") or "").strip()
    destination = (args.get("destination") or "").strip()
    mode = args.get("mode", "driving")

    if not origin or not destination:
        return "错误: origin 和 destination 不能为空"

    cfg = NAV_PROVIDERS.get(provider)
    if not cfg:
        return f"不支持的提供商: {provider}"

    needs_key = cfg.get("key_param") is not None
    if needs_key and not api_key:
        return (
            f"导航服务未配置 API Key。\n"
            f"当前提供商: {cfg['name']}\n"
            f"请填入 {cfg['api_key_hint']}\n"
            f"注册地址: {cfg['register_url']}\n"
            f"或切换到免费的 OSRM 提供商。"
        )

    # 地理编码
    origin_coord = _geocode_nav(origin, provider, api_key)
    dest_coord = _geocode_nav(destination, provider, api_key)
    if not origin_coord:
        return f"无法解析起点: {origin}"
    if not dest_coord:
        return f"无法解析终点: {destination}"

    mode_name = TRAVEL_MODES.get(mode, mode)

    # ---- OSRM 路径 ----
    if provider == "osrm":
        url_key = {
            "driving": "driving_url",
            "walking": "walking_url",
            "bicycling": "bicycling_url",
        }.get(mode)
        if not url_key:
            return "OSRM 暂不支持公交路线规划，请切换提供商。"

        url = f"{cfg[url_key]}/{origin_coord[1]},{origin_coord[0]};{dest_coord[1]},{dest_coord[0]}"
        params = {"overview": "full", "steps": "true", "alternatives": "true"}

        try:
            resp = _requests.get(url, params=params, headers={"User-Agent": "MCP-Nav/1.0"}, timeout=10)
            data = resp.json()
            if data.get("code") != "Ok":
                return f"OSRM 路线规划失败: {data.get('message', '未知错误')}"

            routes = data.get("routes", [])
            if not routes:
                return "未找到可用路线。"

            lines = [
                f"路线规划 ({cfg['name']}, {mode_name})",
                f"起点: {origin} ({origin_coord[0]:.4f}, {origin_coord[1]:.4f})",
                f"终点: {destination} ({dest_coord[0]:.4f}, {dest_coord[1]:.4f})",
            ]

            for i, route in enumerate(routes[:3], 1):
                dist = route.get("distance", 0) / 1000
                dur = route.get("duration", 0) / 60
                lines.append(
                    f"\n路线 {i}: {dist:.1f} km, 约 {dur:.0f} 分钟"
                )
                # 导航步骤摘要
                steps = route.get("legs", [{}])[0].get("steps", [])
                if steps:
                    lines.append(f"  {len(steps)} 个转弯:")
                    for j, step in enumerate(steps[:8], 1):
                        instruction = step.get("name", "") or "直行"
                        sd = step.get("distance", 0)
                        if sd > 1000:
                            lines.append(f"    {j}. {instruction} ({sd/1000:.1f} km)")
                        else:
                            lines.append(f"    {j}. {instruction} ({sd:.0f} m)")
                    if len(steps) > 8:
                        lines.append(f"    ... 还有 {len(steps) - 8} 步")

            return "\n".join(lines)
        except Exception as e:
            return f"OSRM 请求失败: {str(e)}"

    # ---- 高德路径 ----
    if provider == "amap":
        url_map = {
            "driving": "driving_url", "walking": "walking_url",
            "transit": "transit_url", "bicycling": "bicycling_url",
        }
        url = cfg.get(url_map.get(mode, "driving_url"))
        params = {
            "key": api_key,
            "origin": f"{origin_coord[1]},{origin_coord[0]}",
            "destination": f"{dest_coord[1]},{dest_coord[0]}",
            "extensions": "all",
            "output": "JSON",
        }
        if mode == "transit":
            params["city"] = "北京"  # 默认城市

        try:
            resp = _requests.get(url, params=params, timeout=10)
            data = resp.json()
            if data.get("status") != "1":
                return f"高德路线规划失败: {data.get('info', '未知错误')}"

            route_data = data.get("route", {})
            paths = route_data.get("paths", [])
            if not paths:
                return "未找到可用路线。"

            lines = [
                f"路线规划 (高德地图, {mode_name})",
                f"起点: {origin} ({origin_coord[0]:.4f}, {origin_coord[1]:.4f})",
                f"终点: {destination} ({dest_coord[0]:.4f}, {dest_coord[1]:.4f})",
            ]

            for i, path in enumerate(paths[:3], 1):
                dist = int(path.get("distance", 0)) / 1000
                dur = int(path.get("duration", 0)) / 60
                cost = path.get("cost", 0)
                cost_str = f", 约{cost}元" if cost else ""
                lines.append(f"\n路线 {i}: {dist:.1f} km, 约 {dur:.0f} 分钟{cost_str}")

                steps = path.get("steps", [])
                if steps:
                    lines.append(f"  {len(steps)} 个步骤:")
                    for j, step in enumerate(steps[:8], 1):
                        instruction = step.get("instruction", "") or ""
                        # 去掉 HTML 标签
                        import re
                        instruction = re.sub(r"<[^>]+>", "", instruction)
                        sd = int(step.get("distance", 0))
                        if sd > 1000:
                            lines.append(f"    {j}. {instruction[:80]} ({sd/1000:.1f} km)")
                        else:
                            lines.append(f"    {j}. {instruction[:80]} ({sd:.0f} m)")
                    if len(steps) > 8:
                        lines.append(f"    ... 还有 {len(steps) - 8} 步")

            return "\n".join(lines)
        except Exception as e:
            return f"高德请求失败: {str(e)}"

    # ---- 百度路径 ----
    if provider == "baidu":
        url_map = {
            "driving": "driving_url", "walking": "walking_url",
            "transit": "transit_url", "bicycling": "bicycling_url",
        }
        url = cfg.get(url_map.get(mode, "driving_url"))
        params = {
            "ak": api_key,
            "origin": f"{origin_coord[0]},{origin_coord[1]}",
            "destination": f"{dest_coord[0]},{dest_coord[1]}",
            "output": "json",
        }
        if mode == "transit":
            params["page_size"] = "3"

        try:
            resp = _requests.get(url, params=params, timeout=10)
            data = resp.json()
            if data.get("status") != 0:
                return f"百度路线规划失败: {data.get('message', '未知错误')}"

            result = data.get("result", {})
            routes = result.get("routes", [])
            if not routes:
                return "未找到可用路线。"

            lines = [
                f"路线规划 (百度地图, {mode_name})",
                f"起点: {origin} ({origin_coord[0]:.4f}, {origin_coord[1]:.4f})",
                f"终点: {destination} ({dest_coord[0]:.4f}, {dest_coord[1]:.4f})",
            ]

            for i, route in enumerate(routes[:3], 1):
                dist = route.get("distance", 0) / 1000
                dur = route.get("duration", 0) / 60
                lines.append(f"\n路线 {i}: {dist:.1f} km, 约 {dur:.0f} 分钟")

                steps = route.get("steps", [])
                if steps:
                    lines.append(f"  {len(steps)} 个步骤:")
                    for j, step in enumerate(steps[:8], 1):
                        instruction = step.get("instructions", step.get("road_name", "")) or "直行"
                        sd = step.get("distance", 0)
                        if sd > 1000:
                            lines.append(f"    {j}. {instruction[:80]} ({sd/1000:.1f} km)")
                        else:
                            lines.append(f"    {j}. {instruction[:80]} ({sd:.0f} m)")
                    if len(steps) > 8:
                        lines.append(f"    ... 还有 {len(steps) - 8} 步")

            return "\n".join(lines)
        except Exception as e:
            return f"百度请求失败: {str(e)}"

    # ---- Google 路径 ----
    if provider == "google":
        params = {
            "key": api_key,
            "origin": f"{origin_coord[0]},{origin_coord[1]}",
            "destination": f"{dest_coord[0]},{dest_coord[1]}",
            "mode": mode,
            "alternatives": "true",
            "language": "zh-CN",
        }

        try:
            resp = _requests.get(cfg["driving_url"], params=params, timeout=10)
            data = resp.json()
            if data.get("status") != "OK":
                return f"Google 路线规划失败: {data.get('status', '未知')}"

            routes = data.get("routes", [])
            if not routes:
                return "未找到可用路线。"

            lines = [
                f"路线规划 (Google Maps, {mode_name})",
                f"起点: {origin} ({origin_coord[0]:.4f}, {origin_coord[1]:.4f})",
                f"终点: {destination} ({dest_coord[0]:.4f}, {dest_coord[1]:.4f})",
            ]

            for i, route in enumerate(routes[:3], 1):
                leg = route.get("legs", [{}])[0]
                dist = leg.get("distance", {}).get("text", "?")
                dur = leg.get("duration", {}).get("text", "?")
                lines.append(f"\n路线 {i}: {dist}, {dur}")

                steps = leg.get("steps", [])
                if steps:
                    lines.append(f"  {len(steps)} 个步骤:")
                    for j, step in enumerate(steps[:8], 1):
                        import re
                        instruction = re.sub(r"<[^>]+>", "", step.get("html_instructions", ""))
                        sd = step.get("distance", {}).get("text", "")
                        lines.append(f"    {j}. {instruction[:80]} ({sd})")
                    if len(steps) > 8:
                        lines.append(f"    ... 还有 {len(steps) - 8} 步")

            return "\n".join(lines)
        except Exception as e:
            return f"Google 请求失败: {str(e)}"

    return f"不支持的提供商: {provider}"


# ============================================================
# 地点搜索
# ============================================================
def _exec_nav_search(args: dict) -> str:
    session_id = args.get("session_id", "default")
    conn = _get_conn(session_id)
    provider = conn.get("provider", "amap")
    api_key = conn.get("api_key", "")
    query = (args.get("query") or "").strip()
    city = (args.get("city") or "").strip()

    if not query:
        return "错误: query 不能为空"

    cfg = NAV_PROVIDERS.get(provider)
    if not cfg:
        return f"不支持的提供商: {provider}"

    if provider == "osrm":
        return "OSRM 不支持地点搜索功能，请切换到高德/百度/Google。"

    if not api_key:
        return f"请先配置 {cfg['name']} API Key。"

    try:
        results = []

        if provider == "amap":
            params = {"key": api_key, "keywords": query, "output": "JSON", "offset": 10}
            if city:
                params["city"] = city
            resp = _requests.get(cfg["search_url"], params=params, timeout=8)
            data = resp.json()
            pois = data.get("pois", [])
            for p in pois:
                results.append({
                    "name": p.get("name", "?"),
                    "address": p.get("address", "?"),
                    "location": p.get("location", "?"),
                    "type": p.get("type", "?"),
                })

        elif provider == "baidu":
            params = {"ak": api_key, "query": query, "output": "json", "page_size": 10, "scope": 2}
            if city:
                params["region"] = city
            resp = _requests.get(cfg["search_url"], params=params, timeout=8)
            data = resp.json()
            for p in data.get("results", []):
                loc = p.get("location", {})
                results.append({
                    "name": p.get("name", "?"),
                    "address": p.get("address", "?"),
                    "location": f"{loc.get('lat', '')},{loc.get('lng', '')}",
                    "type": p.get("detail_info", {}).get("type", "?"),
                })

        elif provider == "google":
            params = {"key": api_key, "query": query, "language": "zh-CN"}
            resp = _requests.get(cfg["search_url"], params=params, timeout=8)
            data = resp.json()
            for p in data.get("results", []):
                loc = p.get("geometry", {}).get("location", {})
                results.append({
                    "name": p.get("name", "?"),
                    "address": p.get("formatted_address", p.get("vicinity", "?")),
                    "location": f"{loc.get('lat', '')},{loc.get('lng', '')}",
                    "type": ", ".join(p.get("types", [])[:3]),
                })

        if not results:
            return f"未找到 '{query}' 相关的地点。"

        lines = [f"搜索结果: {query}" + (f" ({city})" if city else "")]
        for i, r in enumerate(results[:10], 1):
            lines.append(f"\n  [{i}] {r['name']}")
            lines.append(f"      {r['address']}")
            lines.append(f"      坐标: {r['location']} | 类型: {r.get('type', '?')}")

        return "\n".join(lines)
    except Exception as e:
        return f"搜索失败: {str(e)}"


# ============================================================
# 注册工具
# ============================================================
_tool_list = [
    (NAV_ROUTE_DEF, _exec_nav_route),
    (NAV_SEARCH_DEF, _exec_nav_search),
]

for tool_def, executor in _tool_list:
    tool_registry.register(tool_def["name"], tool_def, executor)


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app, http_session=None):
    @app.route("/api/navigation/test-connection", methods=["POST"])
    def navigation_test_connection():
        """测试导航服务连接"""
        data = request.get_json(force=True)
        provider = data.get("provider", "osrm")
        api_key = (data.get("api_key") or "").strip()
        session_id = data.get("session_id", "default")

        cfg = NAV_PROVIDERS.get(provider)
        if not cfg:
            return jsonify({"success": False, "error": f"不支持的提供商: {provider}"})

        conn = _get_conn(session_id)
        conn["provider"] = provider
        conn["api_key"] = api_key

        # OSRM 免费，直接测试请求
        if provider == "osrm":
            t0 = time.time()
            try:
                test_url = f"{cfg['driving_url']}/116.397,39.908;116.470,39.906"
                resp = _requests.get(test_url, params={"overview": "false"}, headers={"User-Agent": "MCP-Nav/1.0"}, timeout=8)
                latency_ms = round((time.time() - t0) * 1000)
                if resp.status_code == 200:
                    conn["connected"] = True
                    conn["last_test"] = time.time()
                    return jsonify({
                        "success": True,
                        "message": f"OSRM 服务可用 (免费，无需 Key)\n延迟: {latency_ms}ms",
                        "provider": "OpenStreetMap OSRM",
                        "latency_ms": latency_ms,
                    })
                return jsonify({"success": False, "error": f"OSRM 返回 HTTP {resp.status_code}"})
            except Exception as e:
                return jsonify({"success": False, "error": str(e)})

        if not api_key:
            return jsonify({
                "success": False,
                "error": f"请填入 {cfg['name']} API Key。\n注册地址: {cfg['register_url']}",
            }), 400

        t0 = time.time()

        # 测试地理编码
        test_address = "北京市天安门"
        coord = _geocode_nav(test_address, provider, api_key)
        latency_ms = round((time.time() - t0) * 1000)

        if coord:
            conn["connected"] = True
            conn["last_test"] = time.time()
            return jsonify({
                "success": True,
                "message": (
                    f"{cfg['name']} 连接成功！\n"
                    f"测试: {test_address} -> ({coord[0]:.4f}, {coord[1]:.4f})\n"
                    f"延迟: {latency_ms}ms"
                ),
                "provider": cfg["name"],
                "latency_ms": latency_ms,
                "test_coord": f"{coord[0]:.4f},{coord[1]:.4f}",
            })
        else:
            conn["connected"] = False
            return jsonify({
                "success": False,
                "error": f"{cfg['name']} API 测试失败。请检查 API Key 是否正确。",
                "latency_ms": latency_ms,
            })

    @app.route("/api/navigation/providers", methods=["GET"])
    def navigation_providers():
        """返回可用导航提供商列表"""
        return jsonify({k: {"name": v["name"], "needs_key": v["key_param"] is not None, "register_url": v["register_url"]} for k, v in NAV_PROVIDERS.items()})
