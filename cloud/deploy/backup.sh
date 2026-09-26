#!/bin/sh
# Копия базы в другое место. Сама копия уже сделана `app.tools backup` (см. cron.example);
# здесь — только увезти последнюю с этой машины: пропавший VPS не должен уносить базу с собой.
# Настроить одно из двух: BACKUP_SCP (user@host:/path) или BACKUP_RCLONE (remote:bucket/path).
set -eu
DIR="${BACKUP_DIR:-/srv/dentpilot/data/backups}"
LAST="$(ls -1 "$DIR"/cloud-*.db 2>/dev/null | sort | tail -n 1 || true)"
if [ -z "$LAST" ]; then
    echo "копий в $DIR нет — сначала app.tools backup" >&2
    exit 1
fi
if [ -n "${BACKUP_SCP:-}" ]; then
    scp -q "$LAST" "$BACKUP_SCP/" && echo "увезено scp: $(basename "$LAST")"
elif [ -n "${BACKUP_RCLONE:-}" ]; then
    rclone copy "$LAST" "$BACKUP_RCLONE" && echo "увезено rclone: $(basename "$LAST")"
else
    echo "ни BACKUP_SCP, ни BACKUP_RCLONE: копия осталась только на этой машине" >&2
    exit 1
fi
