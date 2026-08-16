"""
Web Search 网页搜索模块
多引擎联合搜索: 微博热搜 → 搜狗/360 → 百度新闻 → 搜狗微信 → 搜狗新闻 → Bing
"""

import json
import re
import time
import urllib.parse

import requests as _requests
from flask import jsonify, request

from . import tool_registry

# ============================================================
# 工具定义 (OpenAI Function Calling Schema)
# ============================================================
WEB_SEARCH_DEFINITION = {
    "name": "web_search",
    "description": (
        "搜索互联网获取最新信息。"
        "当需要查找实时信息、新闻、热点事件、百科知识或任何不确定的事实时使用此工具。"
        "支持中文和英文搜索，自动匹配最优搜索引擎。"
        "时效性查询（新闻/热点/最新动态）会优先使用新闻和热搜引擎。"
        "返回标题、摘要、来源地址和发布日期。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词或问题，例如 '2024年诺贝尔物理学奖得主'",
            },
            "max_results": {
                "type": "integer",
                "description": "返回结果数量，默认 5，最大 10",
                "default": 5,
            },
            "time_range": {
                "type": "string",
                "enum": ["day", "week", "month", "year", "auto"],
                "description": (
                    "时间范围筛选。day=24小时内, week=一周内, month=一月内, "
                    "year=一年内, auto=自动判断(默认)。"
                    "查询新闻/热点/最新动态时建议使用 day 或 week。"
                ),
                "default": "auto",
            },
        },
        "required": ["query"],
    },
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 搜索引擎超时（秒）
ENGINE_TIMEOUT = {
    "bing_cn": 5,
    "sogou": 8,
    "bing": 8,
}

# Sogou 专用 Session（带 Cookie 伪装）
_sogou_session = None


def _get_sogou_session():
    """获取或创建 Sogou 搜索 Session（首次访问首页获取 Cookie）"""
    global _sogou_session
    if _sogou_session is not None:
        return _sogou_session
    _sogou_session = _requests.Session()
    _sogou_session.headers.update(HEADERS)
    try:
        # 先访问首页获取 Cookie
        _sogou_session.get("https://www.sogou.com/", timeout=5)
    except Exception:
        pass
    return _sogou_session


# ============================================================
# AI 工具执行器
# ============================================================
def execute_web_search(args: dict) -> str:
    """AI 调用的搜索执行器"""
    query = (args.get("query") or "").strip()
    max_results = min(int(args.get("max_results", 5)), 10)
    time_range = args.get("time_range", "auto")

    if not query:
        return "错误: 搜索关键词不能为空"

    results = _search_all(query, max_results, time_range)

    if not results:
        return f"未找到与 '{query}' 相关的结果，请尝试更换关键词。"

    time_label = {"day": "24小时内", "week": "一周内", "month": "一月内", "year": "一年内"}.get(time_range, "")
    header = f"🔍 搜索 '{query}'" + (f"（{time_label}）" if time_label else "") + f" 的结果 ({len(results)} 条):"
    lines = [header]
    for i, r in enumerate(results, 1):
        lines.append(f"\n[{i}] {r['title']}")
        lines.append(f"    {r['snippet'][:300]}")
        if r.get("url"):
            lines.append(f"    🔗 {r['url']}")
    return "\n".join(lines)


tool_registry.register("web_search", WEB_SEARCH_DEFINITION, execute_web_search)


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app, http_session=None):
    @app.route("/api/web-search", methods=["POST"])
    def web_search():
        data = request.get_json(force=True)
        query = (data.get("query") or "").strip()
        max_results = min(int(data.get("max_results", 5)), 20)
        time_range = data.get("time_range", "auto")

        if not query:
            return jsonify({"error": "query 不能为空"}), 400

        t0 = time.time()
        try:
            results = _search_all(query, max_results, time_range)
            latency_ms = round((time.time() - t0) * 1000)
            return jsonify({
                "success": True,
                "query": query,
                "results": results,
                "count": len(results),
                "latency_ms": latency_ms,
            })
        except Exception as e:
            latency_ms = round((time.time() - t0) * 1000)
            return jsonify({
                "success": False,
                "error": str(e),
                "latency_ms": latency_ms,
            }), 500

    @app.route("/api/web-search/engines", methods=["GET"])
    def get_engines():
        """获取搜索引擎列表（含当前排序和状态）"""
        return jsonify({
            "engines": get_engine_list(),
            "order": ENGINE_ORDER,
        })

    @app.route("/api/web-search/engines", methods=["POST"])
    def set_engines():
        """更新搜索引擎优先级排序和开关"""
        data = request.get_json(force=True)
        new_order = data.get("order")
        enabled_map = data.get("enabled")
        update_engine_order(new_order, enabled_map)
        return jsonify({
            "success": True,
            "engines": get_engine_list(),
            "order": ENGINE_ORDER,
        })

    @app.route("/api/web-search/hot", methods=["GET"])
    def get_hot():
        """获取微博实时热搜榜单"""
        t0 = time.time()
        try:
            results = _search_weibo_hot("", 20)
            latency_ms = round((time.time() - t0) * 1000)
            return jsonify({
                "success": True,
                "results": results,
                "count": len(results),
                "latency_ms": latency_ms,
                "source": "微博热搜",
            })
        except Exception as e:
            latency_ms = round((time.time() - t0) * 1000)
            return jsonify({
                "success": False,
                "error": str(e),
                "latency_ms": latency_ms,
            }), 500


# ============================================================
# 搜索引擎注册表（可动态排序）
# ============================================================
SEARCH_ENGINES = {
    "bing_cn": {
        "id": "bing_cn",
        "name": "Bing 中国",
        "icon": "🔎",
        "desc": "主力引擎，国内特供 cn.bing.com，中英文均优，速度快，摘要干净",
        "enabled": True,
        "search_fn": None,
    },
    "weibo_hot": {
        "id": "weibo_hot",
        "name": "微博热搜",
        "icon": "🔥",
        "desc": "实时热搜榜单，中文互联网最实时的信息源，适合热点/突发新闻",
        "enabled": True,
        "search_fn": None,
    },
    "sogou": {
        "id": "sogou",
        "name": "搜狗",
        "icon": "🐕",
        "desc": "中文最准确，带 3s 频率限制防反爬",
        "enabled": True,
        "search_fn": None,  # 延迟绑定
    },
    "so360": {
        "id": "so360",
        "name": "360 搜索",
        "icon": "🔍",
        "desc": "国内可访问，中文准确",
        "enabled": True,
        "search_fn": None,
    },
    "baidu_news": {
        "id": "baidu_news",
        "name": "百度新闻",
        "icon": "📰",
        "desc": "新闻聚合搜索，按时间排序，支持时间范围筛选（天/周/月）",
        "enabled": True,
        "search_fn": None,
    },
    "weixin": {
        "id": "weixin",
        "name": "搜狗微信",
        "icon": "💬",
        "desc": "搜索微信公众号文章，中文内容极其丰富，适合深度信息检索",
        "enabled": True,
        "search_fn": None,
    },
    "sogou_news": {
        "id": "sogou_news",
        "name": "搜狗新闻",
        "icon": "📋",
        "desc": "搜狗新闻搜索，百度新闻备用引擎",
        "enabled": False,  # 默认禁用，作为百度新闻备选
        "search_fn": None,
    },
    "bing": {
        "id": "bing",
        "name": "Bing",
        "icon": "🔎",
        "desc": "备选引擎，中文分词较差，自动过滤噪音",
        "enabled": False,  # 默认禁用，中文分词太差
        "search_fn": None,
    },
}
# 默认优先级顺序
ENGINE_ORDER = ["bing_cn", "weibo_hot", "sogou", "so360", "baidu_news", "weixin", "sogou_news", "bing"]


def _get_search_fn(engine_id: str):
    """延迟绑定搜索函数（避免循环引用）"""
    fn_map = {
        "bing_cn": _search_bing_cn,
        "sogou": _search_sogou,
        "so360": _search_so360,
        "bing": _search_bing,
        "weixin": _search_weixin,
        "weibo_hot": _search_weibo_hot,
        "baidu_news": _search_baidu_news,
        "sogou_news": _search_sogou_news,
    }
    return fn_map.get(engine_id)


def get_engine_list() -> list:
    """返回引擎列表（按当前排序，带 enabled 状态）"""
    result = []
    for eid in ENGINE_ORDER:
        eng = SEARCH_ENGINES.get(eid)
        if eng:
            result.append({
                "id": eng["id"],
                "name": eng["name"],
                "icon": eng["icon"],
                "desc": eng["desc"],
                "enabled": eng["enabled"],
            })
    return result


def update_engine_order(order: list, enabled_map: dict = None):
    """更新引擎优先级顺序和开关状态"""
    global ENGINE_ORDER
    valid = [eid for eid in order if eid in SEARCH_ENGINES]
    if valid:
        ENGINE_ORDER = valid
    if enabled_map:
        for eid, enabled in enabled_map.items():
            if eid in SEARCH_ENGINES:
                SEARCH_ENGINES[eid]["enabled"] = bool(enabled)

# ============================================================
# 联合搜索调度
# ============================================================

def _search_all(query: str, max_results: int, time_range: str = "auto") -> list:
    """多引擎联合搜索，并行请求所有启用的搜索引擎"""
    import concurrent.futures

    # 自动检测时间范围
    if time_range == "auto":
        time_range = _detect_time_range(query)

    # 检测是否为热搜/热点类查询
    is_hot_query = bool(re.search(
        r'热搜|热门|trending|正在发生|最新消息|突发|热点|今天发生|实时',
        query,
    )) or time_range in ("day",)
    # 检测是否为新闻类查询
    is_news_query = bool(re.search(
        r'新闻|快讯|报道|最新|发布|公布|出炉|官宣|动态|进展|事件|news',
        query,
    )) or time_range in ("day", "week", "month")

    is_time_sensitive = time_range in ("day", "week", "month")

    # 构建候选引擎列表（过滤不可用引擎）
    candidates = []
    for eid in ENGINE_ORDER:
        eng = SEARCH_ENGINES.get(eid)
        if not eng or not eng["enabled"]:
            continue
        if eid == "weibo_hot" and not (is_hot_query or time_range == "day"):
            continue
        if eid in ("baidu_news", "sogou_news") and not is_news_query:
            continue

        search_fn = _get_search_fn(eid)
        if not search_fn:
            continue

        fetch_count = max_results + 2
        if is_time_sensitive and eid in ("weibo_hot", "baidu_news", "sogou_news"):
            fetch_count = min(fetch_count, max(2, max_results // 2) + 1)

        candidates.append((eid, search_fn, fetch_count))

    # ── 并行搜索所有候选引擎 ──
    all_results = []
    seen_urls = set()

    if not candidates:
        all_results = [{
            "title": f"搜索 '{query}'",
            "snippet": "所有搜索引擎暂时不可用，请检查网络或稍后重试。",
            "url": "",
            "source": "本地",
            "type": "error",
        }]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(candidates), 6)) as executor:
            future_map = {}
            for eid, search_fn, fetch_count in candidates:
                future = executor.submit(search_fn, query, fetch_count, time_range)
                future_map[future] = eid

            for future in concurrent.futures.as_completed(future_map, timeout=30):
                try:
                    results = future.result(timeout=5)
                except Exception:
                    continue
                if results:
                    for r in results:
                        url_key = r.get("url", "")
                        if not url_key or url_key not in seen_urls:
                            all_results.append(r)
                            if url_key:
                                seen_urls.add(url_key)
                            if len(all_results) >= max_results:
                                break
                if len(all_results) >= max_results:
                    # 取消尚未完成的任务
                    for f in future_map:
                        if not f.done():
                            f.cancel()
                    break

    # ---------- 兜底 ----------
    if not all_results:
        all_results = [{
            "title": f"搜索 '{query}'",
            "snippet": "所有搜索引擎暂时不可用（已尝试: 搜狗、360搜索、Bing、百度新闻、微博热搜等），请检查网络或稍后重试。",
            "url": "",
            "source": "本地",
            "type": "error",
        }]

    # 按日期排序
    all_results = _sort_by_freshness(all_results)
    return all_results[:max_results]


# ============================================================
# 文本清洗
# ============================================================

def _clean_text(text: str) -> str:
    """清洗文本：去 HTML 标签、HTML 实体、控制字符、多余空白"""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace("&ensp;", " ").replace("&nbsp;", " ")
    text = text.replace("&amp;", "&").replace("&lt;", "<")
    text = text.replace("&gt;", ">").replace("&quot;", "\"")
    text = re.sub(r'&#?\w+;', ' ', text)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _is_chinese_query(query: str) -> bool:
    """判断查询是否包含中文"""
    return bool(re.search(r'[一-鿿]', query))


def _is_time_sensitive(query: str) -> bool:
    """判断查询是否对时效性敏感（含时间/事件/新闻等关键词）"""
    time_words = [
        # 绝对时间词
        r'20\d{2}年?', r'\d{1,2}月\d{1,2}日',
        # 相对时间词
        r'最新', r'最近', r'近日', r'日前', r'近期',
        r'今日', r'今天', r'昨天', r'昨日', r'本周', r'上周', r'本月',
        r'刚刚', r'刚刚发生', r'实时',
        # 事件词
        r'发布', r'公布', r'出炉', r'官宣', r'曝光', r'上线',
        r'开幕', r'闭幕', r'结果', r'进展', r'动态',
        # 领域词（自带时效需求）
        r'股价', r'股市', r'股票', r'行情', r'天气', r'地震',
        r'新闻', r'快讯', r'直播', r'热点', r'热搜', r'热门',
        r'趋势', r'trending', r'排名', r'排行',
        r'成绩', r'分数', r'分数线', r'录取',
        r'疫情', r'台风', r'暴雨', r'预警',
        r'金牌', r'奖牌', r'比赛', r'赛事', r'赛果',
        r'票房', r'开奖', r'中奖',
    ]
    for pat in time_words:
        if re.search(pat, query):
            return True
    return False


def _detect_time_range(query: str) -> str:
    """从查询中自动推断时间范围，返回 day/week/month/year"""
    # 超短期：今天/刚刚/实时/热搜/热点/快讯/正在
    short_patterns = [
        r'今天', r'今日', r'刚刚', r'实时', r'热搜', r'热点',
        r'快讯', r'正在', r'直播', r'最新消息', r'突发',
    ]
    for pat in short_patterns:
        if re.search(pat, query):
            return "day"

    # 短期：昨天/本周/最近几天/近日
    mid_patterns = [
        r'昨天', r'昨日', r'本周', r'这周', r'最近几天',
        r'近几天', r'近日', r'日前', r'刚发布',
    ]
    for pat in mid_patterns:
        if re.search(pat, query):
            return "week"

    # 中期：本月/最近一个月/上月
    month_patterns = [r'本月', r'这个月', r'上月', r'最近.*月', r'近期']
    for pat in month_patterns:
        if re.search(pat, query):
            return "month"

    # 长期：今年/202x年
    year_patterns = [r'今年', r'20\d{2}年']
    for pat in year_patterns:
        if re.search(pat, query):
            return "year"

    # 有明确时间词但无法归类的 → 默认 week
    if _is_time_sensitive(query):
        return "week"

    return "auto"


def _extract_date(text: str) -> str:
    """从文本中提取日期，返回 YYYY-MM-DD 格式或空字符串"""
    patterns = [
        r'(\d{4})年(\d{1,2})月(\d{1,2})日',
        r'(\d{4})-(\d{1,2})-(\d{1,2})',
        r'(\d{4})/(\d{1,2})/(\d{1,2})',
        r'(\d{1,2})月(\d{1,2})日',  # 无年份，补当年
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            groups = m.groups()
            if len(groups) == 3:
                y, mo, d = groups
                return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
            else:
                today = time.strftime("%Y")
                mo, d = groups
                return f"{today}-{int(mo):02d}-{int(d):02d}"
    return ""


def _sort_by_freshness(results: list) -> list:
    """按发布日期从新到旧排序，无日期的排在后面"""
    def _sort_key(r):
        snippet = r.get("snippet", "")
        title = r.get("title", "")
        date_str = _extract_date(snippet) or _extract_date(title)
        if date_str:
            # 有日期排前面，用日期字符串作为排序键（ISO 格式可直接比较）
            return (0, date_str)
        # 热搜类型无日期但很新鲜，排第二优先级
        if r.get("type") == "hot":
            return (1, "")
        # 新闻类型无明确日期，排第三
        if r.get("type") == "news":
            return (2, "")
        # 其他无日期排最后
        return (3, "")

    return sorted(results, key=_sort_key)


# ============================================================
# Bing 中国 (cn.bing.com) — 主力引擎，国内特供，中英文均优
# ============================================================

def _search_bing_cn(query: str, max_results: int, time_range: str = "auto") -> list:
    """Bing 中国版 cn.bing.com — 国内可直接访问，速度快，结果质量高"""
    import requests as _r

    params = {
        "q": query,
        "count": max_results + 2,
        "setlang": "zh-cn",
    }
    # 时间范围
    if time_range == "day":
        params["tbs"] = "qdr:d"
    elif time_range == "week":
        params["tbs"] = "qdr:w"
    elif time_range == "month":
        params["tbs"] = "qdr:m"
    elif time_range == "year":
        params["tbs"] = "qdr:y"
    elif _is_time_sensitive(query):
        params["tbs"] = "qdr:w"

    try:
        resp = _r.get(
            "https://cn.bing.com/search",
            params=params,
            headers=HEADERS,
            timeout=5,
        )
        resp.encoding = resp.apparent_encoding or "utf-8"
        if resp.status_code != 200 or len(resp.text) < 5000:
            return []
    except Exception:
        return []

    return _parse_bing_cn_html(resp.text, max_results)


def _parse_bing_cn_html(html: str, max_results: int) -> list:
    """解析 cn.bing.com 搜索结果"""
    results = []

    try:
        from lxml import etree
        tree = etree.HTML(html)

        for item in tree.xpath('//li[contains(@class,"b_algo")]'):
            if len(results) >= max_results:
                break

            # 标题和链接
            title_el = item.xpath('.//h2/a')
            if not title_el:
                continue
            title = _clean_text(title_el[0].xpath('string()') or "")
            url = (title_el[0].get("href") or "").strip()

            # 摘要 — Bing 的 caption 区域
            snippet = ""
            caption_el = item.xpath('.//div[contains(@class,"b_caption")]')
            if caption_el:
                snippet = _clean_text(caption_el[0].xpath('string()') or "")
            if not snippet:
                # 备选：找段落
                for p_el in item.xpath('.//p'):
                    text = _clean_text(p_el.xpath('string()') or "")
                    if len(text) > 40:
                        snippet = text
                        break

            # 来源域名
            source = "Bing CN"
            cite_el = item.xpath('.//cite')
            if cite_el:
                cite_text = _clean_text(cite_el[0].xpath('string()') or "")
                if cite_text:
                    source = cite_text.split()[0] if cite_text else "Bing CN"

            # 日期
            date_text = ""
            for span in item.xpath('.//span[contains(@class,"news_dt")] | .//span[contains(@class,"faded")]'):
                text = _clean_text(span.xpath('string()') or "")
                date_text = _extract_date(text)
                if date_text:
                    break
            if date_text:
                snippet = f"📅 {date_text} | {snippet}"

            if title:
                results.append({
                    "title": title,
                    "snippet": snippet[:500] if snippet else title,
                    "url": url,
                    "source": source,
                    "type": "web",
                })

        return results[:max_results]

    except Exception:
        pass

    # Regex fallback
    blocks = re.findall(
        r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>(.*?)</li>',
        html, re.DOTALL,
    )
    for block in blocks:
        if len(results) >= max_results:
            break
        title_m = re.search(r'<h2[^>]*><a[^>]*href="([^"]*)"[^>]*>(.*?)</a></h2>', block, re.DOTALL)
        if not title_m:
            continue
        title = _clean_text(title_m.group(2))
        url = title_m.group(1)
        snippet_m = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
        snippet = _clean_text(snippet_m.group(1)) if snippet_m else title
        if title:
            results.append({
                "title": title, "snippet": snippet[:500],
                "url": url, "source": "Bing CN", "type": "web",
            })

    return results[:max_results]


# ============================================================
# 搜狗搜索 (Sogou) — 带频率限制防反爬
# ============================================================

SOGOU_URL = "https://www.sogou.com/web"
_sogou_last_request = 0.0
SOGOU_MIN_INTERVAL = 3.0  # 两次请求最小间隔（秒）


def _sogou_rate_limit():
    """搜狗频率限制：距上次请求不足 3 秒则跳过本次搜索（非阻塞）"""
    global _sogou_last_request
    elapsed = time.time() - _sogou_last_request
    if elapsed < SOGOU_MIN_INTERVAL:
        return False  # 跳过本次搜索
    _sogou_last_request = time.time()
    return True


def _search_sogou(query: str, max_results: int, time_range: str = "auto") -> list:
    """搜狗网页搜索 — 中文查询准确度最高，带频率限制防反爬"""
    if not _sogou_rate_limit():
        return []  # 频率限制：跳过本次搜索

    params = {"query": query}
    # 时效性查询：按时间排序
    if time_range != "auto" or _is_time_sensitive(query):
        params["tsn"] = "1"  # 搜狗时间排序参数
    # 时间范围映射
    if time_range == "day":
        params["tsn"] = "4"  # 一天内
    elif time_range == "week":
        params["tsn"] = "3"  # 一周内

    try:
        session = _get_sogou_session()
        resp = session.get(
            SOGOU_URL,
            params=params,
            headers={"Referer": "https://www.sogou.com/"},
            timeout=ENGINE_TIMEOUT["sogou"],
        )
        resp.encoding = resp.apparent_encoding or "utf-8"
        if resp.status_code != 200:
            return []
        # 检测反爬页面：内容太短说明被拦截
        if len(resp.text) < 8000:
            return []
    except Exception:
        return []

    return _parse_sogou_html(resp.text, max_results)


def _parse_sogou_html(html: str, max_results: int) -> list:
    """解析 Sogou 搜索结果 HTML"""
    results = []

    try:
        from lxml import etree
        tree = etree.HTML(html)

        for vr in tree.xpath('//div[contains(@class,"vrwrap")]'):
            if len(results) >= max_results:
                break

            # --- 标题 ---
            h3_a = vr.xpath('.//h3/a')
            title = _clean_text(h3_a[0].xpath('string()') or "") if h3_a else ""

            # --- URL ---
            href = h3_a[0].get("href", "") if h3_a else ""
            url = _resolve_sogou_url(href)

            # --- 摘要 ---
            snippet = ""
            # 优先 star-wiki（富文本摘要）
            for el in vr.xpath('.//*[contains(@class,"star-wiki")] | .//*[contains(@class,"space-txt")]'):
                text = _clean_text(el.xpath('string()') or "")
                if len(text) > len(snippet):
                    snippet = text
            # 回退: 找任意长文本元素
            if not snippet:
                for el in vr.xpath('.//p | .//div'):
                    text = _clean_text(el.xpath('string()') or "")
                    if len(text) > 60 and text != title:
                        snippet = text
                        break

            # --- 来源/域名 ---
            source = "Sogou"
            cite_el = vr.xpath('.//cite')
            if cite_el:
                cite_text = _clean_text(cite_el[0].xpath('string()') or "")
                # 提取域名部分
                domain_match = re.match(r'^([\w.-]+)', cite_text)
                if domain_match:
                    source = domain_match.group(1)
                    if not url and cite_text.startswith("http"):
                        url = cite_text.split()[0]
            # 或者从 URL 提取域名
            if source == "Sogou" and url:
                parsed = urllib.parse.urlparse(url)
                source = parsed.netloc or "Sogou"

            # --- 日期 ---
            date_text = ""
            for el in vr.xpath('.//cite | .//*[contains(@class,"time")] | .//*[contains(@class,"date")]'):
                text = _clean_text(el.xpath('string()') or "")
                date_text = _extract_date(text)
                if date_text:
                    break
            if date_text:
                snippet = f"📅 {date_text} | {snippet}"

            if title:
                results.append({
                    "title": title,
                    "snippet": snippet[:500] if snippet else title,
                    "url": url,
                    "source": source,
                    "type": "web",
                })

        return results[:max_results]

    except Exception:
        pass

    # lxml 回退 — 简单 regex
    return _parse_sogou_html_regex(html, max_results)


def _parse_sogou_html_regex(html: str, max_results: int) -> list:
    """Sogou HTML regex 回退解析"""
    results = []
    # 每个结果在 <div class="vrwrap"> 中
    blocks = re.findall(r'<div[^>]*class="[^"]*vrwrap[^"]*"[^>]*>(.*?)(?=<div[^>]*class="[^"]*vrwrap|$)', html, re.DOTALL)
    if not blocks:
        blocks = [html]  # fallback: 整个页面搜索

    for block in blocks:
        if len(results) >= max_results:
            break
        # 标题
        title_m = re.search(r'<h3[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL)
        if not title_m:
            continue
        title = _clean_text(title_m.group(2))
        url = _resolve_sogou_url(title_m.group(1))
        # 摘要
        snippet_m = re.search(r'<p[^>]*class="[^"]*(?:star-wiki|space-txt)[^"]*"[^>]*>(.*?)</p>', block, re.DOTALL)
        snippet = _clean_text(snippet_m.group(1)) if snippet_m else title
        if title:
            results.append({
                "title": title,
                "snippet": snippet[:500],
                "url": url,
                "source": "Sogou",
                "type": "web",
            })

    return results[:max_results]


def _resolve_sogou_url(href: str) -> str:
    """解析 Sogou 链接：处理相对路径和跳转链接"""
    if not href:
        return ""
    # 已经是绝对 URL
    if href.startswith("http://") or href.startswith("https://"):
        return href
    # Sogou 跳转链接 /link?url=...
    if href.startswith("/link?url="):
        parsed = urllib.parse.urlparse(href)
        params = urllib.parse.parse_qs(parsed.query)
        target = params.get("url", [None])[0]
        if target:
            return target
    # 其他相对路径
    if href.startswith("/"):
        return f"https://www.sogou.com{href}"
    return href


# ============================================================
# 360 搜索 (so.com) — 国内可访问，中文准确
# ============================================================

SO360_URL = "https://www.so.com/s"


def _search_so360(query: str, max_results: int, time_range: str = "auto") -> list:
    """360 搜索，国内网络可访问，中文处理准确"""
    params = {"q": query}
    # 时效性查询：按时间排序
    if time_range != "auto" or _is_time_sensitive(query):
        params["sort"] = "date"
    # 时间范围
    if time_range == "day":
        params["sort"] = "date"
        params["date"] = "today"
    elif time_range == "week":
        params["sort"] = "date"
        params["date"] = "week"

    try:
        resp = _requests.get(
            SO360_URL,
            params=params,
            headers=HEADERS,
            timeout=ENGINE_TIMEOUT["bing"],
        )
        resp.encoding = resp.apparent_encoding or "utf-8"
        if resp.status_code != 200:
            return []
    except Exception:
        return []

    return _parse_so360_html(resp.text, max_results)


def _parse_so360_html(html: str, max_results: int) -> list:
    """解析 360 搜索结果"""
    results = []

    try:
        from lxml import etree
        tree = etree.HTML(html)

        for item in tree.xpath('//li[contains(@class,"res-list")]'):
            if len(results) >= max_results:
                break

            # 标题
            h3_a = item.xpath('.//h3/a')
            if not h3_a:
                continue
            title = _clean_text(h3_a[0].xpath('string()') or "")
            href = h3_a[0].get("href", "")

            # URL 解析：360 跳转链接 → 真实 URL
            url = _resolve_so360_url(href)

            # 摘要 — 360 有两种结果格式: res-desc 和 res-list-summary
            snippet = ""
            desc = item.xpath('.//*[contains(@class,"res-desc")] | .//*[contains(@class,"res-list-summary")]')
            if desc:
                snippet = _clean_text(desc[0].xpath('string()') or "")
            # 如果还是没有摘要，找任意较长的文本
            if not snippet:
                for el in item.xpath('.//*'):
                    text = _clean_text(el.xpath('string()') or "")
                    if len(text) > 60 and text != title:
                        snippet = text
                        break

            # 来源
            source = "360搜索"
            cite_el = item.xpath('.//cite | .//*[contains(@class,"res-linkinfo")]')
            if cite_el:
                cite_text = _clean_text(cite_el[0].xpath('string()') or "")
                if cite_text:
                    source = cite_text.split()[0] if cite_text else "360搜索"
            if source == "360搜索" and url:
                parsed = urllib.parse.urlparse(url)
                source = parsed.netloc or "360搜索"

            # --- 日期 ---
            date_text = ""
            for el in item.xpath('.//*[contains(@class,"res-linkinfo")] | .//*[contains(@class,"g-c-gray")]'):
                text = _clean_text(el.xpath('string()') or "")
                date_text = _extract_date(text)
                if date_text:
                    break
            if date_text:
                snippet = f"📅 {date_text} | {snippet}"

            if title:
                results.append({
                    "title": title,
                    "snippet": snippet[:500] if snippet else title,
                    "url": url,
                    "source": source,
                    "type": "web",
                })

        return results[:max_results]
    except Exception:
        pass

    # Regex fallback
    blocks = re.findall(
        r'<li[^>]*class="[^"]*res-list[^"]*"[^>]*>(.*?)</li>',
        html, re.DOTALL,
    )
    for block in blocks:
        if len(results) >= max_results:
            break
        title_m = re.search(r'<h3[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL)
        if not title_m:
            continue
        title = _clean_text(title_m.group(2))
        url = _resolve_so360_url(title_m.group(1))
        desc_m = re.search(
            r'<[^>]*class="[^"]*(?:res-desc|res-list-summary)[^"]*"[^>]*>(.*?)</(?:p|div)>',
            block, re.DOTALL,
        )
        snippet = _clean_text(desc_m.group(1)) if desc_m else title
        if title:
            results.append({
                "title": title,
                "snippet": snippet[:500],
                "url": url,
                "source": "360搜索",
                "type": "web",
            })

    return results[:max_results]


def _resolve_so360_url(href: str) -> str:
    """解析 360 跳转链接 → 提取真实 URL"""
    if not href:
        return ""
    if href.startswith("http://") or href.startswith("https://"):
        # 如果不是 so.com 域名，直接返回
        if "so.com/link" not in href and "ai.so.com" not in href:
            return href
    # 360 跳转链接中的真实 URL（如果有 m= 参数是编码过的）
    return href  # 360 的跳转链接较复杂，直接保留原始链接


# ============================================================
# 搜狗微信搜索 (weixin.sogou.com) — 微信公众号文章
# ============================================================

WEIXIN_URL = "https://weixin.sogou.com/weixin"


def _search_weixin(query: str, max_results: int, time_range: str = "auto") -> list:
    """搜狗微信搜索 — 微信公众号文章，中文内容极丰富"""
    try:
        resp = _requests.get(
            WEIXIN_URL,
            params={"query": query, "type": 2},
            headers=HEADERS,
            timeout=ENGINE_TIMEOUT["sogou"],
        )
        resp.encoding = resp.apparent_encoding or "utf-8"
        if resp.status_code != 200:
            return []
        if len(resp.text) < 5000:
            return []
    except Exception:
        return []

    return _parse_weixin_html(resp.text, max_results)


def _parse_weixin_html(html: str, max_results: int) -> list:
    """解析搜狗微信搜索结果"""
    results = []

    try:
        from lxml import etree
        tree = etree.HTML(html)

        for item in tree.xpath('//li[contains(@class,"news-item")] | //ul[contains(@class,"news-list")]/li'):
            if len(results) >= max_results:
                break

            # 标题
            h3_a = item.xpath('.//h3/a | .//a[contains(@class,"tit")]')
            title = _clean_text(h3_a[0].xpath('string()') or "") if h3_a else ""
            href = h3_a[0].get("href", "") if h3_a else ""

            # URL 解析
            url = _resolve_sogou_url(href)

            # 摘要
            snippet = ""
            for sel in ['.//p[contains(@class,"txt")]', './/p[contains(@class,"info")]', './/dd', './/p']:
                elems = item.xpath(sel)
                if elems:
                    text = _clean_text(elems[0].xpath('string()') or "")
                    if len(text) > 20:
                        snippet = text
                        break

            # 来源（公众号名称）
            source = "微信公众号"
            account_el = item.xpath('.//span[contains(@class,"account")] | .//span[contains(@class,"wx-name")] | .//a[contains(@class,"account")]')
            if account_el:
                account_name = _clean_text(account_el[0].xpath('string()') or "")
                if account_name:
                    source = account_name

            # 日期
            date_text = ""
            for el in item.xpath('.//*[contains(@class,"date")] | .//*[contains(@class,"time")] | .//span[last()]'):
                text = _clean_text(el.xpath('string()') or "")
                date_text = _extract_date(text)
                if date_text:
                    break
            if date_text:
                snippet = f"📅 {date_text} | {snippet}"

            if title:
                results.append({
                    "title": title,
                    "snippet": snippet[:500] if snippet else title,
                    "url": url,
                    "source": source,
                    "type": "web",
                })

        return results[:max_results]
    except Exception:
        pass

    # Regex fallback
    items = re.findall(r'<li[^>]*class="[^"]*news-item[^"]*"[^>]*>(.*?)</li>', html, re.DOTALL)
    if not items:
        items = re.findall(r'<li>(.*?)</li>', html, re.DOTALL)

    for item in items:
        if len(results) >= max_results:
            break
        title_m = re.search(r'<h3[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', item, re.DOTALL)
        if not title_m:
            continue
        title = _clean_text(title_m.group(2))
        url = _resolve_sogou_url(title_m.group(1))
        snippet_m = re.search(r'<p[^>]*class="[^"]*txt[^"]*"[^>]*>(.*?)</p>', item, re.DOTALL)
        snippet = _clean_text(snippet_m.group(1)) if snippet_m else title
        if title:
            results.append({
                "title": title,
                "snippet": snippet[:500],
                "url": url,
                "source": "微信公众号",
                "type": "web",
            })

    return results[:max_results]


# ============================================================
# Bing 搜索
# ============================================================

BING_URL = "https://www.bing.com/search"


def _search_bing(query: str, max_results: int, time_range: str = "auto") -> list:
    """Bing 搜索 — 使用排除词过滤噪音（旅游、百科等）"""
    # 检测中文查询：自动加排除词防止"北京邮电大学"被当作"北京"城市旅游
    actual_query = query
    if _is_chinese_query(query):
        # 将查询中出现的城市名/地名后面加排除词，减少歧义
        exclude_terms = []
        # 如果查询不是明确在搜旅游/景点，排除旅游相关噪音
        travel_keywords = ['旅游', '景点', '攻略', '打卡', '门票', '旅行社', '一日游']
        if not any(kw in query for kw in travel_keywords):
            exclude_terms = ['旅游', '景点', '攻略', '免费']
        if exclude_terms:
            actual_query = query + ' ' + ' '.join(f'-{t}' for t in exclude_terms)

    try:
        bing_params = {
            "q": actual_query,
            "count": max_results,
            "setmkt": "zh-CN",
        }
        # 时间范围 → Bing tbs 参数
        if time_range == "day":
            bing_params["tbs"] = "qdr:d"
        elif time_range == "week":
            bing_params["tbs"] = "qdr:w"
        elif time_range == "month":
            bing_params["tbs"] = "qdr:m"
        elif time_range == "year":
            bing_params["tbs"] = "qdr:y"
        elif _is_time_sensitive(query):
            bing_params["tbs"] = "qdr:w"  # 默认一周

        resp = _requests.get(
            BING_URL,
            params=bing_params,
            headers=HEADERS,
            timeout=ENGINE_TIMEOUT["bing"],
        )
        resp.encoding = resp.apparent_encoding or "utf-8"
        if resp.status_code != 200:
            return []
    except Exception:
        return []

    return _parse_bing_html(resp.text, max_results)


def _parse_bing_html(html: str, max_results: int) -> list:
    """解析 Bing 搜索结果"""
    results = []

    try:
        from lxml import etree
        tree = etree.HTML(html)
        for item in tree.xpath('//li[contains(@class,"b_algo")]'):
            if len(results) >= max_results:
                break

            title_el = item.xpath('.//h2/a')
            if not title_el:
                continue
            title = _clean_text(title_el[0].xpath('string()') or "")
            url = (title_el[0].get("href") or "").strip()

            # 摘要
            snippet = ""
            cap = item.xpath('.//div[contains(@class,"b_caption")]')
            if cap:
                snippet = _clean_text(cap[0].xpath('string()') or "")
            # 如果是跳转链接，尝试解析真实 URL
            if url and "bing.com" not in url and not url.startswith("http"):
                url = url

            # --- 日期 ---
            date_text = ""
            for span in item.xpath('.//span[contains(@class,"news_dt")] | .//span[contains(@class,"faded")]'):
                date_text = _extract_date(_clean_text(span.xpath('string()') or ""))
                if date_text:
                    break
            if date_text:
                snippet = f"📅 {date_text} | {snippet}"

            if title and not _is_noise_result(title, snippet):
                results.append({
                    "title": title,
                    "snippet": snippet[:500],
                    "url": url,
                    "source": "Bing",
                    "type": "web",
                })

        return results[:max_results]
    except Exception:
        pass

    # Regex fallback
    items = re.findall(
        r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>(.*?)</li>',
        html, re.DOTALL,
    )
    for item in items:
        if len(results) >= max_results:
            break
        title_m = re.search(r'<h2[^>]*><a[^>]*href="([^"]*)"[^>]*>(.*?)</a></h2>', item, re.DOTALL)
        if not title_m:
            continue
        title = _clean_text(title_m.group(2))
        url = title_m.group(1)
        snippet_m = re.search(r'<p[^>]*>(.*?)</p>', item, re.DOTALL)
        snippet = _clean_text(snippet_m.group(1)) if snippet_m else ""

        if title and not _is_noise_result(title, snippet):
            results.append({
                "title": title,
                "snippet": snippet[:500],
                "url": url,
                "source": "Bing",
                "type": "web",
            })

    return results[:max_results]


def _is_noise_result(title: str, snippet: str) -> bool:
    """过滤明显不相关的结果（Bing 对中文地名分词错误时会产生大量旅游百科结果）"""
    combined = title + snippet
    # 旅游/百科类噪声（当用户不是在搜这些时）
    travel_noise = [
        "旅游攻略", "必去景点", "必打卡", "旅行社",
        "免费景点", "好玩的地方", "游玩攻略",
        "人民政府门户网站", "人民政府",
        "百度百科", "百度地图",
    ]
    for kw in travel_noise:
        if kw in combined:
            return True
    # 标题就是"XX市_百度百科"或"XX旅游攻略"时必过滤
    if re.search(r'^[一-鿿]{2,4}[市省区]?_百度百科$', title):
        return True
    if re.search(r'[一-鿿]{2,4}旅游|[一-鿿]{2,4}攻略', title):
        return True
    # 行政区划首页（如"北京市人民政府门户网站"）
    if re.search(r'^[一-鿿]{2,4}[市省区]', title) and '人民政府' in title:
        return True
    return False


# ============================================================
# 微博热搜 (Weibo Hot Search)
# ============================================================

WEIBO_HOT_URL = "https://weibo.com/ajax/side/hotSearch"


def _search_weibo_hot(query: str, max_results: int, time_range: str = "auto") -> list:
    """微博热搜 — JSON 接口，实时热搜榜单"""
    try:
        resp = _requests.get(
            WEIBO_HOT_URL,
            headers={**HEADERS, "Referer": "https://weibo.com/"},
            timeout=5,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        if not data or data.get("ok") != 1:
            return []

        topics = data.get("data", {}).get("realtime", [])
        if not topics:
            return []

        results = []
        # 去除热搜/热门等泛词，提取用户真正关心的关键词
        query_clean = re.sub(r'热搜|热门|热点|今天|最新|有什么|什么|现在', '', query).strip()
        # 如果清理后只剩很短的关键词或为空，说明用户就是想看热搜榜
        want_full_list = len(query_clean) <= 2

        for topic in topics:
            if len(results) >= max_results:
                break
            word = topic.get("word", "")
            hot_score = topic.get("num", 0)

            # 如果用户想看完整榜单，不过滤
            if not want_full_list and query_clean:
                # 检查热搜词是否包含用户的查询关键词
                if query_clean not in word:
                    # 把热搜词中的 emoji/符号去掉做二次匹配
                    clean_word = re.sub(r'[^一-鿿\w]', '', word)
                    if query_clean not in clean_word:
                        continue

            url = f"https://s.weibo.com/weibo?q={urllib.parse.quote(word)}"
            results.append({
                "title": word,
                "snippet": f"🔥 热度: {_format_hot_num(hot_score)} | 微博实时热搜",
                "url": url,
                "source": "微博热搜",
                "type": "hot",
            })

        # 如果过滤后没有匹配的（且用户有具体查询），也返回空让其他引擎补充
        if want_full_list and not results:
            for topic in topics[:max_results]:
                word = topic.get("word", "")
                hot_score = topic.get("num", 0)
                url = f"https://s.weibo.com/weibo?q={urllib.parse.quote(word)}"
                results.append({
                    "title": word,
                    "snippet": f"🔥 热度: {_format_hot_num(hot_score)} | 微博实时热搜",
                    "url": url,
                    "source": "微博热搜",
                    "type": "hot",
                })

        return results[:max_results]
    except Exception:
        return []


def _format_hot_num(num) -> str:
    """格式化热度数字"""
    try:
        n = int(num)
        if n >= 10000:
            return f"{n/10000:.0f}万"
        return str(n)
    except (ValueError, TypeError):
        return str(num) if num else "未知"


# ============================================================
# 百度新闻搜索 (Baidu News)
# ============================================================

BAIDU_NEWS_URL = "https://news.baidu.com/ns"


def _search_baidu_news(query: str, max_results: int, time_range: str = "auto") -> list:
    """百度新闻搜索 — 按时间排序的新闻聚合"""
    params = {
        "word": query,
        "pn": 0,
        "rn": max_results + 2,
    }
    # 时间范围：百度新闻 rtt 参数 (1=一天, 4=一周, 7=一月)
    if time_range == "day":
        params["rtt"] = "1"
        params["pd"] = "news"
    elif time_range == "week":
        params["rtt"] = "4"
        params["pd"] = "news"
    elif time_range == "month":
        params["rtt"] = "7"
        params["pd"] = "news"
    else:
        params["pd"] = "news"  # 默认新闻模式
        params["rtt"] = "4"    # 默认一周

    params["cl"] = "2"  # 按时间排序

    try:
        resp = _requests.get(
            BAIDU_NEWS_URL,
            params=params,
            headers={**HEADERS, "Accept-Language": "zh-CN,zh;q=0.9"},
            timeout=10,
        )
        resp.encoding = resp.apparent_encoding or "utf-8"
        if resp.status_code != 200:
            return []
        if len(resp.text) < 3000:
            return []
    except Exception:
        return []

    return _parse_baidu_news_html(resp.text, max_results)


def _parse_baidu_news_html(html: str, max_results: int) -> list:
    """解析百度新闻搜索结果"""
    results = []

    try:
        from lxml import etree
        tree = etree.HTML(html)

        for item in tree.xpath('//div[contains(@class,"result")]'):
            if len(results) >= max_results:
                break

            # 标题和链接
            title_el = item.xpath('.//h3/a')
            if not title_el:
                continue
            title = _clean_text(title_el[0].xpath('string()') or "")
            href = title_el[0].get("href", "")

            # 摘要
            snippet = ""
            for sel in ['.//div[contains(@class,"c-summary")]', './/div[contains(@class,"c-abstract")]', './/p']:
                elems = item.xpath(sel)
                if elems:
                    snippet = _clean_text(elems[0].xpath('string()') or "")
                    if len(snippet) > 20:
                        break

            # 来源和时间
            source = "百度新闻"
            date_text = ""
            info_el = item.xpath('.//div[contains(@class,"c-info")] | .//p[contains(@class,"c-author")]')
            if info_el:
                info_text = _clean_text(info_el[0].xpath('string()') or "")
                # 提取来源和日期
                parts = info_text.split()
                if parts:
                    source = parts[0]
                date_text = _extract_date(info_text)

            if date_text:
                snippet = f"📅 {date_text} | {snippet}"

            if title:
                results.append({
                    "title": title,
                    "snippet": snippet[:500] if snippet else title,
                    "url": href,
                    "source": source,
                    "type": "news",
                })

        return results[:max_results]
    except Exception:
        pass

    # Regex fallback for Baidu News
    blocks = re.findall(
        r'<div[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)(?=<div[^>]*class="[^"]*result|$)',
        html, re.DOTALL,
    )
    for block in blocks:
        if len(results) >= max_results:
            break
        title_m = re.search(r'<h3[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL)
        if not title_m:
            continue
        title = _clean_text(title_m.group(2))
        url = title_m.group(1)
        snippet_m = re.search(
            r'<[^>]*class="[^"]*(?:c-summary|c-abstract)[^"]*"[^>]*>(.*?)</(?:div|p)>',
            block, re.DOTALL,
        )
        snippet = _clean_text(snippet_m.group(1)) if snippet_m else title
        if title:
            results.append({
                "title": title,
                "snippet": snippet[:500],
                "url": url,
                "source": "百度新闻",
                "type": "news",
            })

    return results[:max_results]


# ============================================================
# 搜狗新闻搜索 (Sogou News)
# ============================================================

SOGOU_NEWS_URL = "https://news.sogou.com/news"


def _search_sogou_news(query: str, max_results: int, time_range: str = "auto") -> list:
    """搜狗新闻搜索 — 百度新闻备用引擎"""
    params = {"query": query}
    # 时间范围
    if time_range == "day":
        params["tsn"] = "4"
    elif time_range == "week":
        params["tsn"] = "3"
    elif time_range == "month":
        params["tsn"] = "2"
    elif time_range != "auto":
        params["tsn"] = "1"

    try:
        resp = _requests.get(
            SOGOU_NEWS_URL,
            params=params,
            headers={**HEADERS, "Referer": "https://news.sogou.com/"},
            timeout=10,
        )
        resp.encoding = resp.apparent_encoding or "utf-8"
        if resp.status_code != 200:
            return []
        if len(resp.text) < 3000:
            return []
    except Exception:
        return []

    return _parse_sogou_news_html(resp.text, max_results)


def _parse_sogou_news_html(html: str, max_results: int) -> list:
    """解析搜狗新闻搜索结果"""
    results = []

    try:
        from lxml import etree
        tree = etree.HTML(html)

        for item in tree.xpath('//div[contains(@class,"news-item")] | //li[contains(@class,"news-item")]'):
            if len(results) >= max_results:
                break

            title_el = item.xpath('.//h3/a | .//a[contains(@class,"tit")]')
            if not title_el:
                continue
            title = _clean_text(title_el[0].xpath('string()') or "")
            href = title_el[0].get("href", "")
            url = _resolve_sogou_url(href)

            snippet = ""
            for sel in ['.//p[contains(@class,"txt")]', './/div[contains(@class,"abstract")]', './/p']:
                elems = item.xpath(sel)
                if elems:
                    snippet = _clean_text(elems[0].xpath('string()') or "")
                    if len(snippet) > 20:
                        break

            source = "搜狗新闻"
            date_text = ""
            info_el = item.xpath('.//span[contains(@class,"time")] | .//span[contains(@class,"source")] | .//cite')
            if info_el:
                info_text = _clean_text(info_el[0].xpath('string()') or "")
                date_text = _extract_date(info_text)

            if date_text:
                snippet = f"📅 {date_text} | {snippet}"

            if title:
                results.append({
                    "title": title,
                    "snippet": snippet[:500] if snippet else title,
                    "url": url,
                    "source": source,
                    "type": "news",
                })

        return results[:max_results]
    except Exception:
        pass

    # Regex fallback
    blocks = re.findall(r'<div[^>]*class="[^"]*news-item[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
    for block in blocks:
        if len(results) >= max_results:
            break
        title_m = re.search(r'<h3[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL)
        if not title_m:
            continue
        title = _clean_text(title_m.group(2))
        url = _resolve_sogou_url(title_m.group(1))
        snippet_m = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
        snippet = _clean_text(snippet_m.group(1)) if snippet_m else title
        if title:
            results.append({
                "title": title,
                "snippet": snippet[:500],
                "url": url,
                "source": "搜狗新闻",
                "type": "news",
            })

    return results[:max_results]


# ============================================================
# (DuckDuckGo 已移除 — 不再使用)
# ============================================================
