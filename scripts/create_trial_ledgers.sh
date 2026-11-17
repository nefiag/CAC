#!/usr/bin/env bash
set -euo pipefail

# Creates a real PostgreSQL custom-format backup, verifies it, then atomically
# clones both formal baselines into their fixed trial-ledger IDs.
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="${COMPOSE_FILE:-$repo_dir/docker-compose.prod.yml}"
backup_dir="${LEDGER_BACKUP_DIR:-$repo_dir/backups/ledger}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="$backup_dir/pre-create-trials-$timestamp.dump"

mkdir -p "$backup_dir"
cd "$repo_dir"

docker compose -f "$compose_file" exec -T db \
  pg_dump -Fc -U coxiaoac_user -d coxiaoac > "$backup_file"
test -s "$backup_file"
sha256="$(sha256sum "$backup_file" | awk '{print $1}')"
docker compose -f "$compose_file" exec -T db \
  pg_restore --list < "$backup_file" >/dev/null

docker compose -f "$compose_file" run --rm \
  -v "$backup_dir:/ledger-backup:ro" \
  backend python scripts/create_trial_ledgers.py \
  --backup "/ledger-backup/$(basename "$backup_file")" \
  --sha256 "$sha256"

printf 'BACKUP=%s\nSHA256=%s\n' "$backup_file" "$sha256"
