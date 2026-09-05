# 小金库 — FastAPI 后端 + 静态前端 的单容器镜像
#
# 在仓库根目录执行：
#   docker build -t vault .
#   docker run -d --name vault -p 6011:6011 -v vault-data:/app/data vault
# 或直接用同目录 docker-compose.yml：
#   docker compose up -d --build
#
# 说明：
#   - 数据文件 data/inventory.json 由 .dockerignore 排除，绝不打进镜像（隐私）
#   - 后端缺失数据文件时会自动创建，持久化靠挂载卷 /app/data
#   - main.py 里 uvicorn 已绑定 0.0.0.0:6011，与本地 `uv run python main.py` 行为一致

# FROM pengbotao:miniconda
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 1) 依赖层：先只复制清单文件，之后改代码不会破坏这一层的缓存
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# 2) 代码层：后端入口 + 静态前端（FastAPI 在 / 托管 frontend/）
COPY main.py ./
COPY frontend ./frontend

# 3) 数据目录：镜像内留一个可写的空挂载点（真实数据只存卷里）
RUN mkdir -p data && chown -R 1000:1000 /app
USER 1000:1000

EXPOSE 6011

# 健康检查：请求 /（前端页）判定存活
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6011/', timeout=3)"

CMD ["python", "main.py"]
