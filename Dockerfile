# Agent Editor — 公网部署镜像
# 生产服务器用 waitress（纯 Python 跨平台，支持并发；Flask 开发服务器不适用于生产）
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    FLASK_ENV=production

WORKDIR /app

# 系统依赖（编译部分 wheel 需要 gcc；多数包有预编译轮子）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 数据目录（docker-compose 用卷挂载持久化：SQLite/项目/向量库/MCP 配置）
RUN mkdir -p /app/data

EXPOSE 5000

# 生产服务器（server:app 由 waitress 导入，不触发 app.run——见 __main__ 保护）
CMD ["python", "-m", "waitress.serve", "--host=0.0.0.0", "--port=5000", "server:app"]
