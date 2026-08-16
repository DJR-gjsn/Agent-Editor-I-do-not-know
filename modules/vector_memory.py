"""
Vector Memory 向量记忆模块
embeddings_index: 将文档向量化并存入本地向量库
embeddings_search: 语义搜索，余弦相似度匹配 top-K
"""
import json
import math
import threading
import time

import requests as _requests
from flask import jsonify, request

from . import tool_registry
from .config import get_config
from .utils import get_request_api_config

# ============================================================
# 向量存储（线程安全）
# ============================================================
_lock = threading.RLock()
_store = []  # [{"id": str, "text": str, "embedding": list[float], "created_at": str}]
_next_id = 0


def _clear_store():
    """清空向量库"""
    global _store, _next_id
    with _lock:
        _store = []
        _next_id = 0


def _get_stats() -> dict:
    """获取向量库统计"""
    with _lock:
        dims = len(_store[0]["embedding"]) if _store else 0
        return {
            "doc_count": len(_store),
            "dimensions": dims,
            "total_chars": sum(len(d["text"]) for d in _store),
        }


# ============================================================
# Embedding API 调用
# ============================================================
def _get_embedding(text: str, api_base: str = None, api_key: str = None) -> list:
    """获取文本向量。优先用 API embeddings，不可用时回退到本地 TF-IDF"""
    cfg = get_config()
    req_cfg = get_request_api_config()
    base = api_base or req_cfg.get("api_base") or cfg["api_base"]
    key = api_key or req_cfg.get("api_key") or cfg["api_key"]

    # 尝试 API embeddings（仅首次，失败后跳过）
    global _api_available
    if _api_available:
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            }
            payload = {"model": "text-embedding-3-small", "input": text}
            resp = _requests.post(
                f"{base}/embeddings", headers=headers, json=payload, timeout=2,
            )
            if resp.status_code == 200:
                body = resp.json()
                return body["data"][0]["embedding"]
        except Exception:
            _api_available = False  # 失败后不再尝试

    # 回退：本地 TF-IDF 向量化
    return _tfidf_embed(text)


# ============================================================
# TF-IDF 本地向量化（无需 API，无需网络）
# ============================================================
_tfidf_vectorizer = None
_api_available = True  # 缓存 API 可用状态，失败一次后跳过


def _tfidf_embed(text: str) -> list:
    """TF-IDF 向量化，使用字符 n-gram 适配中文"""
    global _tfidf_vectorizer

    from sklearn.feature_extraction.text import TfidfVectorizer

    with _lock:
        corpus = [d["text"] for d in _store]
        corpus.append(text)

        try:
            # 字符级 n-gram (2-4) 对中文和英文混合文本都有效
            _tfidf_vectorizer = TfidfVectorizer(
                analyzer='char',
                ngram_range=(2, 4),
                max_features=512,
            )
            tfidf_matrix = _tfidf_vectorizer.fit_transform(corpus)
            vec = tfidf_matrix[-1].toarray()[0].tolist()

            # 更新所有已存储文档的向量
            if _store:
                for i, doc in enumerate(_store):
                    doc["embedding"] = tfidf_matrix[i].toarray()[0].tolist()

            return vec
        except Exception:
            return _fallback_hash(text, 512)


def _fallback_hash(text: str, dims: int = 256) -> list:
    """极端回退：字符级简单向量（每个维度基于字符哈希）"""
    import hashlib
    vec = [0.0] * dims
    chars = list(text)
    for i, ch in enumerate(chars):
        h = int(hashlib.md5(ch.encode()).hexdigest()[:8], 16)
        idx = (h + i * 31) % dims
        vec[idx] += 1.0
    # 归一化
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


# ============================================================
# 余弦相似度
# ============================================================
def _cosine_similarity(a: list, b: list) -> float:
    """两个向量的余弦相似度 (0~1, 越大越相似)"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ============================================================
# 工具定义
# ============================================================
INDEX_DEF = {
    "name": "embeddings_index",
    "description": (
        "将文档添加到向量知识库。传入文本内容，系统会自动向量化并存储。"
        "适合将重要信息、参考资料、对话摘要等存入知识库，供后续语义搜索使用。"
        "多次调用可积累多条文档。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "要添加到向量知识库的文档内容",
            },
        },
        "required": ["text"],
    },
}

SEARCH_DEF = {
    "name": "embeddings_search",
    "description": (
        "在向量知识库中进行语义搜索。根据查询内容，找到知识库中意思最相近的文档。"
        "不是关键词匹配，而是理解语义后找相关内容。"
        "适合查找之前存储的参考资料、对话记录、专业知识等。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索查询，用自然语言描述你想找什么",
            },
            "top_k": {
                "type": "integer",
                "description": "返回最相似的前几条结果，默认 3，最大 10",
                "default": 3,
            },
        },
        "required": ["query"],
    },
}


# ============================================================
# 工具执行器
# ============================================================
def _exec_index(args: dict) -> str:
    """AI 可调用：将文档加入向量库"""
    text = (args.get("text") or "").strip()
    if not text:
        return "错误: text 不能为空"
    if len(text) > 8000:
        return "错误: 文本过长（最多 8000 字符）"

    global _next_id
    try:
        embedding = _get_embedding(text)
    except Exception as e:
        return f"❌ 向量化失败: {e}"

    with _lock:
        doc_id = f"vec_{_next_id}"
        _next_id += 1
        _store.append({
            "id": doc_id,
            "text": text,
            "embedding": embedding,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        total = len(_store)

    preview = text[:100] + ("..." if len(text) > 100 else "")
    return f"✅ 已添加到向量知识库 (ID: {doc_id})\n当前共 {total} 条文档\n内容: {preview}"


def _exec_search(args: dict) -> str:
    """AI 可调用：语义搜索向量库"""
    query = (args.get("query") or "").strip()
    top_k = min(int(args.get("top_k", 3)), 10)

    if not query:
        return "错误: query 不能为空"

    with _lock:
        if not _store:
            return "📭 向量知识库为空。请先用 embeddings_index 添加文档。"

    # 向量化查询（在锁外执行，避免长时间持锁）
    try:
        query_emb = _get_embedding(query)
    except Exception as e:
        return f"❌ 查询向量化失败: {e}"

    # 计算相似度并排序
    with _lock:
        scored = []
        for doc in _store:
            score = _cosine_similarity(query_emb, doc["embedding"])
            scored.append((score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]

    lines = [f"🔍 语义搜索 '{query[:60]}' 的结果 (top {len(top)}):"]
    for i, (score, doc) in enumerate(top, 1):
        pct = f"{score * 100:.0f}%"
        text_preview = doc["text"][:200]
        lines.append(
            f"\n[{i}] 相似度: {pct} | {doc['created_at']}\n"
            f"    {text_preview}"
        )
        if len(doc["text"]) > 200:
            lines.append("    ...")

    return "\n".join(lines)


# ============================================================
# 注册工具
# ============================================================
tool_registry.register("embeddings_index", INDEX_DEF, _exec_index)
tool_registry.register("embeddings_search", SEARCH_DEF, _exec_search)


# ============================================================
# Flask 路由
# ============================================================
def register_routes(app, http_session=None):
    @app.route("/api/vector-memory/documents", methods=["GET", "POST"])
    def vm_documents():
        """列出文档 或 添加文档"""
        if request.method == "POST":
            data = request.get_json(force=True)
            text = (data.get("text") or "").strip()
            if not text:
                return jsonify({"success": False, "error": "text 不能为空"})
            # 支持传入 API 配置覆盖
            # 支持传入 API 配置覆盖
            if data.get("api_base"):
                _api_base_override = data["api_base"]
            if data.get("api_key"):
                _api_key_override = data["api_key"]
            result = _exec_index({"text": text})
            return jsonify({"success": True, "result": result})
        # GET
    def vm_list_docs():
        """列出向量库中的所有文档（不含向量数据）"""
        with _lock:
            docs = [{
                "id": d["id"],
                "text": d["text"][:200],
                "created_at": d["created_at"],
                "dimensions": len(d["embedding"]),
            } for d in _store]
        return jsonify({"success": True, "documents": docs, "count": len(docs)})

    @app.route("/api/vector-memory/documents", methods=["DELETE"])
    def vm_clear_docs():
        """清空向量库"""
        _clear_store()
        return jsonify({"success": True, "message": "向量库已清空"})

    @app.route("/api/vector-memory/search", methods=["POST"])
    def vm_search():
        """直接搜索向量库（非 AI 调用）"""
        data = request.get_json(force=True)
        query = (data.get("query") or "").strip()
        top_k = min(int(data.get("top_k", 3)), 10)

        if not query:
            return jsonify({"success": False, "error": "query 不能为空"})

        result = _exec_search({"query": query, "top_k": top_k})
        return jsonify({"success": True, "result": result})

    @app.route("/api/vector-memory/stats", methods=["GET"])
    def vm_stats():
        return jsonify({"success": True, "stats": _get_stats()})
