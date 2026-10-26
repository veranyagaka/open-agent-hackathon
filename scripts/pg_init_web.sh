#!/bin/sh
# Runs once inside the stockwhy-pg container on first start (docker-compose.yml): creates the public-notices
# database and loads it, so Zetaris can federate it as a second datasource.
set -e
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE \"$PG_WEB_DATABASE\""
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$PG_WEB_DATABASE" -f /seed/web_notes_load.sql
