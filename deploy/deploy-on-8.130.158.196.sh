#!/usr/bin/env bash
# ============================================================================
# 「快速挽救脚本」—— 在 8.130.158.196 的 SSH 终端中直接 curl | bash 也行
# 作用：不管之前代码多旧、端口是不是被 502 旧 Nginx 占着，
#       一键停旧服务 → 拉最新代码 → 装依赖 → 启服务 → 自检公网可达
#
# 推荐用法（SSH 到 8.130.158.196 之后粘贴，把 TUSHARE= 换成你自己的）：
#   curl -fsSL https://raw.githubusercontent.com/kangyincheng/webstock/main/deploy-8.130.158.196.sh \
#        -o /tmp/deploy.sh && sudo TUSHARE_TOKEN=xxxxxxxxxxxxxxxxxx bash /tmp/deploy.sh
#  或者（如果分支还没合并，先本地 merge 一下）
# ============================================================================
set -euo pipefail
TUSHARE_TOKEN="${TUSHARE_TOKEN:-}"
SSL_EMAIL="${SSL_EMAIL:-admin@jeoj.com}"     # ← 改成你自己的通知邮箱
ENABLE_SSL="${ENABLE_SSL:-auto}"
PUBLIC_IP="8.130.158.196"
DOMAIN="www.jeoj.com"
APEX_DOMAIN="jeoj.com"
APP_DIR="/opt/webstock"

cat <<EOF
═══════════════════════════════════════════════════════════════════════════
  webstock @ ${PUBLIC_IP} · ${DOMAIN} · HTTPS + HSTS 全链路开启
  SSL 通知邮箱: ${SSL_EMAIL}  ·  ENABLE_SSL=${ENABLE_SSL}
═══════════════════════════════════════════════════════════════════════════
EOF

###############################################
# Step 0 · 立即杀死所有占着 80/8000 的旧进程（当前 502 的元凶）
###############################################
echo -e "\n\033[32m[0/8]\033[0m  释放 80 / 443 / 8000 端口..."
set +e
# 老 Nginx / Apache
if command -v systemctl >/dev/null 2>&1; then
  for svc in nginx httpd apache2; do
    systemctl is-active --quiet "$svc" 2>/dev/null && sudo systemctl stop "$svc"
    systemctl is-enabled --quiet "$svc" 2>/dev/null && sudo systemctl disable "$svc" 2>/dev/null || true
  done
fi
# 旧 webstock backend
systemctl is-active --quiet webstock 2>/dev/null && sudo systemctl stop webstock 2>/dev/null || true
# docker（可能开着老的 webstock 容器）
if command -v docker >/dev/null 2>&1; then
  sudo docker ps --format '{{.Names}}' | grep -i webstock | xargs -r -n1 sudo docker rm -f >/dev/null 2>&1 || true
fi
# lsof 兜底
if command -v lsof >/dev/null 2>&1; then
  PIDS=$(sudo lsof -ti tcp:80 -ti tcp:443 -ti tcp:8000 2>/dev/null | sort -u | tr '\n' ' ')
  if [[ -n "$PIDS" ]]; then
    echo "   杀旧监听: PIDs=$PIDS"
    sudo kill -9 $PIDS 2>/dev/null || true
    sleep 2
  fi
fi
set -e

###############################################
# Step 1 · 拉取 / 更新代码
###############################################
echo -e "\n\033[32m[1/8]\033[0m  拉取 GitHub 最新代码（kangyincheng/webstock 仓库）..."
sudo mkdir -p "$(dirname "$APP_DIR")"
if [[ -d "$APP_DIR/.git" ]]; then
  # 用户可能已经把代码拷上去过
  (cd "$APP_DIR" && git remote set-url origin https://github.com/kangyincheng/webstock.git 2>/dev/null || true)
  # pull 失败兜底: 直接 reset 到 main (main 或 master, 自动探测)
  (cd "$APP_DIR" && git fetch --depth=1 origin 2>&1 | tail -3)
  DEF_BRANCH=$(cd "$APP_DIR" && git remote show origin 2>/dev/null | sed -n '/HEAD branch/s/.*: //p')
  if [[ -z "$DEF_BRANCH" ]]; then DEF_BRANCH="main"; fi
  (cd "$APP_DIR" && git reset --hard "origin/${DEF_BRANCH}" 2>&1 | tail -3 || git reset --hard origin/main)
else
  sudo rm -rf "$APP_DIR"
  sudo git clone --depth=1 https://github.com/kangyincheng/webstock.git "$APP_DIR"
fi
sudo chown -R "$(id -u):$(id -g)" "$APP_DIR"
cd "$APP_DIR"
chmod +x deploy-alinux3.sh deploy-8.130.158.196.sh

###############################################
# Step 2 · 放行 firewalld / iptables
###############################################
echo -e "\n\033[32m[2/8]\033[0m  放行主机层防火墙..."
if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  sudo firewall-cmd --permanent --zone=public --add-service=http  2>/dev/null || true
  sudo firewall-cmd --permanent --zone=public --add-service=https 2>/dev/null || true
  sudo firewall-cmd --reload 2>/dev/null || true
  echo "   firewalld ✅"
fi
if command -v iptables >/dev/null 2>&1; then
  sudo iptables -C INPUT -p tcp --dport 80  -j ACCEPT 2>/dev/null || sudo iptables -I INPUT -p tcp --dport 80  -j ACCEPT
  sudo iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
  echo "   iptables ✅"
fi

###############################################
# Step 3 · 调用通用 deploy-alinux3.sh 完成 90% 工作
###############################################
echo -e "\n\033[32m[3/8]\033[0m  调用 deploy-alinux3.sh --mode=baremetal..."
ARGS=(--mode=baremetal --domain="${DOMAIN}" --ssl-email="${SSL_EMAIL}" --enable-ssl="${ENABLE_SSL}")
[[ -n "${TUSHARE_TOKEN}" ]] && ARGS+=(--tushare="${TUSHARE_TOKEN}")
bash deploy-alinux3.sh "${ARGS[@]}"

###############################################
# Step 4 · 健康检查
###############################################
echo -e "\n\033[32m[4/8]\033[0m  健康检查（本机 127.0.0.1:8000）..."
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS --max-time 5 http://127.0.0.1:8000/api/system/healthz >/dev/null; then
    echo "   backend ✅  alive"; break
  fi
  sleep 2
done

###############################################
# Step 5 · Nginx 配完 reload
###############################################
echo -e "\n\033[32m[5/8]\033[0m  Nginx 语法测试 + reload..."
sudo nginx -t 2>&1 | tail -3
sudo systemctl restart nginx
sleep 1
systemctl is-active --quiet nginx && echo "   nginx ✅ running" || { echo "   ❌ nginx 启动失败"; exit 1; }

###############################################
# Step 6 · 本机 80 端口自检（模拟真实客户端）
###############################################
echo -e "\n\033[32m[6/8]\033[0m  本机 80 端口 HTTP 200 自检..."
for i in 1 2 3 4 5; do
  CODE=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 6 http://127.0.0.1/ 2>/dev/null || true)
  [[ "$CODE" == "200" ]] && { echo "   ✅ HTTP 200 @ localhost"; break; }
  echo "   第 $i 次 CODE=$CODE，重试..."
  sleep 3
done

###############################################
# Step 7 · 关键 API 自检（ST 列表 / CBond 申购 / 热门板块）
###############################################
echo -e "\n\033[32m[7/8]\033[0m  业务接口冒烟（无 tushare token 时走 Mock）..."
for PATH in \
  "/api/system/healthz" \
  "/api/market/sector-heat" \
  "/api/cbond/subscribe" \
  "/api/favorites"; do
  CODE=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 8 -X POST \
    -H "Content-Type: application/json" \
    --data '{}' \
    "http://127.0.0.1${PATH}" 2>/dev/null || echo "000")
  echo "   POST $PATH  => HTTP $CODE"
done

###############################################
# Step 8 · 出口（含 HTTPS 301 检查）
###############################################
echo
echo "═══════════════════════════════════════════════════════════════════════════"
echo "   🎉 部署完成！"
for URL in "http://${DOMAIN}" "https://${DOMAIN}" "http://${APEX_DOMAIN}" "https://${APEX_DOMAIN}" "http://${PUBLIC_IP}"; do
  echo "     $URL"
done
echo
echo "   规范化跳转预期："
echo "     http://jeoj.com       → 301 → https://www.jeoj.com"
echo "     http://8.130.158.196  → 301 → https://www.jeoj.com （HTTPS 启用后）"
echo
echo "   常用命令："
echo "     查看后端日志    sudo journalctl -u webstock -fn 80"
echo "     重启后端        sudo systemctl restart webstock"
echo "     重启 Nginx      sudo systemctl restart nginx"
echo "     手动续期 SSL    sudo certbot renew --dry-run"
echo "     更新代码        cd ${APP_DIR} && git pull --ff-only"
echo "                       && sudo systemctl restart webstock"
echo
echo "   ⚠️  若浏览器仍提示不安全："
echo "      a) 阿里云安全组：TCP 443 必须放行 0.0.0.0/0"
echo "      b) 证书申请成功后，检查是否已在 /etc/letsencrypt/live/www.jeoj.com/"
echo "      c) 如启用 CDN：别打开 CDN 的「强制 HTTPS」让我们自己跳，避免 301 死循环"
echo "═══════════════════════════════════════════════════════════════════════════"
