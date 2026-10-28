#!/bin/sh
set -eu

echo "[init-postgres] Waiting for shared-postgres to be fully ready to accept queries..."
max_retries=${DB_WAIT_RETRIES:-60}
count=0

until pg_isready -h shared-postgres -U postgres -d postgres >/dev/null 2>&1 && psql -h shared-postgres -U postgres -d postgres -c "SELECT 1;" >/dev/null 2>&1; do
  count=$((count + 1))
  if [ $count -ge $max_retries ]; then
    echo "[init-postgres] ERROR: Timed out waiting for shared-postgres after ${max_retries} attempts." >&2
    exit 1
  fi
  sleep 1
done

echo "[init-postgres] shared-postgres is ready! Verifying and provisioning application databases..."

for db in zilean mediafusion aiometadata sootio; do
  echo "[init-postgres] Checking database '$db'..."
  exists=$(psql -v ON_ERROR_STOP=1 -h shared-postgres -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$db';")
  if [ "$exists" != "1" ]; then
    echo "[init-postgres] Creating database '$db'..."
    psql -v ON_ERROR_STOP=1 -h shared-postgres -U postgres -d postgres -c "CREATE DATABASE $db;"
    echo "[init-postgres] ✓ Database '$db' created."
  else
    echo "[init-postgres] ✓ Database '$db' already exists."
  fi
done

echo "[init-postgres] All application databases successfully verified and ready!"
exit 0
