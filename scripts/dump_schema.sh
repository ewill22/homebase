#!/usr/bin/env bash
# Refresh schema.sql from the current homebase MySQL database.
# Run after creating or altering any homebase table.
#
# Reads MYSQL_USER and MYSQL_PASSWORD from .env in the repo root.
set -eo pipefail

cd "$(dirname "$0")/.."

# Read .env without shell expansion (values may contain $ and other metacharacters).
# Strip Windows CRLF — .env was saved with CRLF line endings.
while IFS='=' read -r key val; do
    val="${val%$'\r'}"
    [[ -z "$key" || "$key" == \#* ]] && continue
    export "$key"="$val"
done < .env

MYSQLDUMP="/c/Program Files/MySQL/MySQL Server 8.0/bin/mysqldump.exe"

"$MYSQLDUMP" \
    -h "${MYSQL_HOST:-127.0.0.1}" \
    -u "$MYSQL_USER" \
    -p"$MYSQL_PASSWORD" \
    --no-data \
    --skip-add-drop-table \
    --skip-comments \
    --skip-set-charset \
    --skip-dump-date \
    --compact \
    homebase 2>/dev/null \
  | sed -E 's/ AUTO_INCREMENT=[0-9]+//g' \
  | grep -v '^/\*!' \
  | grep -v '^$' \
  > _schema_body.sql

# Reattach the human header
{
  cat <<'EOF'
-- homebase MySQL schema (database: homebase)
-- Frozen snapshot of every table the homebase code depends on.
--
-- To apply to a fresh DB: mysql -u guapa_will -p homebase < schema.sql
-- To regenerate from current DB: see scripts/dump_schema.sh
--
-- Note: guapa.* tables (parcels, sr1a_sales, tax_list, strain_stock) live in
-- a separate database and are NOT in this file.

EOF
  cat _schema_body.sql
} > schema.sql

rm _schema_body.sql
echo "schema.sql refreshed ($(wc -l < schema.sql) lines)"
