#!/bin/bash
set -e

echo "Running schema migration..."
psql $DATABASE_URL -f sql/schema.sql

echo "Seeding data..."
psql $DATABASE_URL -f sql/seed.sql

echo "Migration and seeding complete."
