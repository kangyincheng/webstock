#!/bin/bash
# ====== jeoj.com 快速构建脚本 ======

set -e

echo "=== 开始构建 webstock 服务 ==="

# 1. 停止现有服务
echo "停止现有服务..."
docker compose down 2>/dev/null || true

# 2. 使用国内镜像源优化构建
echo "使用国内镜像源加速构建..."

# 设置环境变量使用国内镜像
export HTTP_PORT=80
export HTTPS_PORT=443
export WORKERS=2

# 3. 构建服务（使用缓存和优化）
echo "构建服务（可能需要10-15分钟）..."
COMPOSE_DOCKER_CLI_BUILD=1 DOCKER_BUILDKIT=1 docker compose build --no-cache

# 4. 启动服务
echo "启动服务..."
docker compose up -d

# 5. 等待服务健康
echo "等待服务启动..."
sleep 5

# 6. 检查服务状态
echo "检查服务状态..."
docker compose ps

echo ""
echo "=== 构建完成 ==="
echo "HTTP 访问: http://www.jeoj.com"
echo "服务器健康检查: http://www.jeoj.com/api/system/healthz"
echo ""
echo "查看日志: docker compose logs -f"
echo "停止服务: docker compose down"