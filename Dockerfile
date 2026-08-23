# syntax=docker/dockerfile:1.6
# ------------------------------------------------------------------
# webstock Backend Dockerfile（兼容 Alibaba Cloud Linux 3 = RHEL8 / centos8 血统）
# 多阶段构建：Builder 安装全部编译依赖 → Runtime 仅保留运行时，镜像更小。
# Python 3.11-slim 基于 Debian Bookworm；Alinux 3 上 Docker CE 18+ 可正常跑任何 glibc 镜像。
# ------------------------------------------------------------------

# -------- Stage 1: 安装 Python 依赖 + 构建前端静态资源 --------
FROM python:3.11-slim-bookworm AS builder
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UVICORN_VERSION=0.29.0

WORKDIR /build

# 装编译依赖（pytorch/tensorflow 多数是 wheel，保险起见）
RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends \
        build-essential curl ca-certificates pkg-config git \
        libopenblas-dev libgomp1 \
 && rm -rf /var/lib/apt/lists/*

# 后端 Python 依赖（单独 COPY 利用缓存分层）
COPY backend/requirements.txt /build/backend/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefix=/opt/venv --break-system-packages -r /build/backend/requirements.txt

# 源码拷贝
COPY src /build/src
COPY backend /build/backend

# -------- Stage 2: 前端构建（Node 20 alpine 小巧） --------
FROM node:20-alpine AS fe-builder
WORKDIR /fe
COPY frontend/package.json frontend/vite.config.js frontend/index.html ./
COPY frontend/src ./src
RUN --mount=type=cache,target=/root/.npm \
    npm install --no-audit --no-fund --loglevel=error && npm run build

# -------- Stage 3: 最终运行镜像 --------
FROM python:3.11-slim-bookworm AS runtime
LABEL maintainer="kangyincheng" \
      description="webstock (FastAPI + Vue3) runtime image"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH=/opt/venv/bin:$PATH \
    APP_HOME=/app \
    PORT=8000

# 运行时只保留最小依赖
# libgomp1 → pytorch/tensorflow 需要；ca-certificates → baostock/tushare HTTPS；libopenblas → numpy/scipy
RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends \
        ca-certificates curl libgomp1 libopenblas0 tini \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -r app && useradd -r -g app -d /app app

WORKDIR /app

# Python 依赖（从 builder 复制整个 /opt/venv）
COPY --from=builder /opt/venv /opt/venv

# 业务代码
COPY --chown=app:app src /app/src
COPY --chown=app:app backend /app/backend

# 前端 dist（Nginx 容器/宿主机也会挂载；这里一并放进去供 FastAPI fallback 托管）
COPY --from=fe-builder --chown=app:app /fe/dist /app/frontend/dist

# 数据/模型持久化目录
RUN mkdir -p /app/backend/data /app/backend/models \
 && chown -R app:app /app

USER app
EXPOSE 8000

# 使用 tini 当 PID 1，解决孤儿进程
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", \
     "gunicorn -k uvicorn.workers.UvicornWorker -w ${WORKERS:-2} -b 0.0.0.0:${PORT:-8000} \
      --timeout 600 --keep-alive 30 --max-requests 1000 --max-requests-jitter 200 \
      backend.app.main:app"]
