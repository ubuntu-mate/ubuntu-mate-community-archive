#!/usr/bin/bash -e
#
# Sets up a local container running Postgres to access a Discourse database backup.
#
# This script can only be run by the administrator with the database backup,
# since the database backup will never be public.
#
BACKUP_FILE="$1"
CONTAINER_NAME="discourse-db"

if [[ -z "$BACKUP_FILE" || ! -f "$BACKUP_FILE" ]]; then
    echo "Usage: import_db.sh <discourse_tar_gz>"
    exit 1
fi

# Already imported? Delete it.
if podman ps -a --format '{{.Names}}' | grep -q "^$CONTAINER_NAME\$"; then
    echo "Removing old container: $CONTAINER_NAME..."
    podman rm -f "$CONTAINER_NAME"
fi

# Start it up!
podman run \
  --name "$CONTAINER_NAME" \
  -e POSTGRES_PASSWORD=pass \
  -e POSTGRES_USER=discourse \
  -e POSTGRES_DB=discourse \
  -p 5432:5432 \
    postgres:14 &
CONTAINER_PID=$!

# Wait for container to start
until podman exec discourse-db pg_isready -U discourse -d discourse >/dev/null 2>&1; do
    if ! kill -0 "$CONTAINER_PID" 2>/dev/null; then
        wait "$CONTAINER_PID"
        exit 1
    fi
    sleep 1
done

# Import SQL directly from Discourse backup
tar -xOzf "$BACKUP_FILE" dump.sql.gz | gzip -dc | podman exec -i discourse-db psql -U discourse -d discourse

echo "Import complete. \"$CONTAINER_NAME\" running. Press CTRL+C to stop."
podman attach "$CONTAINER_NAME"
