#!/bin/bash
set -e

# Load environment variables from .env file
set -a
if [ -f .env ]; then
    source .env
else
    echo ".env file not found. Please create one based on .env.example."
    exit 1
fi
set +a

DB_URL_NO_PROTOCOL=$(echo $DATABASE_URL | sed 's/postgresql+asyncpg:\/\///')

DB_USER=$(echo $DB_URL_NO_PROTOCOL | cut -d':' -f1)
DB_PASSWORD=$(echo $DB_URL_NO_PROTOCOL | cut -d':' -f2 | cut -d'@' -f1)

HOST_PORT_DB=$(echo $DB_URL_NO_PROTOCOL | cut -d'@' -f2)

DB_HOST=$(echo $HOST_PORT_DB | cut -d':' -f1)
DB_PORT=$(echo $HOST_PORT_DB | cut -d':' -f2 | cut -d'/' -f1)
DB_NAME=$(echo $HOST_PORT_DB | cut -d'/' -f2)

# Set psql environment variables
export PGUSER=$DB_USER
export PGPASSWORD=$DB_PASSWORD
export PGHOST=$DB_HOST
export PGPORT=$DB_PORT
export PGDATABASE=$DB_NAME

echo "Running schema migration for database: $PGDATABASE on $PGHOST:$PGPORT..."
psql -f sql/schema.sql

echo "Seeding data for database: $PGDATABASE..."
psql -f sql/seed.sql

echo "Migration and seeding complete."