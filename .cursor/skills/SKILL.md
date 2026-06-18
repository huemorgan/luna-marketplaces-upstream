---
name: clone-prod-db
description: >-
  Clone the production PostgreSQL database to local. Use when the user asks to
  copy, clone, sync, or pull production data locally, or mentions "prod db".
---

# Clone Production DB to Local

## Connection Details

- **Production**: Render PostgreSQL 16 (`marketracking-db`)
  - Host: `dpg-d7fm61flk1mc73dhcas0-a.oregon-postgres.render.com`
  - Database: `marketracking`
  - User: `marketracking_user`
  - Password: `c9mAvNNNK0fAkfmUN4Pad4dUj4hYNpyR`
- **Local**: `postgresql://roy@localhost:5432/funnel_fighters`

## Steps

1. **Set PATH** for the matching PostgreSQL 16 client tools:

```bash
export PATH="/opt/homebrew/Cellar/postgresql@16/16.13/bin:$PATH"
```

2. **Dump production** (compressed custom format, ~11MB, takes ~45s):

```bash
PGPASSWORD=c9mAvNNNK0fAkfmUN4Pad4dUj4hYNpyR pg_dump \
  -h dpg-d7fm61flk1mc73dhcas0-a.oregon-postgres.render.com \
  -U marketracking_user \
  -d marketracking \
  --no-owner --no-acl -Fc \
  -f /tmp/prod_dump.dump
```

3. **Kill local connections, drop, and recreate** the local DB:

```bash
psql -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'funnel_fighters' AND pid <> pg_backend_pid();"
dropdb --if-exists funnel_fighters
createdb funnel_fighters
```

4. **Restore** into local:

```bash
pg_restore --no-owner --no-acl -d funnel_fighters /tmp/prod_dump.dump
```

5. **Verify** with a quick count:

```bash
psql -d funnel_fighters -c "SELECT 'tracked_users' as tbl, count(*) FROM tracked_users UNION ALL SELECT 'organizations', count(*) FROM organizations UNION ALL SELECT 'product_events', count(*) FROM product_events;"
```

## Notes

- The dump uses `-Fc` (custom format) which is compressed and supports parallel restore.
- `--no-owner --no-acl` avoids permission issues since local user is `roy`, not `marketracking_user`.
- If `pg_dump` is not found, check `/opt/homebrew/Cellar/postgresql@16/*/bin/`.
- The local server (if running) will lose its connection when the DB is dropped — restart it after restore.
- If `psql` is also missing, you can test connectivity via Node: `node -e "require('pg').Pool({connectionString:'...'}).query('SELECT 1')"`
