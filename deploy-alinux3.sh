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
DOMAIN=""
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
  --domain=your.domain.com  设置后会写入 Nginx server_name
  --tushare=xxxxx           设置 tushare token（写进 tushare_token.txt）
  --skip-build              Docker 模式下跳过 docker build
  -h, --help                本帮助
EOF
            exit 0
            ;;
        *) warn "未知参数：$arg（忽略）" ;;
    esac
done

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

    info "[Docker] 启动所有服务：Nginx + FastAPI + Redis ..."
    if command -v docker >/dev/null 2>&1 && groups | grep -q '\bdocker\b'; then
        docker compose up -d
    else
        sudo docker compose up -d
    fi
    sleep 3
    info "[Docker] 健康检查..."
    (command -v docker >/dev/null 2>&1 && groups | grep -q '\bdocker\b' && docker compose ps) \
        || sudo docker compose ps
    echo
    info "✅ 部署完成！请访问：http://$(hostname -I | awk '{print $1}'):${HTTP_PORT}"
    if [[ -n "$DOMAIN" ]]; then
        info "   或解析域名后访问：http://${DOMAIN}:${HTTP_PORT}"
    fi
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
    echo
    info "========================================="
    info "✅ 部署完成"
    info "   地址：http://${IP}:${HTTP_PORT}"
    [[ -n "$DOMAIN" ]] && info "   域名：http://${DOMAIN}:${HTTP_PORT}"
    info "   常用命令："
    info "     查看后端日志  sudo journalctl -u webstock -f"
    info "     重启后端      sudo systemctl restart webstock"
    info "     重载 Nginx    sudo systemctl reload nginx"
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
