#!/usr/bin/env bash
# 同步 quillrag 代码 + .env 到腾讯云生产机
# 用法：bash deploy/server-sync.sh
#
# 排除项：.venv / data / __pycache__ / .git / 测试缓存
# 包含：app/ tests/ docs/ fixtures/ deploy/ requirements* pyproject.toml Dockerfile .env.example .env README.md

set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-root@43.155.217.74}"
REMOTE_DIR="${REMOTE_DIR:-/root/workspace/quillrag}"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"

cd "$(dirname "$0")/.."  # 切到项目根

echo "▶ 同步代码到 ${REMOTE_HOST}:${REMOTE_DIR}"

# 1. 远程确保目录存在
ssh $SSH_OPTS "${REMOTE_HOST}" "mkdir -p ${REMOTE_DIR}/{data,logs}"

# 2. rsync 同步代码（增量，排除缓存/虚拟环境）
rsync -avz --delete \
  -e "ssh $SSH_OPTS" \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache/' \
  --exclude='.ruff_cache/' \
  --exclude='.coverage' \
  --exclude='htmlcov/' \
  --exclude='data/' \
  --exclude='logs/' \
  --exclude='.git/' \
  --exclude='*.db' \
  --exclude='*.db-journal' \
  --exclude='.DS_Store' \
  ./ "${REMOTE_HOST}:${REMOTE_DIR}/"

echo "✓ 代码同步完成"

# 3. 单独 scp .env（rsync --exclude 了 data，但 .env 不在排除中，rsync 已带过去）
# 这里再做一次保险，确保最新 .env 落地
if [ -f .env ]; then
  scp $SSH_OPTS .env "${REMOTE_HOST}:${REMOTE_DIR}/.env"
  echo "✓ .env 已更新"
else
  echo "⚠ 本地无 .env，跳过凭证同步（首次部署需手动创建）"
fi

echo ""
echo "▶ 下一步："
echo "  首次部署：  ssh ${REMOTE_HOST} 'cd ${REMOTE_DIR} && bash deploy/install.sh'"
echo "  重启服务：  bash deploy/server-ctl.sh restart"
echo "  查看状态：  bash deploy/server-ctl.sh status"
