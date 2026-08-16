"""
MCP Finance 金融数据服务模块
提供汇率转换、股票/加密货币价格查询
"""

import json
import time

import requests as _requests
from flask import jsonify, request

from . import tool_registry

# ============================================================
# 缓存
# ============================================================
_cache = {"rates": None, "rates_time": 0}


# ============================================================
# 工具定义
# ============================================================
CURRENCY_DEF = {
    "name": "currency_convert",
    "description": (
        "使用实时汇率进行货币转换。"
        "当用户询问币种换算、汇率、某币等于多少某币时使用。"
        "支持常见货币: USD, CNY, EUR, JPY, GBP, HKD, KRW, AUD, CAD 等。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "amount": {"type": "number", "description": "金额"},
            "from_currency": {"type": "string", "description": "源货币代码，如 'USD'、'CNY'"},
            "to_currency": {"type": "string", "description": "目标货币代码，如 'EUR'、'JPY'"},
        },
        "required": ["amount", "from_currency", "to_currency"],
    },
}

STOCK_DEF = {
    "name": "stock_price",
    "description": (
        "获取股票或加密货币的当前价格。"
        "股票使用股票代码（如 AAPL, TSLA, 0700.HK），加密货币使用符号（如 BTC, ETH）。"
        "无需 API Key，使用 Yahoo Finance 和 CoinGecko 免费数据。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "股票代码或加密货币符号，如 'AAPL'、'BTC'"},
        },
        "required": ["symbol"],
    },
}


# ============================================================
# 货币转换
# ============================================================
def _get_rates() -> dict:
    """获取汇率（缓存 1 小时）"""
    now = time.time()
    if _cache["rates"] and now - _cache["rates_time"] < 3600:
        return _cache["rates"]

    try:
        # 免费 API，无需 Key
        resp = _requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=8)
        data = resp.json()
        _cache["rates"] = data.get("rates", {})
        _cache["rates_time"] = now
        return _cache["rates"]
    except Exception:
        return _cache["rates"] or {}


def _exec_currency(args: dict) -> str:
    amount = float(args.get("amount", 0))
    f = (args.get("from_currency") or "USD").upper()
    t = (args.get("to_currency") or "CNY").upper()

    rates = _get_rates()
    if not rates:
        return "❌ 无法获取汇率数据，请稍后重试。"

    if f not in rates or t not in rates:
        return f"❌ 不支持的货币代码: {f if f not in rates else t}\n支持的货币: {', '.join(sorted(rates.keys())[:30])}..."

    # 通过 USD 转换
    usd_amount = amount / rates[f]
    result = usd_amount * rates[t]

    return f"💱 {amount:,.2f} {f} = {result:,.4f} {t}\n📊 汇率: 1 {f} = {rates[t] / rates[f]:.4f} {t}"


# ============================================================
# 股票/加密货币价格
# ============================================================
def _exec_stock(args: dict) -> str:
    symbol = (args.get("symbol") or "").strip().upper()
    if not symbol:
        return "错误: symbol 不能为空"

    # 尝试加密货币（CoinGecko 免费 API）
    crypto_map = {
        "BTC": "bitcoin", "ETH": "ethereum", "USDT": "tether", "BNB": "binancecoin",
        "SOL": "solana", "XRP": "ripple", "ADA": "cardano", "DOGE": "dogecoin",
        "DOT": "polkadot", "AVAX": "avalanche-2", "MATIC": "matic-network",
    }
    crypto_id = crypto_map.get(symbol, symbol.lower() if symbol.isalpha() and len(symbol) <= 6 else None)

    # 先尝试 Yahoo Finance (股票 + 加密货币)
    result = _get_yahoo_price(symbol)
    if result:
        return result

    # CoinGecko 备用
    if crypto_id:
        result = _get_coingecko_price(crypto_id, symbol)
        if result:
            return result

    return f"❌ 未找到 '{symbol}' 的价格数据。\n请检查代码是否正确（如 AAPL、TSLA、BTC、ETH）。"


def _get_yahoo_price(symbol: str) -> str | None:
    """通过 yfinance 获取价格"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info
        if not info or "regularMarketPrice" not in info:
            return None

        price = info.get("regularMarketPrice", 0)
        prev_close = info.get("previousClose", price)
        change = price - prev_close
        pct = (change / prev_close * 100) if prev_close else 0
        name = info.get("shortName", info.get("longName", symbol))

        arrow = "📈" if change > 0 else "📉" if change < 0 else "➡️"
        return f"{arrow} {name} ({symbol})\n💵 价格: ${price:.2f}\n📊 涨跌: {change:+.2f} ({pct:+.2f}%)"
    except ImportError:
        pass
    except Exception:
        pass
    return None


def _get_coingecko_price(coin_id: str, symbol: str) -> str | None:
    """通过 CoinGecko 免费 API 获取加密货币价格"""
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price"
        resp = _requests.get(url, params={
            "ids": coin_id,
            "vs_currencies": "usd",
            "include_24hr_change": "true",
        }, timeout=8)
        data = resp.json()
        if coin_id in data:
            info = data[coin_id]
            price = info.get("usd", 0)
            change = info.get("usd_24h_change", 0)
            arrow = "📈" if change and change > 0 else "📉" if change and change < 0 else "➡️"
            return f"{arrow} {symbol} ({coin_id})\n💵 价格: ${price:,.2f}\n📊 24h 涨跌: {change:+.2f}%"
    except Exception:
        pass
    return None


_tool_list = [
    (CURRENCY_DEF, _exec_currency),
    (STOCK_DEF, _exec_stock),
]

for tool_def, executor in _tool_list:
    tool_registry.register(tool_def["name"], tool_def, executor)


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app, http_session=None):
    @app.route("/api/finance/test-connection", methods=["POST"])
    def finance_test_connection():
        """测试金融数据服务可用性"""
        results = {}

        # 测试汇率 API
        try:
            resp = _requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=5)
            if resp.status_code == 200:
                rates = resp.json().get("rates", {})
                results["exchange_rate"] = f"可用 ({len(rates)} 种货币)"
            else:
                results["exchange_rate"] = f"不可用 (HTTP {resp.status_code})"
        except Exception as e:
            results["exchange_rate"] = f"不可用 ({e})"

        # 测试 yfinance
        try:
            import yfinance
            results["yfinance"] = "可用"
        except ImportError:
            results["yfinance"] = "未安装 (pip install yfinance)"

        # 测试 CoinGecko
        try:
            resp = _requests.get("https://api.coingecko.com/api/v3/ping", timeout=5)
            results["coingecko"] = "可用" if resp.status_code == 200 else "不可用"
        except Exception:
            results["coingecko"] = "不可用"

        return jsonify({
            "success": any("可用" in v for v in results.values()),
            "message": "金融数据服务测试完成",
            "services": results,
        })
