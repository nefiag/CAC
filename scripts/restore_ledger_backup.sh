#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 || "$2" != "我确认恢复账务备份" ]]; then
  printf '用法：%s BACKUP_FILE "我确认恢复账务备份"\n' "$0" >&2
  exit 2
fi
backup_file="$(realpath "$1")"
test -s "$backup_file"

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="${COMPOSE_FILE:-$repo_dir/docker-compose.prod.yml}"
compose_project="${COMPOSE_PROJECT_NAME:-coxiaoac}"
env_file="${COMPOSE_ENV_FILE:-$repo_dir/.env.production}"
pre_restore_dir="${LEDGER_BACKUP_DIR:-$repo_dir/backups/ledger}"
mkdir -p "$pre_restore_dir"
pre_restore="$pre_restore_dir/pre-restore-$(date -u +%Y%m%dT%H%M%SZ).dump"
cd "$repo_dir"

# Even rollback is a mutation: preserve the state being replaced first.
docker compose -p "$compose_project" --env-file "$env_file" -f "$compose_file" exec -T db \
  pg_dump -Fc -U coxiaoac_user -d coxiaoac > "$pre_restore"
test -s "$pre_restore"
docker compose -p "$compose_project" --env-file "$env_file" -f "$compose_file" exec -T db pg_restore --list < "$pre_restore" >/dev/null
docker compose -p "$compose_project" --env-file "$env_file" -f "$compose_file" exec -T db pg_restore --list < "$backup_file" >/dev/null

docker compose -p "$compose_project" --env-file "$env_file" -f "$compose_file" stop backend
docker compose -p "$compose_project" --env-file "$env_file" -f "$compose_file" exec -T db \
  pg_restore --clean --if-exists --no-owner -U coxiaoac_user -d coxiaoac < "$backup_file"
docker compose -p "$compose_project" --env-file "$env_file" -f "$compose_file" start backend

printf 'RESTORED=%s\nPRE_RESTORE_BACKUP=%s\n' "$backup_file" "$pre_restore"
