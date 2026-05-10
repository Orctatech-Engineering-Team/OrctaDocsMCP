#!/bin/sh
docker compose exec -T postgres psql -U postgres -c   "ALTER USER postgres WITH PASSWORD 'postgres';" 2>/dev/null &&   echo "[ok] postgres password ensured" ||   echo "[warn] postgres not ready yet - run this script again after a few seconds"
