#!/bin/bash
# ====== jeoj.com 快速启动脚本（国内镜像源优化）======

set -e

echo "=== 🚀 开始部署 webstock 服务 ==="

# 切换到项目目录
cd /var/www/webstock

# 1. 停止现有服务
echo "🛑 停止现有服务..."
docker compose down 2>/dev/null || true

# 2. 清理旧镜像
echo "🧹 清理旧镜像..."
docker rmi webstock:cpu 2>/dev/null || true

# 3. 设置环境变量
export HTTP_PORT=80
export HTTPS_PORT=443
export WORKERS=2

echo "⚙️  构建配置："
echo "   - 镜像源：清华 pip 镜像"
echo "   - 版本：CPU-only（避免 CUDA 下载）"
echo "   - 前端：淘宝 npm 镜像"
echo ""

# 4. 构建服务
echo "🔨 开始构建服务（预计 5-10 分钟）..."
COMPOSE_DOCKER_CLI_BUILD=1 DOCKER_BUILDKIT=1 docker compose build

# 5. 启动服务
echo "🚀 启动服务..."
docker compose up -d

# 6. 等待服务健康
echo "⏳ 等待服务启动（30秒）..."
sleep 5
for i in {1..6}; do
    if curl -fs http://localhost:80/api/system/healthz > /dev/null 2>&1; then
        echo "✅ 服务健康检查通过"
        break
    fi
    echo "   等待中... ($i/6)"
    sleep 5
done

# 7. 检查服务状态
echo ""
echo "📊 服务状态："
docker compose ps

# 8. 显示访问信息
echo ""
echo "=== 🎉 部署完成 ==="
echo ""
echo "🌐 访问地址："
echo "   HTTP:  http://www.jeoj.com"
echo "   直接IP: http://$(curl -s ifconfig.me)"
echo ""
echo "🔍 健康检查："
echo "   curl http://www.jeoj.com/api/system/healthz"
echo ""
echo "📝 管理命令："
echo "   查看日志: docker compose logs -f"
echo "   停止服务: docker compose down"
echo "   重启服务: docker compose restart"
echo ""
echo "⚡ 性能特性："
echo "   ✅ CPU-only 版本（快速启动）"
echo "   ✅ 国内镜像源加速"
echo "   ✅ 静态资源强缓存"
echo "   ✅ Gzip/Brotli 压缩"
echo "   ✅ WebSocket 长连接支持"
echo ""