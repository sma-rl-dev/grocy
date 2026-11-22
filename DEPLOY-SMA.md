# Grocy tester environment

Baseline: `v4.7.1` — `7d15c46bbdc35d4958cae99209ba170667dc1d64` (latest stable
GitHub Release, 2026-09-04; `master` is 7 commits ahead and still declares 4.7.1).

Fork: <https://github.com/sma-rl-dev/grocy>, branch `tester-env-baseline` =
upstream v4.7.1 plus one tooling-only commit (the files listed under
"Tooling files" below; no upstream file modified). In the corpus this fork is the
submodule at `apps/grocy`, and `app_cli = "tester-env"` is submodule-relative.
Upstream publishes no Dockerfile, so `Dockerfile.tester-env` here mirrors the
documented source install: composer into `./packages`, yarn 1 into
`./public/packages`, Apache document root `public/`.

## Quick Start

```bash
./tester-env deploy    # Build image, start container, migrate, verify login
./tester-env seed      # Create the deterministic household data
./tester-env verify    # Assert login, /stockoverview and every seeded record
./tester-env reset     # Clean slate (container + data dir removed)
./tester-env stop      # Stop container, keep /data
./tester-env logs      # Tail Apache/PHP logs
./tester-env status    # Container, URL, credentials
```

`./tester-env --help` lists options (`--run-id`, `--port`) and caveats.

## Stack

- One `php:8.5-apache` container, host port `8088` → container port 80.
- No database service: SQLite, `data/config.php` and `viewcache/` live in the
  `./.tester-env-data` bind mount at `/data` (override with `DATA_DIR`).
- Extensions: `gd`, `intl`, `pdo_sqlite`, `mbstring`; fileinfo/ctype/zlib/iconv/
  tokenizer/json are built in. The Dockerfile asserts `PASSWORD_ARGON2ID` exists
  because migration 0027 hashes the default admin password with argon2id.
- `mod_rewrite` is enabled, so pages are at `/stockoverview`, `/login`, ...
  (`DISABLE_URL_REWRITING=false`). The no-rewrite mode only routes
  `/index.php/...` when `GROCY_BASE_PATH=/index.php` and still emits
  `/index.php/` URLs, so rewriting is the simpler path.

## Credentials and first run

- `admin` / `admin`, ADMIN permissions. Migration 0027 creates it, so first-run
  setup is deterministic.
- Only `GET /` runs the migrations (`SystemController::Root`). The first request
  only redirects to itself after touching the config-hash cache file, so the
  deploy health check follows redirects until it gets a 200.
- `deploy` creates `/data/config.php` from `config-dist.php` when absent and
  applies settings through `GROCY_*` environment variables (which outrank
  `config.php`).

## Environment

| Variable | Default (compose) |
|---|---|
| `GROCY_DATAPATH` | `/data` |
| `GROCY_MODE` | `production` (demo mode disables auth and uses week-relative data) |
| `GROCY_DEFAULT_LOCALE` | `en` |
| `GROCY_DISABLE_URL_REWRITING` | `false` |
| `GROCY_BASE_PATH` / `GROCY_BASE_URL` | empty / `/` |
| `GROCY_STOCK_BARCODE_LOOKUP_PLUGIN` | empty (no OpenFoodFacts lookups) |
| `TZ` + `date.timezone` | `UTC` |
| `IMAGE_TAG` | set by `scripts/rl-env` (content-addressed); manual runs use `tester-env-grocy:dev` |

## Reset

`./tester-env reset` stops the container, removes it and deletes
`.tester-env-data<run-id>`. `/data` is written by `www-data` (uid 33), so reset
clears it through a throwaway process of the same image before removing the
directory — a plain host-side `rm -rf` can hit permission errors.

## Build cost

- Dependency stages are separate and cached (composer cache mount, yarn cache
  mount), so PHP/JS edits only re-run `COPY . .` + `composer dump-autoload`.
- Measured: cold build ~3 min first time, `--no-cache` rebuild with warm package
  caches 92 s, JS source edit 8 s including restart and verify. Image 821 MB.
- Composer pulls two VCS dev branches (`berrnd/lessql`, `berrnd/php-gettext`),
  so the first build needs network access and `git`.

## Seed data

`./tester-env seed` runs `tester-env-seed.py` (host `python3`) against the
running app: it logs in as `admin/admin`, wipes only the business data the seed
owns, then recreates it over the object/stock API (no direct SQLite writes).
`./tester-env verify` re-reads every value through the same API plus six
authenticated pages. The static requirement manifest is `tester-env-seed.json`.

Theme: a shared household ("Maple Street") keeps its kitchen stock in Grocy.

Master data (fixed, deterministic):

| Entity | Values |
|---|---|
| Locations | `Fridge` (migration default; products without an explicit location), `Freezer` (is_freezer=1), `Pantry`, `Cellar` |
| Quantity units | default `Piece`, `Pack` plus `Bottle`/`Bottles`, `Can`/`Cans`, `Loaf`/`Loaves` |
| Product groups | `Dairy & eggs`, `Bakery`, `Produce`, `Pantry staples`, `Drinks`, `Household` |
| Shopping locations | `Corner Grocer`, `Riverside Market` |
| Products | 12 products with description, group, location, store, unit, min stock and active flag |
| Barcodes | `4001234567890` Whole milk, `4009876543217` Free-range eggs |

Products and stock (amount, best before, purchased, price):

| Product | Amount | Entries |
|---|---|---|
| Whole milk | 5 | 3 @ 2026-11-29 (buy 2026-11-16, 1.19), 2 @ 2026-12-06 (buy 2026-11-21, 1.19) |
| Free-range eggs | 2 | 2026-12-02 (buy 2026-11-15, 2.49) |
| Sourdough loaf | 1 | 2026-11-24 (buy 2026-11-21, 3.20) |
| Unsalted butter | 2 | 2027-01-15 (buy 2026-11-05, 2.10) |
| Greek yoghurt | 1 | 2026-11-26 (buy 2026-11-19, 1.75); min 2, so below minimum |
| Cherry tomatoes | 2 | 2026-11-27 (buy 2026-11-20, 1.40) |
| Frozen peas | 2 | 2027-04-30 (buy 2026-09-30, 1.60) |
| Basmati rice | 3 | 2027-10-31 (buy 2026-10-12, 3.49) |
| Vegetable stock cubes | 3 | 2027-05-31 (buy 2026-10-12, 1.85) |
| Sparkling water | 8 | 2027-08-31 (buy 2026-11-08, 0.45) |
| Dish soap | 0 | none; min 2, so below minimum and out of stock |
| Coffee beans | 0 | none; `active=0` (discontinued), hidden from `/products` |

Other seeded records:

- Shopping lists: `Weekly groceries` (the renamed default list, so plain
  `/shoppinglist` works) with Dish soap 2 (`Lemon scent`), Greek yoghurt 2
  (`500 g tubs`), Coffee beans 1 (`Whole beans, medium roast`); `Weekend market`
  with Cherry tomatoes 1 (`Ask for the vine ones`) and the note-only item
  `Collect the bread order`.
- Chores (next execution, all absolute): `Water the herbs` 2026-11-23 08:00,
  `Clean the fridge` 2026-11-28 10:00, `Defrost the freezer` 2026-12-15 09:00,
  `Take out the recycling` 2026-11-23 09:30 (weekly Monday, last tracked
  2026-11-17 09:30).
- Tasks: `Order a replacement fridge filter` (open, due 2026-11-10),
  `Clean the gutters` (open, due 2026-11-29), `Book the boiler service` (done
  2026-11-05 14:20) in categories `Household` and `Garden`. Due dates are
  date-only like the task form writes them; the `/tasks` statistics widget adds
  ` 23:59:59` to `due_date` (`public/viewjs/tasks.js:211`), so a stored
  datetime would make moment() return `Invalid date` and the overdue/due
  counters read 0 while the row stays red from the server-side `due_type`.
- Recipe: `Winter vegetable soup`, 4 servings, positions Cherry tomatoes 2,
  Frozen peas 1, Vegetable stock cubes 2; fully in stock, cost 8.10.

Determinism: two full `reset -> deploy -> seed -> verify` cycles and one
`--run-id seedcheck --port 58088` cycle produced byte-identical canonical state
digests (ids excluded), and a second `seed` without reset reproduces the same
digest. `reset && deploy` without `seed` makes `verify` fail with
`locations are Fridge/Freezer/Pantry/Cellar [Fridge]` (exit 1) while `deploy`
still passes. After the task due dates were normalized to date-only (see
Tasks above), a reseed and one more full reset cycle reproduced the same digest
again; only the three `tasks.due_date` values differ from the earlier digest.

Re-seeding: the seed deletes only its own products (which cascade stock,
stock logs, barcodes, recipe positions and shopping-list items), recipes,
chores, tasks, task categories, extra lists, product groups, extra locations,
extra quantity units and shopping locations, then rebuilds them. The migration
defaults (`Fridge`, `Piece`, `Pack`, default list id 1) are reused.

## Notes

- `public/js/*.js` is plain editable frontend source served as-is; there is no
  bundler step, so JS mutations need no rebuild.
- Seed data is app-owned: `tester-env-seed.py` (seed + verify) and
  `tester-env-seed.json` (manifest) live next to `tester-env`; the CLI calls
  them, so `./tester-env seed|verify` is the only supported entry point.
- Tooling files (`tester-env`, `tester-env-seed.py`, `tester-env-seed.json`,
  `Dockerfile.tester-env`, `docker-compose.tester-env.yml`,
  `docker/tester-env-entrypoint.sh`, `.dockerignore`, `DEPLOY-SMA.md`) live in the
  fork's `tester-env-baseline` tip so `scripts/rl-env` can pin a `tooling_ref`.
- Evidence provenance: build/deploy/reset/seed/verify were run by app-deployer and
  seed-engineer from this checkout; the browser smoke and seed verification were
  done by browser-checker. No browser tool is used by this CLI.

## Verified commands

```bash
./tester-env reset && ./tester-env deploy   # fresh /data, 257 migrations, admin/admin
./tester-env seed && ./tester-env verify    # household fixtures, exit 0
./tester-env stop                           # container stopped, /data preserved
```
