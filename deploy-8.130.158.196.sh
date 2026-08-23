#!/usr/bin/env bash
# =====================================================================
# 专属部署脚本 · 目标 ECS：公网 8.130.158.196
# 系统：Alibaba Cloud Linux 3.2104 LTS 64 位
#
# 在 ECS 的 SSH 终端中直接执行：
#   1) 若无代码：  先 git clone，然后 bash deploy-8.130.158.196.sh --tushare=你的TOKEN
#   2) 已有代码：  直接 bash deploy-8.130.158.196.sh --tushare=你的TOKEN
#
# 可选模式（默认 baremetal，省资源、启动快、性能最好）：
#   --mode=baremetal   宿主机：Python 3.11 + Redis + Nginx + Systemd（推荐）
#   --mode=docker      Docker Compose：Nginx + FastAPI + Redis 三容器
# =====================================================================
set -euo pipefail

PUBLIC_IP="8.130.158.196"
DOMAIN="${DOMAIN:-www.jeoj.com}"      # ← 你的主域名
APEX_DOMAIN="${DOMAIN#www.}"
APP_DIR="/opt/webstock"
MODE="baremetal"
TUSHARE_TOKEN="${TUSHARE_TOKEN:-}"
SSL_EMAIL="${SSL_EMAIL:-admin@${APEX_DOMAIN}}"
ENABLE_SSL="${ENABLE_SSL:-auto}"
for arg in "$@"; do
  case "$arg" in
    --mode=*)       MODE="${arg#*=}" ;;
    --tushare=*)    TUSHARE_TOKEN="${arg#*=}" ;;
    --app-dir=*)    APP_DIR="${arg#*=}" ;;
    --ssl-email=*)  SSL_EMAIL="${arg#*=}" ;;
    --enable-ssl=*) ENABLE_SSL="${arg#*=}" ;;
    --domain=*)     DOMAIN="${arg#*=}" ;;
  esac
done

echo "▶ 目标公网 IP：${PUBLIC_IP}"
echo "▶ 主域名       ：${DOMAIN}（apex=${APEX_DOMAIN}）"
echo "▶ 部署模式     ：${MODE}"
echo "▶ 部署目录     ：${APP_DIR}"
echo "▶ SSL 通知邮箱 ：${SSL_EMAIL}"

###############################################
# 0. 公网可达性预检（ECS 内部自检出口连通性）
###############################################
echo
echo "[0/6] 预检安全组/防火墙放行 80/443 ..."
PUB_IP_OUT="$(curl -sS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
if [[ -n "$PUB_IP_OUT" && "$PUB_IP_OUT" != "$PUBLIC_IP" ]]; then
  echo "⚠️   本机出口 IP = ${PUB_IP_OUT}，与给定 ${PUBLIC_IP} 不一致（可能是 NAT / 弹性网卡场景，如确认无误可忽略）"
elif [[ -n "$PUB_IP_OUT" && "$PUB_IP_OUT" == "$PUBLIC_IP" ]]; then
  echo "✅ 本机出口 IP 匹配 ${PUBLIC_IP}"
fi

###############################################
# 1. Alinux 3 上可能还有旧的监听 80 的 nginx（当前 502）
#    先停掉任何冲突端口的进程
###############################################
echo
echo "[1/6] 清理占用 80/8000 的旧服务（当前探测到的 502 Nginx）..."
if command -v systemctl >/dev/null 2>&1; then
  # 停掉常见与我们冲突的旧 nginx/apache
  for svc in httpd nginx old-nginx; do
    if systemctl list-unit-files | grep -q "^${svc}.service"; then
      sudo systemctl stop    "${svc}"      2>/dev/null || true
      sudo systemctl disable "${svc}"      2>/dev/null || true
    fi
  done
fi
# 兜底：如果 80 还被绑，直接按 PID 杀（但别杀 sshd 22）
for PORT in 80 443 8000; do
  if command -v lsof >/dev/null 2>&1; then
    PIDS="$(sudo lsof -ti tcp:${PORT} 2>/dev/null || true)"
    if [[ -n "$PIDS" ]]; then
      echo "   端口 ${PORT} 仍被 PIDs=$PIDS 占用，发送 SIGTERM..."
      sudo kill -TERM $PIDS 2>/dev/null || true
      sleep 2
    fi
  fi
done

###############################################
# 2. 克隆/拉取最新代码
###############################################
echo
echo "[2/6] 拉取最新代码（GitHub：kangyincheng/webstock）..."
sudo mkdir -p "$(dirname "$APP_DIR")"
if [[ ! -d "$APP_DIR/.git" ]]; then
  sudo rm -rf "$APP_DIR"
  sudo git clone --depth=1 https://github.com/kangyincheng/webstock.git "$APP_DIR"
  sudo chown -R "$(id -u):$(id -g)" "$APP_DIR"
else
  (cd "$APP_DIR" && git fetch --depth=1 origin && git reset --hard origin/$(cd "$APP_DIR" && git rev-parse --abbrev-ref HEAD))
fi
cd "$APP_DIR"
sudo chmod +x deploy-alinux3.sh deploy-8.130.158.196.sh

###############################################
# 3. firewalld 放行 80/443
###############################################
echo
echo "[3/6] 放行 firewalld / iptables 的 80、443 ..."
if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  sudo firewall-cmd --permanent --add-service=http  --zone=public >/dev/null 2>&1 || true
  sudo firewall-cmd --permanent --add-service=https --zone=public >/dev/null 2>&1 || true
  sudo firewall-cmd --reload >/dev/null 2>&1 || true
  echo "✅ firewalld 已放行 http/https"
fi
# iptables 兜底（Alinux 3 早期版本可能只有 iptables）
if command -v iptables >/dev/null 2>&1; then
  sudo iptables -C INPUT -p tcp --dport 80  -j ACCEPT >/dev/null 2>&1 || sudo iptables -I INPUT -p tcp --dport 80  -j ACCEPT
  sudo iptables -C INPUT -p tcp --dport 443 -j ACCEPT >/dev/null 2>&1 || sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
  # 如存在 iptables-services，尝试保存
  command -v iptables-save >/dev/null 2>&1 && sudo iptables-save >/dev/null 2>&1 || true
  echo "✅ iptables 已放行 80/443"
fi

###############################################
# 4. 提示阿里云控制台安全组
###############################################
cat <<'SECURITY_GROUP_HINT'

┌────────────────────────────────────────────────────────────────────┐
│  ⚠️  重要：阿里云 ECS 控制台「安全组」还需放行（控制台侧）            │
│    入方向规则：                                                      │
│       协议类型  端口范围  授权对象         优先级                     │
│       TCP       80       0.0.0.0/0        1                        │
│       TCP       443      0.0.0.0/0        1                        │
│       TCP       22       你的办公IP/32    1  ← SSH 尽量别全开       │
│    路径：ECS → 实例 → 安全组 → 配置规则 → 手动加入                   │
└────────────────────────────────────────────────────────────────────┘

SECURITY_GROUP_HINT

###############################################
# 5. 调用通用 deploy-alinux3.sh
###############################################
echo -e "\n\033[32m[5/6]\033[0m  调用 deploy-alinux3.sh (mode=${MODE}) ..."
EXTRA_ARGS=(--mode="${MODE}" --domain="${DOMAIN}" --app-dir="${APP_DIR}" --ssl-email="${SSL_EMAIL}" --enable-ssl="${ENABLE_SSL}")
if [[ -n "${TUSHARE_TOKEN}" ]]; then
  EXTRA_ARGS+=(--tushare="${TUSHARE_TOKEN}")
fi
bash deploy-alinux3.sh "${EXTRA_ARGS[@]}"

###############################################
# 6. 自检公网是否可达
###############################################
echo
echo "[6/6] 公网可达性自检（http://${DOMAIN} / http://${PUBLIC_IP}）..."
sleep 3
DOM_OK="" IP_OK=""
for i in 1 2 3 4 5 6 7 8; do
  if [[ -z "$DOM_OK" ]]; then
    C="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 6 "http://${DOMAIN}/" || true)"
    if [[ "$C" == "200" || "$C" == "301" ]]; then DOM_OK=1; fi
  fi
  if [[ -z "$IP_OK" ]]; then
    C="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 6 "http://${PUBLIC_IP}/" || true)"
    if [[ "$C" == "200" || "$C" == "301" ]]; then IP_OK=1; fi
  fi
  [[ -n "$DOM_OK" && -n "$IP_OK" ]] && break
  echo "   第 $i 次自测，等待 3s..."
  sleep 3
done
[[ -n "$DOM_OK" ]] && echo "✅ ${DOMAIN} 外部可访问" || echo "⚠️  ${DOMAIN} 暂未返回 200/301（若刚开了 HTTPS 301 是正常的，https 再测一次）"
[[ -n "$IP_OK"  ]] && echo "✅ ${PUBLIC_IP} 外部可访问"  || echo "⚠️  ${PUBLIC_IP} 仍不可达，请检查安全组 TCP 80 是否已放行 0.0.0.0/0"

echo
echo "====================================================================="
echo "✅ 部署完成，前端：  http://${PUBLIC_IP}"
echo "   健康检查：        http://${PUBLIC_IP}/api/system/healthz"
echo "   后端日志(bm)：    sudo journalctl -u webstock -f"
echo "   后端日志(docker)：cd ${APP_DIR} && sudo docker compose logs -f webstock"
echo "   Nginx 重载：      sudo systemctl restart nginx"
echo "====================================================================="
