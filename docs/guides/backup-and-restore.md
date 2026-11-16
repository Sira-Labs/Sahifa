# Backup and restore

For an install from the compose bundle (`deploy/quickstart.md`). The commands run in the folder
that holds `compose.yaml` and `.env`. The CI job `quickstart` runs the backup and the restore
below after its scans and checks that the scans are still there.

## What to back up

| What | Where it lives | Back it up? |
|---|---|---|
| Everything Sahifa knows: connections, scans, reports, checks, findings and their history, workspaces, members, schedules, the audit log | the database, volume `pgdata` | **yes** |
| The settings and the logins to your sources | `.env`, `compose.override.yaml` | **yes**, they hold passwords: store them like passwords |
| Uploaded files | volume `data` | no: Sahifa deletes them `SAHIFA_UPLOAD_TTL_DAYS` after their scan; the reports are in the database |
| TLS certificates | volume `caddy_data` | no: Caddy gets new ones on start |

Your sources are not part of this: Sahifa only reads them.

## Back up

```bash
stamp=$(date +%F-%H%M%S)
docker compose exec -T db pg_dump -U sahifa -d sahifa --format=custom > "sahifa-$stamp.dump"
cp .env "env-$stamp.backup"
cp compose.override.yaml "compose.override-$stamp.yaml"
```

- It runs while Sahifa is in use; the dump is one consistent state.
- The names carry the time to the second, so a second backup on the same day (one before an
  update, one after) does not overwrite the first.
- Write down the version next to it (the footer of every page shows it, or
  `docker compose exec api python -c "import sahifa; print(sahifa.__version__)"` and the
  `SAHIFA_TAG` in `.env`): a dump restores into the same version or a newer one.
- Keep the files somewhere else than the machine Sahifa runs on. Once a day is a reasonable
  start, for example from cron:

  ```cron
  15 2 * * *  cd /home/me/sahifa && docker compose exec -T db pg_dump -U sahifa -d sahifa --format=custom > /backup/sahifa-$(date +\%F-\%H\%M\%S).dump
  ```

- Take one before every update.

## Restore

On the machine that should run Sahifa. On a new machine, follow the quick start first, but
put the `.env` and the `compose.override.yaml` you saved in place of the downloaded ones (the
override holds your folders and other changes), and let it start once: the first start
creates the database roles the dump refers to.

```bash
dump=sahifa-2026-11-17-021500.dump
docker compose stop api worker &&
  docker compose exec -T db dropdb -U sahifa --force sahifa &&
  docker compose exec -T db createdb -U sahifa sahifa &&
  docker compose exec -T db pg_restore -U sahifa -d sahifa --no-owner --exit-on-error < "$dump" &&
  docker compose up -d
```

- The steps are chained with `&&` on purpose: when one fails, the rest does not run, and
  Sahifa is not started on a database that was only partly restored. Fix what the failed
  command reports and run the block again; it starts from an empty database each time.
- `docker compose ps` shows `api` healthy after a few seconds; the scans, checks and findings
  are back, and people sign in as before.
- **The image must be as new as the dump, or newer.** A newer image brings the database up to
  its version when it starts. An older image stops with `db.schema_mismatch` in its log: set
  `SAHIFA_TAG` to the version the dump was taken with.
- Uploaded files are not in the dump. Reports of uploads stay complete; scanning the same files
  again needs a new upload.
- Scans that were running when the dump was taken come back as queued or running and are
  marked failed within minutes; start them again.

## Going back after an update

An update may change the database, and an older image does not start on a newer database. To
go back to the version before, restore the dump taken before the update with `SAHIFA_TAG` set
to that version.

## Test it once

A backup that was never restored is a hope. On another machine, or in another folder with
another project name (`docker compose -p sahifa-restore-test ...`, other ports in
`compose.override.yaml`), follow *Restore* with last night's dump and open the scans list.
