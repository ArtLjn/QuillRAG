#!/usr/bin/env bash
# 远程控制 quillrag（在腾讯云上跑 systemctl）
# 用法：
#   bash deploy/server-ctl.sh start|stop|restart|status|tail|logs|health|sync

set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-root@43.155.217.74}"
REMOTE_DIR="${REMOTE_DIR:-/root/workspace/quillrag}"
SERVICE_NAME="quillrag"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"
ACTION="${1:-status}"

cd "$(dirname "$0")/.."

case "$ACTION" in
  sync)
    bash deploy/server-sync.sh
    ;;
  install)
    ssh $SSH_OPTS "${REMOTE_HOST}" "cd ${REMOTE_DIR} && bash deploy/install.sh"
    ;;
  start|stop|restart)
    echo "▶ systemctl $ACTION $SERVICE_NAME @ ${REMOTE_HOST}"
    ssh $SSH_OPTS "${REMOTE_HOST}" "systemctl $ACTION $SERVICE_NAME"
    sleep 2
    ssh $SSH_OPTS "${REMOTE_HOST}" "systemctl is-active $SERVICE_NAME 2>&1 || true"
    ;;
  status)
    ssh $SSH_OPTS "${REMOTE_HOST}" "systemctl status $SERVICE_NAME --no-pager -l 2>&1 | head -20 || true"
    ;;
  tail)
    # 实时跟踪最近 200 行日志
    ssh $SSH_OPTS "${REMOTE_HOST}" "journalctl -u $SERVICE_NAME -n 200 --no-pager -f"
    ;;
  logs)
    # 显示最近 N 行（默认 100）
    N="${2:-100}"
    ssh $SSH_OPTS "${REMOTE_HOST}" "journalctl -u $SERVICE_NAME -n $N --no-pager"
    ;;
  health)
    echo "▶ 远程 /health"
    ssh $SSH_OPTS "${REMOTE_HOST}" "curl -s http://127.0.0.1:8001/health" | python3 -m json.tool 2>/dev/null || \
      ssh $SSH_OPTS "${REMOTE_HOST}" "curl -s http://127.0.0.1:8001/health"
    ;;
  *)
    echo "用法: bash deploy/server-ctl.sh {sync|install|start|stop|restart|status|tail|logs [N]|health}"
    echo ""
    echo "  sync     同步代码 + .env 到 ${REMOTE_HOST}:${REMOTE_DIR}"
    echo "  install  首次部署（apt + venv + systemd）"
    echo "  start    启动"
    echo "  stop     停止"
    echo "  restart  重启（同步代码后用）"
    echo "  status   systemd 状态"
    echo "  tail     实时跟踪日志（Ctrl+C 退出）"
    echo "  logs N   最近 N 行日志（默认 100）"
    echo "  health   远程 /health"
    exit 1
    ;;
esac
