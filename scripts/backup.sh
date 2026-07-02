#!/usr/bin/env bash
# z-spanish 每日备份：用 SQLite online backup（.backup）保证一致性，不是简单 cp。
# 建议放 crontab：  0 4 * * *  /z/apps/z-spanish/scripts/backup.sh
set -euo pipefail

DB="${Z_SPANISH_DB:-/z/apps/z-spanish/data/z-spanish.db}"
BACKUP_DIR="${Z_SPANISH_BACKUP:-/z/backup/z-spanish}"
KEEP_DAYS="${Z_SPANISH_BACKUP_KEEP:-30}"

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/z-spanish-$STAMP.db"

if [ ! -f "$DB" ]; then
  echo "[backup] 数据库不存在：$DB" >&2
  exit 1
fi

# 一致性备份（即使有写入也安全）
sqlite3 "$DB" ".backup '$OUT'"
gzip -f "$OUT"
echo "[backup] 已生成 $OUT.gz"

# 清理超过 KEEP_DAYS 天的旧备份
find "$BACKUP_DIR" -name 'z-spanish-*.db.gz' -mtime "+$KEEP_DAYS" -delete
echo "[backup] 已清理 $KEEP_DAYS 天前的备份"
