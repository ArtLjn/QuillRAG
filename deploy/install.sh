#!/usr/bin/env bash
# 首次部署：在腾讯云上安装依赖 + 启用 systemd 服务
# 必须在服务器上跑（ssh root@43.155.217.74 'cd /root/workspace/quillrag && bash deploy/install.sh'）
#
# 做的事：
# 1. apt 安装系统依赖（tesseract OCR、libgl、build-essential）
# 2. python3 -m venv .venv（用系统 Python 3.10+，毕设场景够用）
# 3. pip install -r requirements.txt
# 4. 部署 systemd 单元 + enable + start
# 5. 健康检查

set -euo pipefail

APP_DIR="${APP_DIR:-/root/workspace/quillrag}"
SERVICE_NAME="quillrag"
cd "$APP_DIR"

echo "▶ [1/6] apt 安装系统依赖（tesseract-ocr 中文 + libgl + build-essential）..."
if ! command -v tesseract >/dev/null 2>&1; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-chi-tra \
    libgl1 libglib2.0-0 build-essential curl >/dev/null
  echo "  ✓ tesseract 已装"
else
  echo "  ✓ tesseract 已存在，跳过"
fi

PY_BIN="python3"
if ! "$PY_BIN" -c 'import sys; assert sys.version_info >= (3,11)' 2>/dev/null; then
  # 尝试 python3.11 / python3.12
  for cand in python3.12 python3.11; do
    if command -v "$cand" >/dev/null 2>&1; then
      PY_BIN="$cand"
      break
    fi
  done
  if ! "$PY_BIN" -c 'import sys; assert sys.version_info >= (3,11)' 2>/dev/null; then
    echo "  ⚠ 系统 Python 版本 < 3.11，尝试装 python3.12（deadsnakes PPA）..."
    apt-get install -y -qq software-properties-common
    add-apt-repository -y ppa:deadsnakes/ppa
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3.12 python3.12-venv python3.12-dev
    PY_BIN="python3.12"
  fi
fi
echo "  ✓ 使用 Python: $("$PY_BIN" --version)"

echo ""
echo "▶ [2/6] 创建 venv..."
if [ ! -d .venv ]; then
  "$PY_BIN" -m venv .venv
fi
.venv/bin/pip install -q --upgrade pip
echo "  ✓ venv 已就绪"

echo ""
echo "▶ [3/6] 安装 Python 依赖（requirements.txt）..."
.venv/bin/pip install -q -r requirements.txt
echo "  ✓ 依赖安装完成"

echo ""
echo "▶ [4/6] 部署 systemd 单元..."
cp -f deploy/quillrag.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 || true
echo "  ✓ systemd 已注册并 enable"

echo ""
echo "▶ [5/6] 启动服务..."
systemctl restart "$SERVICE_NAME"
sleep 3

echo ""
echo "▶ [6/6] 健康检查..."
for i in 1 2 3 4 5; do
  if curl -sf --max-time 3 http://127.0.0.1:8001/health >/dev/null 2>&1; then
    echo "  ✓ /health 返回 200"
    curl -s http://127.0.0.1:8001/health | python3 -m json.tool
    echo ""
    echo "🎉 部署完成！访问入口："
    echo "  本机：    http://127.0.0.1:8001/ui/"
    echo "  公网：    http://43.155.217.74:8001/ui/"
    echo "  日志：    bash deploy/server-ctl.sh tail"
    exit 0
  fi
  echo "  ⏳ 等待启动... ($i/5)"
  sleep 2
done

echo ""
echo "✗ 启动失败，查看日志：journalctl -u $SERVICE_NAME -n 50 --no-pager"
systemctl status "$SERVICE_NAME" --no-pager -l | head -30
exit 1
