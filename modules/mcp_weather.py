"""
MCP Weather 天气服务模块
提供天气查询工具，支持当前天气和预报
使用 OpenWeatherMap API（免费套餐：https://openweathermap.org/api）
"""

import json
import time
import urllib.parse

import requests as _requests
from flask import jsonify, request

from . import tool_registry
from .session_manager import TTLDict

# ============================================================
# 会话级配置（每个前端组件实例一个 session）
# TTLDict: 1小时过期，最多100个连接
# ============================================================
_connections = TTLDict(max_size=100, ttl_seconds=3600)


def _get_conn(session_id: str) -> dict:
    conn = _connections.get(session_id)
    if conn is None:
        conn = {
            "api_key": "",
            "city": "Beijing",
            "connected": False,
            "last_test": None,
        }
        _connections.set(session_id, conn)
    return conn


# ============================================================
# 工具定义
# ============================================================
WEATHER_CURRENT_DEF = {
    "name": "weather_current",
    "description": (
        "获取指定城市的当前天气信息，包括温度、湿度、风速、天气描述等。"
        "当用户询问某地现在天气如何、气温多少、是否下雨等时使用。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "城市名称，如 'Beijing'、'Tokyo'、'London'。支持中文名如 '北京'。",
            },
            "session_id": {
                "type": "string",
                "description": "会话 ID",
            },
        },
        "required": ["city"],
    },
}

WEATHER_FORECAST_DEF = {
    "name": "weather_forecast",
    "description": (
        "获取指定城市未来几天的天气预报。"
        "当用户询问未来天气、明天天气、这周天气时使用。"
        "返回每日最高/最低温度、天气状况等。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "城市名称，如 'Beijing'、'Shanghai'",
            },
            "days": {
                "type": "integer",
                "description": "预报天数，1-5，默认 3",
                "default": 3,
            },
            "session_id": {
                "type": "string",
                "description": "会话 ID",
            },
        },
        "required": ["city"],
    },
}


# ============================================================
# 天气 API 调用
# ============================================================
GEO_URL = "https://api.openweathermap.org/geo/1.0/direct"
WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"


def _geocode(city: str, api_key: str) -> dict | None:
    """将城市名转为经纬度"""
    params = {"q": city, "limit": 1, "appid": api_key}
    try:
        resp = _requests.get(GEO_URL, params=params, timeout=8)
        data = resp.json()
        if data and len(data) > 0:
            return {"lat": data[0]["lat"], "lon": data[0]["lon"], "name": data[0].get("local_names", {}).get("zh", data[0]["name"])}
    except Exception:
        pass
    return None


def _get_weather(city: str, api_key: str) -> str:
    """获取当前天气"""
    # 如果没有 API Key，使用免费的 wttr.in 作为回退
    if not api_key:
        return _get_weather_wttr(city)

    geo = _geocode(city, api_key)
    if not geo:
        return f"❌ 未找到城市 '{city}'，请检查城市名称拼写。"

    params = {"lat": geo["lat"], "lon": geo["lon"], "appid": api_key, "units": "metric", "lang": "zh_cn"}
    try:
        resp = _requests.get(WEATHER_URL, params=params, timeout=8)
        data = resp.json()
        if data.get("cod") != 200:
            return f"❌ 天气查询失败: {data.get('message', '未知错误')}"

        w = data["weather"][0] if data.get("weather") else {}
        m = data.get("main", {})
        wind = data.get("wind", {})
        sys_data = data.get("sys", {})

        # 风向转换
        deg = wind.get("deg", 0)
        dirs = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
        wind_dir = dirs[round(deg / 45) % 8] if deg else "未知"

        return (
            f"🌤️ {geo['name']} 当前天气\n"
            f"🌡️ 温度: {m.get('temp', '?')}°C（体感 {m.get('feels_like', '?')}°C）\n"
            f"🌧️ 天气: {w.get('description', '未知')}\n"
            f"💧 湿度: {m.get('humidity', '?')}%\n"
            f"🌬️ 风速: {wind.get('speed', '?')} m/s {wind_dir}\n"
            f"📊 气压: {m.get('pressure', '?')} hPa\n"
            f"👁️ 能见度: {data.get('visibility', '?')} m\n"
            f"🌅 日出: {_format_unix(sys_data.get('sunrise', 0))}  |  🌇 日落: {_format_unix(sys_data.get('sunset', 0))}"
        )
    except Exception as e:
        return f"❌ 天气查询失败: {str(e)}"


def _get_weather_wttr(city: str) -> str:
    """使用免费的 wttr.in API 获取天气（无需 API Key）"""
    import urllib.parse
    encoded_city = urllib.parse.quote(city)
    url = f"https://wttr.in/{encoded_city}?format=j1&lang=zh"
    try:
        resp = _requests.get(url, headers={"User-Agent": "MCP-Weather/1.0"}, timeout=8)
        data = resp.json()
        current = data.get("current_condition", [{}])[0]
        weather_info = data.get("weather", [{}])[0]
        astronomy = weather_info.get("astronomy", [{}])[0] if weather_info.get("astronomy") else {}

        temp_c = current.get("temp_C", "?")
        feels_like = current.get("FeelsLikeC", "?")
        humidity = current.get("humidity", "?")
        wind_speed = current.get("windspeedKmph", "?")
        wind_dir = current.get("winddir16Point", "?")
        pressure = current.get("pressure", "?")
        visibility = current.get("visibility", "?")
        desc = current.get("weatherDesc", [{}])[0].get("value", "未知")
        sunrise = astronomy.get("sunrise", "?")
        sunset = astronomy.get("sunset", "?")

        nearest = data.get("nearest_area", [{}])[0]
        area_name = nearest.get("areaName", [{}])[0].get("value", city)
        country = nearest.get("country", [{}])[0].get("value", "")

        return (
            f"🌤️ {area_name}{', ' + country if country else ''} 当前天气（免费数据源）\n"
            f"🌡️ 温度: {temp_c}°C（体感 {feels_like}°C）\n"
            f"🌧️ 天气: {desc}\n"
            f"💧 湿度: {humidity}%\n"
            f"🌬️ 风速: {wind_speed} km/h {wind_dir}\n"
            f"📊 气压: {pressure} hPa\n"
            f"👁️ 能见度: {visibility} km\n"
            f"🌅 日出: {sunrise}  |  🌇 日落: {sunset}\n"
            f"\n💡 使用 OpenWeatherMap API Key 可获得更精确的数据。"
        )
    except Exception as e:
        return f"❌ 免费天气查询也失败了: {str(e)}\n💡 建议配置 OpenWeatherMap API Key: https://openweathermap.org/api"


def _get_forecast(city: str, api_key: str, days: int) -> str:
    """获取天气预报"""
    # 如果没有 API Key，使用免费的 wttr.in 作为回退
    if not api_key:
        return _get_forecast_wttr(city, days)

    geo = _geocode(city, api_key)
    if not geo:
        return f"❌ 未找到城市 '{city}'。"

    params = {"lat": geo["lat"], "lon": geo["lon"], "appid": api_key, "units": "metric", "lang": "zh_cn", "cnt": days * 8}
    try:
        resp = _requests.get(FORECAST_URL, params=params, timeout=8)
        data = resp.json()
        if data.get("cod") != "200":
            return f"❌ 预报查询失败: {data.get('message', '未知错误')}"

        # 按天分组
        by_day = {}
        for item in data.get("list", []):
            day = item["dt_txt"][:10]
            if day not in by_day:
                by_day[day] = {"temps": [], "icons": [], "descs": [], "winds": []}
            by_day[day]["temps"].append(item["main"]["temp"])
            by_day[day]["icons"].append(item["weather"][0]["icon"])
            by_day[day]["descs"].append(item["weather"][0]["description"])
            by_day[day]["winds"].append(item["wind"]["speed"])

        lines = [f"📅 {geo['name']} 未来 {min(days, len(by_day))} 天天气预报:"]
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

        for i, (day, vals) in enumerate(by_day.items()):
            if i >= days:
                break
            import datetime
            dt = datetime.datetime.strptime(day, "%Y-%m-%d")
            wd = weekdays[dt.weekday()]
            # 最常见天气描述
            desc = max(set(vals["descs"]), key=vals["descs"].count)
            lines.append(
                f"\n  {day} {wd}: {desc}"
                f"  |  🌡️ {min(vals['temps']):.0f}°C ~ {max(vals['temps']):.0f}°C"
                f"  |  🌬️ {sum(vals['winds']) / len(vals['winds']):.1f} m/s"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 预报查询失败: {str(e)}"


def _get_forecast_wttr(city: str, days: int) -> str:
    """使用免费的 wttr.in API 获取天气预报（无需 API Key）"""
    import urllib.parse
    encoded_city = urllib.parse.quote(city)
    url = f"https://wttr.in/{encoded_city}?format=j1&lang=zh"
    try:
        resp = _requests.get(url, headers={"User-Agent": "MCP-Weather/1.0"}, timeout=8)
        data = resp.json()
        forecast = data.get("weather", [])

        lines = [f"📅 {city} 未来 {min(days, len(forecast))} 天天气预报（免费数据源）:"]
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

        import datetime
        for i, day_data in enumerate(forecast[:days]):
            date_str = day_data.get("date", "?")
            try:
                dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                wd = weekdays[dt.weekday()]
            except Exception:
                wd = ""
            max_temp = day_data.get("maxtempC", "?")
            min_temp = day_data.get("mintempC", "?")
            hourly = day_data.get("hourly", [{}])
            desc = hourly[0].get("weatherDesc", [{}])[0].get("value", "未知") if hourly else "未知"
            wind = day_data.get("hourly", [{}])[0].get("windspeedKmph", "?") if hourly else "?"

            lines.append(
                f"\n  {date_str} {wd}: {desc}"
                f"  |  🌡️ {min_temp}°C ~ {max_temp}°C"
                f"  |  🌬️ {wind} km/h"
            )

        lines.append("\n💡 使用 OpenWeatherMap API Key 可获得更精确的数据。")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 免费天气预报查询也失败了: {str(e)}"


def _format_unix(ts: int) -> str:
    if not ts:
        return "?"
    return time.strftime("%H:%M", time.localtime(ts))


# ============================================================
# 执行器
# ============================================================
def _exec_weather_current(args: dict) -> str:
    session_id = args.get("session_id", "default")
    conn = _get_conn(session_id)
    api_key = args.get("api_key") or conn.get("api_key", "")
    city = args.get("city", conn.get("city", "Beijing"))

    # 无 API Key 时自动使用免费 wttr.in，不再报错
    return _get_weather(city, api_key)


def _exec_weather_forecast(args: dict) -> str:
    session_id = args.get("session_id", "default")
    conn = _get_conn(session_id)
    api_key = args.get("api_key") or conn.get("api_key", "")
    city = args.get("city", conn.get("city", "Beijing"))
    days = min(int(args.get("days", 3)), 5)

    # 无 API Key 时自动使用免费 wttr.in，不再报错
    return _get_forecast(city, api_key, days)


# ============================================================
# 注册工具
# ============================================================
_tool_list = [
    (WEATHER_CURRENT_DEF, _exec_weather_current),
    (WEATHER_FORECAST_DEF, _exec_weather_forecast),
]

for tool_def, executor in _tool_list:
    tool_registry.register(tool_def["name"], tool_def, executor)


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app, http_session=None):
    @app.route("/api/weather/test-connection", methods=["POST"])
    def weather_test_connection():
        """测试 OpenWeatherMap API 连接"""
        data = request.get_json(force=True)
        api_key = (data.get("api_key") or "").strip()
        city = (data.get("city") or "Beijing").strip()
        session_id = data.get("session_id", "default")

        if not api_key:
            return jsonify({"success": False, "error": "请填入 OpenWeatherMap API Key（免费注册: openweathermap.org）"}), 400

        conn = _get_conn(session_id)
        conn["api_key"] = api_key
        conn["city"] = city

        t0 = time.time()
        try:
            # 用 geocode 测试 key 是否有效
            resp = _requests.get(
                GEO_URL,
                params={"q": city, "limit": 1, "appid": api_key},
                timeout=10,
            )
            latency_ms = round((time.time() - t0) * 1000)

            if resp.status_code == 401:
                conn["connected"] = False
                conn["last_test"] = time.time()
                return jsonify({
                    "success": False,
                    "error": "API Key 无效，请检查 Key 是否正确。",
                    "latency_ms": latency_ms,
                })
            elif resp.status_code == 200:
                data = resp.json()
                city_name = data[0].get("local_names", {}).get("zh", data[0]["name"]) if data else city
                conn["connected"] = True
                conn["last_test"] = time.time()
                return jsonify({
                    "success": True,
                    "message": f"连接成功！已定位城市: {city_name}",
                    "city": city_name,
                    "latency_ms": latency_ms,
                })
            else:
                conn["connected"] = False
                conn["last_test"] = time.time()
                return jsonify({
                    "success": False,
                    "error": f"API 返回异常: HTTP {resp.status_code}",
                    "latency_ms": latency_ms,
                })
        except _requests.exceptions.Timeout:
            return jsonify({"success": False, "error": "连接超时，请检查网络"})
        except _requests.exceptions.ConnectionError:
            return jsonify({"success": False, "error": "无法连接到 OpenWeatherMap API，请检查网络"})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})

    @app.route("/api/weather/config", methods=["GET"])
    def weather_get_config():
        """获取当前天气服务配置（不暴露完整 API Key）"""
        session_id = request.args.get("session_id", "default")
        conn = _get_conn(session_id)
        key = conn.get("api_key", "")
        return jsonify({
            "has_api_key": bool(key),
            "api_key_preview": (key[:4] + "..." + key[-4:]) if len(key) > 8 else "",
            "city": conn.get("city", "Beijing"),
            "connected": conn.get("connected", False),
            "last_test": conn.get("last_test"),
        })
