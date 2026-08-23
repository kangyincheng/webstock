#!/usr/bin/env bash
# =====================================================================
# webstock 一键部署脚本 · 目标系统：Alibaba Cloud Linux 3.2104 LTS 64 位
# 作者：kangyincheng
#
# 模式：
#   1) --mode=docker   （默认）Docker Compose 方式部署，零依赖、最省心
#   2) --mode=baremetal  宿主机直接部署：Python3.11 + Nginx + Redis + Systemd
#
# 执行示例：
#   cd /opt/webstock
#   bash deploy-alinux3.sh --mode=docker
#
# 安全加固：该脚本不写全局配置；只在 /opt/webstock 与相关 systemd 目录下操作。
# =====================================================================
set -euo pipefail

COLOR_GREEN=$'\033[32m'
COLOR_YELLOW=$'\033[33m'
COLOR_RED=$'\033[31m'
COLOR_RESET=$'\033[0m'
info()    { echo "${COLOR_GREEN}[INFO]${COLOR_RESET} $*"; }
warn()    { echo "${COLOR_YELLOW}[WARN]${COLOR_RESET} $*"; }
err()     { echo "${COLOR_RED}[ERR]${COLOR_RESET}  $*" >&2; exit 1; }

# ---- 默认参数 ----
MODE="docker"
APP_DIR="/opt/webstock"
HTTP_PORT="80"
HTTPS_PORT="443"
WORKERS="$(nproc)"
DOMAIN="www.jeoj.com"               # 默认用我们的主域名
SSL_EMAIL=""                        # 留空时会 fallback 到 admin@<主域名>
ENABLE_SSL="auto"                   # auto=DNS 已解时才申请，yes=强制申请，no=跳过
TUSHARE_TOKEN=""
SKIP_BUILD="no"

for arg in "$@"; do
    case "$arg" in
        --mode=*)        MODE="${arg#*=}" ;;
        --app-dir=*)     APP_DIR="${arg#*=}" ;;
        --http-port=*)   HTTP_PORT="${arg#*=}" ;;
        --https-port=*)  HTTPS_PORT="${arg#*=}" ;;
        --workers=*)     WORKERS="${arg#*=}" ;;
        --domain=*)      DOMAIN="${arg#*=}" ;;
        --ssl-email=*)   SSL_EMAIL="${arg#*=}" ;;
        --enable-ssl=*)  ENABLE_SSL="${arg#*=}" ;;
        --tushare=*)     TUSHARE_TOKEN="${arg#*=}" ;;
        --skip-build)    SKIP_BUILD="yes" ;;
        -h|--help)
            cat <<EOF
用法：$0 [OPTIONS]
  --mode=docker|baremetal   部署模式（默认 docker）
  --app-dir=/opt/webstock   部署根目录
  --http-port=80            Nginx 对外 HTTP 端口
  --https-port=443          Nginx 对外 HTTPS 端口
  --workers=N               gunicorn workers 数（默认 nproc）
  --domain=www.jeoj.com     主域名（默认 www.jeoj.com，支持形如 a.com 同时带 www）
  --ssl-email=you@mail.com  Let's Encrypt 通知邮箱，缺省为 admin@主域名
  --enable-ssl=auto|yes|no  auto=DNS 解析到本机公网时自动申请（默认）
  --tushare=xxxxx           设置 tushare token（写进 tushare_token.txt）
  --skip-build              Docker 模式下跳过 docker build
  -h, --help                本帮助
EOF
            exit 0
            ;;
        *) warn "未知参数：$arg（忽略）" ;;
    esac
done

# 主域名（去掉 www. 前缀取 apex）
APEX_DOMAIN="${DOMAIN#www.}"
if [[ -z "$SSL_EMAIL" ]]; then
  SSL_EMAIL="admin@${APEX_DOMAIN}"
fi

# ---- 环境预检 ----
[[ "$(uname -s)" == "Linux" ]] || err "仅支持 Linux"

info "部署模式     = $MODE"
info "部署根目录   = $APP_DIR"
info "Workers      = $WORKERS"

###############################################
# 通用：系统包安装（yum/dnf，兼容 Alinux3）
###############################################
install_system_packages_baremetal() {
    info "[通用] 安装系统依赖（curl git ca-certificates）..."
    if command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y -q curl git ca-certificates tar gzip
    elif command -v yum >/dev/null 2>&1; then
        sudo yum install -y -q curl git ca-certificates tar gzip
    else
        warn "未找到 dnf/yum，请自行安装 curl/git/ca-certificates"
    fi
}

install_python311_alinux3() {
    if command -v python3.11 >/dev/null 2>&1; then
        info "Python 3.11 已安装：$(python3.11 --version)"
        return
    fi
    info "[Alinux 3] 安装 Python 3.11（通过 dnf 模块安装）"
    # Alinux 3 使用 dnf module 安装 Python 3.11（官方源已包含）
    set +e
    sudo dnf install -y -q python3.11 python3.11-pip python3.11-devel
    if ! command -v python3.11 >/dev/null 2>&1; then
        warn "dnf 未装到 Python3.11，退化为编译安装（需联网）..."
        sudo dnf groupinstall -y -q "Development Tools"
        sudo dnf install -y -q openssl-devel bzip2-devel libffi-devel zlib-devel xz-devel
        PY="3.11.9"
        cd /tmp && curl -fsSLO "https://www.python.org/ftp/python/${PY}/Python-${PY}.tgz"
        tar xzf "Python-${PY}.tgz" && cd "Python-${PY}"
        ./configure --prefix=/usr/local --enable-optimizations --with-lto >/dev/null
        make -j"$(nproc)" >/dev/null && sudo make altinstall >/dev/null
    fi
    set -e
    command -v python3.11 >/dev/null 2>&1 || err "Python 3.11 安装失败"
    info "Python 已就绪：$(python3.11 --version)"
}

install_redis_alinux3() {
    if command -v redis-server >/dev/null 2>&1; then
        info "Redis 已安装"
        return
    fi
    info "[Alinux 3] 安装 Redis（epel 兼容）..."
    set +e
    sudo dnf install -y -q epel-release
    sudo dnf install -y -q redis
    set -e
    sudo systemctl enable --now redis
    redis-cli ping | grep -q PONG && info "Redis 启动成功" || warn "Redis 未启动（稍后由 FastAPI 自动降级为内存缓存）"
}

install_nginx_alinux3() {
    if command -v nginx >/dev/null 2>&1; then
        info "Nginx 已安装（$(nginx -v 2>&1)）"
        return
    fi
    info "[Alinux 3] 安装 Nginx..."
    sudo dnf install -y -q nginx
    sudo systemctl enable --now nginx
    info "Nginx 已启动"
}

###############################################
# Let's Encrypt 证书申请（certbot webroot）
# 前置：DNS 已解析、80 端口已放行、ACME challenge location 已在 nginx.conf
###############################################
install_certbot_alinux3() {
    if command -v certbot >/dev/null 2>&1; then
      info "certbot 已存在（$(certbot --version 2>&1)）"
      return
    fi
    info "[SSL] 安装 certbot（Python 3.11 venv，独立于项目 venv）..."
    if ! command -v python3.11 >/dev/null 2>&1; then
      install_python311_alinux3
    fi
    sudo python3.11 -m venv /opt/certbot-venv
    # shellcheck disable=SC1091
    sudo /opt/certbot-venv/bin/python -m pip install --upgrade pip setuptools wheel 2>&1 | tail -2
    sudo /opt/certbot-venv/bin/python -m pip install --no-cache-dir certbot 2>&1 | tail -3
    sudo ln -sf /opt/certbot-venv/bin/certbot /usr/local/bin/certbot
    command -v certbot >/dev/null 2>&1 || err "certbot 安装失败"
    info "certbot ready: $(certbot --version 2>&1)"
}

dns_resolves_to_this_host() {
  # 判断域名 A 记录是否解析到本机公网 IP
  local host="$1"
  [[ -z "$host" ]] && return 1
  local pub
  pub="$(curl -sS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
  [[ -z "$pub" ]] && { warn "无法获取本机出口 IP，跳过 SSL 预检"; return 1; }
  local resolved
  resolved="$( (dig +short -t A "$host" 2>/dev/null || host -t A "$host" 2>/dev/null | awk '/has address/{print $4}') | head -1 )"
  [[ -z "$resolved" ]] && return 1
  if [[ "$resolved" == "$pub" ]]; then
    info "DNS OK: $host → $resolved (本机公网 $pub)"
    return 0
  fi
  warn "DNS 未对齐: $host → $resolved，本机出口 IP = $pub（若在 NAT 下可忽略此校验并 --enable-ssl=yes）"
  return 1
}

issue_letsencrypt_webroot() {
  # 域名清单：www.jeoj.com + jeoj.com
  local DOMAINS_ARGS=("-d" "$DOMAIN")
  if [[ "$APEX_DOMAIN" != "$DOMAIN" ]]; then
    DOMAINS_ARGS+=("-d" "$APEX_DOMAIN")
  fi

  # ACME webroot 目录（与 nginx.conf 中 location ^~ /.well-known/acme-challenge/ 一致）
  sudo mkdir -p /var/www/acme-challenge
  # 测试 ACME 回显（certbot 会校验）
  local test_token="webstock-probe-$RANDOM"
  echo -n "$test_token" | sudo tee /var/www/acme-challenge/.probe >/dev/null
  local http_code
  http_code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 8 "http://${DOMAIN}/.well-known/acme-challenge/.probe" 2>/dev/null || true)"
  sudo rm -f /var/www/acme-challenge/.probe
  info "ACME 连通性预检 http://${DOMAIN}/.well-known/acme-challenge/ → HTTP $http_code"

  # certbot certonly --webroot -w /var/www/acme-challenge -d www.jeoj.com -d jeoj.com --email ... --non-interactive
  set +e
  sudo certbot certonly --webroot -w /var/www/acme-challenge \
      "${DOMAINS_ARGS[@]}" \
      --email "$SSL_EMAIL" \
      --agree-tos --no-eff-email --non-interactive \
      --keep-until-expiring \
      2>&1 | tail -20
  local rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    warn "certbot 申请失败（rc=$rc），SSL 段不会启用。可以稍后手工执行："
    warn "   sudo certbot certonly --webroot -w /var/www/acme-challenge -d ${DOMAIN} -d ${APEX_DOMAIN} --email ${SSL_EMAIL}"
    return 1
  fi
  # 写进 crontab 自动续期（每天 03:00 检查）
  if ! sudo crontab -l 2>/dev/null | grep -q certbot; then
    (sudo crontab -l 2>/dev/null; echo "0 3 * * * /usr/local/bin/certbot renew --quiet --post-hook 'systemctl reload nginx'") \
      | sudo crontab -
    info "已写入每日 certbot renew crontab"
  fi
  return 0
}

enable_https_server_block() {
  local snippet_src="$1"        # 比如 deploy/nginx/webstock-https.conf.snippet
  local target_path="$2"        # 比如 /etc/nginx/conf.d/webstock-https.conf 或 $APP_DIR/deploy/nginx/conf.d/webstock-https.conf
  local replace_upstream="$3"   # baremetal=127.0.0.1:8000  docker=webstock:8000
  local replace_root="$4"       # baremetal=$APP_DIR/frontend/dist  docker=/usr/share/nginx/html

  [[ -f "$snippet_src" ]] || err "缺失 HTTPS 片段：$snippet_src"
  sudo mkdir -p "$(dirname "$target_path")"
  sudo cp "$snippet_src" "$target_path"
  sudo sed -i "s|server webstock:8000|server ${replace_upstream}|g" "$target_path"
  sudo sed -i "s|root /usr/share/nginx/html;|root ${replace_root};|g" "$target_path"
  sudo sed -i "s|alias /usr/share/nginx/html/assets/;|alias ${replace_root%/}/assets/;|" "$target_path"

  # 确认证书真的存在（经验 331399：不存在则 nginx -t 必崩）
  if [[ ! -f /etc/letsencrypt/live/${DOMAIN}/fullchain.pem ]]; then
    warn "证书文件 /etc/letsencrypt/live/${DOMAIN}/fullchain.pem 不存在，撤回 443 配置片段避免 nginx -t 失败"
    sudo rm -f "$target_path"
    return 1
  fi
  return 0
}

install_docker_alinux3() {
    if command -v docker >/dev/null 2>&1; then
        info "Docker 已存在（$(docker --version)）"
    else
        info "[Alinux 3] 安装 Docker CE（阿里云镜像）..."
        sudo dnf install -y -q yum-utils device-mapper-persistent-data lvm2
        sudo dnf config-manager -y --add-repo \
            https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo
        sudo dnf install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin
        sudo systemctl enable --now docker
    fi
    # docker compose v2
    if docker compose version >/dev/null 2>&1; then
        info "Docker Compose：$(docker compose version)"
    else
        sudo curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-Linux-x86_64" \
             -o /usr/local/bin/docker-compose && sudo chmod +x /usr/local/bin/docker-compose
    fi
    # 把当前用户加入 docker 组（需重新登录生效）
    if ! groups 2>/dev/null | grep -q '\bdocker\b'; then
        sudo usermod -aG docker "$USER" 2>/dev/null || true
    fi
}

sync_code() {
    info "同步代码到 $APP_DIR ..."
    sudo mkdir -p "$APP_DIR"
    sudo chown -R "$(id -u):$(id -g)" "$APP_DIR"
    if [[ -d "$APP_DIR/.git" ]]; then
        (cd "$APP_DIR" && git pull --ff-only)
    else
        # 如果在执行脚本的目录本身就是 git 仓库，直接 rsync
        if [[ -d ".git" ]]; then
            rsync -a --delete --exclude='.git' --exclude='node_modules' --exclude='__pycache__' \
                  --exclude='.venv' --exclude='data/*' --exclude='models/*' \
                  ./ "$APP_DIR/"
        fi
    fi
    mkdir -p "$APP_DIR/backend/data" "$APP_DIR/backend/models" "$APP_DIR/deploy/nginx/logs"
    # 写入 tushare token
    if [[ -n "$TUSHARE_TOKEN" ]]; then
        echo -n "$TUSHARE_TOKEN" > "$APP_DIR/tushare_token.txt"
        info "tushare_token.txt 已写入"
    elif [[ ! -f "$APP_DIR/tushare_token.txt" ]]; then
        touch "$APP_DIR/tushare_token.txt"
        warn "未提供 --tushare=TOKEN ，tushare 接口不会启用（板块/热门等仍可用 mock）"
    fi
}

###############################################
# 模式 A：Docker Compose 部署
###############################################
deploy_docker() {
    install_system_packages_baremetal
    install_docker_alinux3
    sync_code

    cd "$APP_DIR"

    # 环境变量文件
    cat >.env <<EOF
HTTP_PORT=$HTTP_PORT
HTTPS_PORT=$HTTPS_PORT
WORKERS=$WORKERS
TUSHARE_TOKEN=${TUSHARE_TOKEN}
DOMAIN=${DOMAIN}
APEX_DOMAIN=${APEX_DOMAIN}
EOF

    if [[ "$SKIP_BUILD" == "no" ]]; then
        info "[Docker] 构建镜像（首次可能 10~20 分钟）..."
        if command -v docker >/dev/null 2>&1 && groups | grep -q '\bdocker\b'; then
            docker compose build --pull
        else
            info "当前未在 docker 组，使用 sudo 构建（之后请重新登录以获得 docker 权限）"
            sudo docker compose build --pull
        fi
    else
        info "[Docker] 跳过构建（--skip-build）"
    fi

    # Docker 模式下 conf.d 目录必须存在（即使为空），以及 /var/www/acme-challenge、/etc/letsencrypt
    sudo mkdir -p "$APP_DIR/deploy/nginx/conf.d" /var/www/acme-challenge /etc/letsencrypt
    # 先别写入 webstock-https.conf（经验 331399：证书没齐 nginx -t 必崩，容器会起不来）
    # 若之前跑过留下旧片段，先清掉，等证书申请到位再写
    sudo rm -f "$APP_DIR/deploy/nginx/conf.d/webstock-https.conf"

    info "[Docker] 启动所有服务：Nginx + FastAPI + Redis ..."
    DC_CMD=(docker compose)
    if ! (command -v docker >/dev/null 2>&1 && groups | grep -q '\bdocker\b'); then
      DC_CMD=(sudo docker compose)
    fi
    "${DC_CMD[@]}" up -d
    sleep 5
    info "[Docker] 健康检查..."
    "${DC_CMD[@]}" ps
    IP="$(hostname -I | awk '{print $1}')"

    # ---- SSL：certbot 申请 + 写入 conf.d 后 reload nginx 容器 ----
    ACME_DONE=0
    if [[ "$ENABLE_SSL" != "no" ]]; then
      if [[ "$ENABLE_SSL" == "yes" ]] || dns_resolves_to_this_host "$DOMAIN"; then
        install_certbot_alinux3
        if issue_letsencrypt_webroot; then
          # Docker 模式：把 https snippet 写到 $APP_DIR/deploy/nginx/conf.d/webstock-https.conf
          #   upstream = webstock:8000（容器内 DNS）
          #   root     = /usr/share/nginx/html（容器内）
          enable_https_server_block \
            "deploy/nginx/webstock-https.conf.snippet" \
            "$APP_DIR/deploy/nginx/conf.d/webstock-https.conf" \
            "webstock:8000" \
            "/usr/share/nginx/html" || true
          # 容器内 nginx -t 再 reload
          set +e
          "${DC_CMD[@]}" exec -T nginx nginx -t 2>&1 | tail -5
          local ok=$?
          set -e
          if [[ $ok -eq 0 ]]; then
            "${DC_CMD[@]}" exec -T nginx nginx -s reload 2>&1 | tail -2
            ACME_DONE=1
          else
            warn "nginx container 内 nginx -t 失败，撤掉 443 片段"
            sudo rm -f "$APP_DIR/deploy/nginx/conf.d/webstock-https.conf"
            "${DC_CMD[@]}" exec -T nginx nginx -s reload 2>/dev/null || true
          fi
        fi
      else
        warn "[SSL] 未通过 DNS 预检，跳过证书申请。CDN/NAT 场景可加 --enable-ssl=yes 强制申请。"
      fi
    fi

    echo
    info "========================================="
    info "✅ 部署完成（Docker Compose）"
    info "   公网 IP：  http://${IP}"
    [[ -n "$DOMAIN" ]] && info "   主域名：   http://${DOMAIN}"
    [[ $ACME_DONE == 1 ]] && info "   HTTPS：    https://${DOMAIN} （jeoj.com → 301 → www.jeoj.com）"
    info "   常用命令（cd $APP_DIR 后）："
    info "     查看后端日志  ${DC_CMD[*]} logs -f webstock"
    info "     重启后端      ${DC_CMD[*]} restart webstock"
    info "     重载 Nginx    ${DC_CMD[*]} exec nginx nginx -s reload"
    info "========================================="
}

###############################################
# 模式 B：裸机部署 (Baremetal)
###############################################
deploy_baremetal() {
    install_system_packages_baremetal
    install_python311_alinux3
    install_redis_alinux3
    install_nginx_alinux3
    sync_code

    cd "$APP_DIR"

    # ---- 虚拟环境 ----
    if [[ ! -d ".venv" ]]; then
        info "创建 Python 虚拟环境..."
        python3.11 -m venv .venv
    fi
    # shellcheck disable=SC1091
    source .venv/bin/activate
    info "pip 安装依赖..."
    python -m pip install --upgrade pip setuptools wheel
    python -m pip install -r backend/requirements.txt
    python -m pip install gunicorn

    # ---- 前端构建（如果机器已装 node 就构建，否则跳过，提示）----
    if command -v npm >/dev/null 2>&1; then
        info "[前端] 安装 Node 依赖并构建..."
        (cd frontend && npm install --no-audit --no-fund --loglevel=error && npm run build)
    else
        warn "[前端] 本机未安装 Node.js，跳过构建。请在本机执行 frontend 下的 npm install && npm run build 后 rsync dist 到 $APP_DIR/frontend/dist，或切换 Docker 模式。"
    fi

    # ---- 创建运行用户 ----
    if ! id -u webstock >/dev/null 2>&1; then
        sudo useradd -r -s /usr/sbin/nologin -d "$APP_DIR" webstock
    fi
    sudo mkdir -p /var/log/webstock
    sudo chown -R webstock:webstock "$APP_DIR/backend/data" "$APP_DIR/backend/models" /var/log/webstock

    # ---- Systemd Unit ----
    info "安装 systemd unit..."
    sudo cp deploy/systemd/webstock.service /etc/systemd/system/webstock.service
    sudo sed -i "s|User=webstock|User=webstock|; s|WorkingDirectory=.*|WorkingDirectory=$APP_DIR|" \
        /etc/systemd/system/webstock.service
    sudo systemctl daemon-reload
    sudo systemctl enable --now webstock
    sleep 3
    systemctl is-active --quiet webstock && info "webstock backend 运行中" || err "backend 启动失败，请查看 journalctl -u webstock"

    # ---- Nginx 配置 ----
    info "安装 Nginx 配置（替换主 nginx.conf，因为 webstock.conf 是完整优化版）..."
    # 备份原来的主配置（保留一次）
    [[ -f /etc/nginx/nginx.conf && ! -f /etc/nginx/nginx.conf.bak.webstock ]] \
        && sudo cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak.webstock
    sudo cp deploy/nginx/webstock.conf /etc/nginx/nginx.conf
    # upstream：baremetal 下 webstock 容器名不存在，改为 127.0.0.1:8000
    sudo sed -i 's|server webstock:8000|server 127.0.0.1:8000|' /etc/nginx/nginx.conf
    # server_name 追加 _ 以防 Host 异常（但 IP 已经是 8.130.158.196）
    # SPA root 改成项目下的 frontend/dist
    sudo sed -i "s|root /usr/share/nginx/html;|root $APP_DIR/frontend/dist;|g" /etc/nginx/nginx.conf
    sudo sed -i "s|alias /usr/share/nginx/html/assets/;|alias $APP_DIR/frontend/dist/assets/;|" /etc/nginx/nginx.conf
    # 停掉默认 default.conf（会与主配置 80 default_server 冲突）
    if [[ -f /etc/nginx/conf.d/default.conf ]]; then
        sudo mv /etc/nginx/conf.d/default.conf /etc/nginx/conf.d/default.conf.disabled 2>/dev/null || true
    fi
    sudo mkdir -p "$APP_DIR/deploy/nginx/logs" /var/log/nginx
    sudo nginx -t || err "Nginx 配置错误，请查看 /etc/nginx/nginx.conf"
    sudo systemctl enable nginx
    sudo systemctl restart nginx

    # ---- 防火墙（Alinux 3 默认 firewalld）----
    if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
        sudo firewall-cmd --permanent --add-service=http >/dev/null 2>&1 || true
        sudo firewall-cmd --permanent --add-port="${HTTP_PORT}/tcp" >/dev/null 2>&1 || true
        sudo firewall-cmd --permanent --add-port="${HTTPS_PORT}/tcp" >/dev/null 2>&1 || true
        sudo firewall-cmd --reload >/dev/null 2>&1 || true
        info "防火墙已放行 $HTTP_PORT/$HTTPS_PORT"
    fi

    # ---- 健康检查 ----
    for i in 1 2 3 4 5 6 7 8 9 10; do
        if curl -fsS "http://127.0.0.1:8000/api/system/healthz" >/dev/null; then
            info "健康检查通过"
            break
        fi
        sleep 2
    done

    IP="$(hostname -I | awk '{print $1}')"

    # ---- SSL：certbot 申请 Let's Encrypt 并启用 443 server 段 ----
    ACME_DONE=0
    if [[ "$ENABLE_SSL" == "no" ]]; then
      warn "[SSL] 用户指定 --enable-ssl=no，跳过"
    else
      if [[ "$ENABLE_SSL" == "yes" ]] || dns_resolves_to_this_host "$DOMAIN"; then
        install_certbot_alinux3
        # 必须先保证 /etc/letsencrypt 目录已存在
        sudo mkdir -p /etc/letsencrypt
        if issue_letsencrypt_webroot; then
          enable_https_server_block \
            "deploy/nginx/webstock-https.conf.snippet" \
            "/etc/nginx/conf.d/webstock-https.conf" \
            "127.0.0.1:8000" \
            "$APP_DIR/frontend/dist" || true
          sudo nginx -t 2>&1 | tail -3
          if sudo nginx -t >/dev/null 2>&1; then
            sudo systemctl reload nginx
            ACME_DONE=1
          else
            warn "nginx -t 失败，撤掉 webstock-https.conf 以保证可用性"
            sudo rm -f /etc/nginx/conf.d/webstock-https.conf
            sudo nginx -t && sudo systemctl reload nginx || true
          fi
        fi
      else
        warn "[SSL] 未通过 DNS 预检，跳过证书申请。如果是 CDN/NAT，请用 --enable-ssl=yes 强制申请。"
      fi
    fi

    echo
    info "========================================="
    info "✅ 部署完成（Baremetal）"
    info "   公网 IP：  http://${IP}"
    [[ -n "$DOMAIN" ]] && info "   主域名：   http://${DOMAIN}"
    [[ $ACME_DONE == 1 ]] && info "   HTTPS：    https://${DOMAIN} （jeoj.com → 301 → www.jeoj.com）"
    info "   常用命令："
    info "     查看后端日志  sudo journalctl -u webstock -f"
    info "     重启后端      sudo systemctl restart webstock"
    info "     重载 Nginx    sudo systemctl reload nginx"
    info "     手动申请证书  sudo certbot certonly --webroot -w /var/www/acme-challenge -d ${DOMAIN} -d ${APEX_DOMAIN} --email ${SSL_EMAIL}"
    info "========================================="
}

###############################################
# 入口
###############################################
case "$MODE" in
    docker)    deploy_docker ;;
    baremetal) deploy_baremetal ;;
    *)         err "未知 --mode=$MODE，可选 docker / baremetal" ;;
esac
