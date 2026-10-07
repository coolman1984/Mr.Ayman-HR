---
name: bams-development
description: Project knowledge for the Break Area Management System (BAMS) - architecture, file map, invariants, how to test, build the Windows installer and release, and the pitfalls learned so far. Load it before changing anything in this repository, and update it whenever something new is learned.
---

# BAMS – how this program works and how to change it safely

Read `CLAUDE.md` (rules) first. This skill is the working knowledge; `DEVELOPMENT_HISTORY.md` is the history;
`IDEAS.md` is the book of reusable ideas (for other projects too).
**Update this file in the same pull request whenever you learn a new rule, pitfall, file or command.**

## What it is

A factory web app for break areas (inventory, issues, maintenance, inspections, surveys, photos, reports) used by
non-technical people. Python standard library only (no pip packages at runtime) + SQLite + plain JavaScript.
Runs on one PC or on several PCs that each keep all data and share changes (offline-first).

Two ways to run:
- **Installed** (normal): `BAMS-Setup.exe` → `C:\Program Files\BAMS\BAMS.exe` (Nuitka-compiled, pages inside),
  data in `%ProgramData%\BAMS` (`BAMS_HOME`). Entry `server/bams_main.py`.
- **Portable / development**: `start.bat` or `python server/app.py`, everything in the program folder.

## File map

| File | Role |
|---|---|
| `server/app.py` | HTTP server, routes, permission checks per request, static pages (`serve_static`: from `_assets` when installed) |
| `server/auth.py` | people, passwords (PBKDF2), sessions, permissions (`PERMISSIONS`, `ADMIN_PERMS`), personal links, profiles, `UserFolder` |
| `server/store.py` | business data: `commit` → changeset, specs per entity, conflicts, restore |
| `server/journal.py` | signed hash-chained changesets, receive rules (`_check`), logs (audit/activity/security), alerts; `SCHEMA` |
| `server/replica.py` | deterministic fold: registers, counters (inventory qty), deletes, conflict flags, markers |
| `server/sync.py` | TLS sync between PCs, pairing, peers, attachments, warnings (`_quiet_pcs`); `SCHEMA_VERSION` |
| `server/node.py` | PC identity, keys, authority key (administrator PC only), machine fingerprint (clone detection) |
| `server/system.py`, `backup.py` | start-up, upgrade, backups, compensating restore |
| `server/nodectl.py` | maintenance tools (`BAMS.exe tool …`) |
| `server/version.py` | VERSION, developer, copyright – the build reads it |
| `js/app.js`, `js/devices.js` | whole UI (views, `ACT` actions, `modal`, `esc` for every value) |
| `js/data.js` | sample data (`buildSeed`, fixed short ids), `DEFAULT_ITEM_TYPES`, lists (actions, conditions) |
| `js/palette.js`, `js/icons.js` | Ctrl K search; generated icon pack |
| `server/office.py` | office mode: a PC without data that opens the administrator PC like a personal link (small page on 127.0.0.1) |
| `server/upgrade.py` | data safety at every update (snapshot, verification, newer-data refusal, migrations) |
| `server/xlsx_read.py`, `server/excel_import.py` | Excel reader and the import rules |
| `js/help.js` | Help & User Guide (`#/help`): Q&A per topic, admin topics hidden from others – **update it with every screen change** |
| `tools/` | `make_assets.py`, `make_icon.py`, `build_windows.py` |
| `installer/bams.iss` | Inno Setup script (install + update, firewall, autostart, old data import) |
| `.github/workflows/build.yml` | tests + Windows build; publishes release `v<version>` from `main` |

## Invariants (never break)

- PCs exchange changesets only, never DB files. Every change is signed by its PC; user/permission/profile/device
  changes are `admin` changesets signed with the authority key (administrator PC only).
- Fold is deterministic on every PC; dependencies (`deps`) come from what was folded (markers), not received.
- Deletes are durable, history is never rolled back, restore = new compensating change.
- A personal link never carries any `ADMIN_PERMS` (checked in `save_user`, `save_profile`, `link_set`,
  `link_allowed`, and in `session()` for every request).
- Tokens/passwords/keys never in logs (`Handler.log_path` hides `/k/…`).
- A new field or entity that older PCs would drop → raise `journal.SCHEMA` and `sync.SCHEMA_VERSION`.
- Sharing cannot be switched off.
- The administrator key leaves the administrator PC only: sealed with a passphrase (`export-key`, on the PC itself) or
  over the pinned TLS sync connection to a PC whose roster role is `backup` (`/sync/authority`).
- Local-only actions (first setup, key export, backup folder) check `self.ip in LOCAL_IPS`.
- UI: English only, plain words; administrators see sync details, normal users only "Please tell the administrator".

## Tests

`cd tests && python3 -m unittest test_unit test_convergence` (fast), `test_multinode` (real processes, ~3 min),
`test_e2e_browser` (Playwright/Chromium). Harness: `tests/harness.py` (`Server`, `Client`, `make_authority`, `pair`,
`TcpProxy` to unplug a PC). Scenario map in `TASKS.md`. Add a regression test for every fix.

## Build and release

See `docs/BUILD_AND_RELEASE.md`. Bump `server/version.py`, update `DEVELOPMENT_HISTORY.md` +
`docs/RELEASE_NOTES.md`, merge → GitHub builds and publishes `BAMS-Setup-X.Y.Z.exe` as release `vX.Y.Z`
(once per version). This session cannot push tags (git proxy 403) – releases come from the workflow on main.
Check a local compile on Linux: `pip install --target <dir> nuitka ordered-set zstandard patchelf`, then
`python -m nuitka --standalone … server/bams_main.py` (see `tools/build_windows.py` for the options).

## Pitfalls learned (add new ones here)

- Don't edit `server/` or `js/` while multi-PC/browser tests run.
- `pkill -f` / `ps | grep` also match your own shell command → kill by process name or PID.
- `<meta name="referrer" content="no-referrer">` makes form posts send `Origin: null` (refused by the CSRF check).
- New replicated fields need `ALTER TABLE` for old databases and a schema raise (see invariants).
- A new change after a link/profile change must be tested on a second PC after `converged()`.
- Inno Setup: never delete `{app}\*` by wildcard; start the program with `runasoriginaluser`.
- Keep the review → fix → regression-test loop; independent reviews found real bugs every time.
- Static files: only `index.html` and `css/ js/ lib/` with known extensions (`serve_static`); the portable program
  folder also holds `data/` and keys.
- Record ids must be random (never `length + 1`): PCs create records offline at the same time.
- Never trust internal options from the client (`resolve` is refused in `/api/commit`); check old *and* new area.
- One program per data folder (`system.lock_data`); tools (`nodectl`) need the program stopped.
- Before login: 64 kB requests and max 10 failed logins per minute per address (`too_many_failures`).
- Tests must build the situation they check (e.g. write a `.part` file) instead of relying on timing; CI machines
  are faster/slower than the dev machine. CI checkout needs `fetch-depth: 0` (upgrade tests read old commits).
- Tags cannot be pushed from the Claude session (403): the workflow publishes the release on main by itself.
- The installed program is the normal case: never mention `start.bat`/`reset_admin.bat` in user texts (portable is
  for developers only). Search `js/`, server messages and guides when delivery changes.
- A removed (revoked) PC never receives its removal: undo local powers on the refusal itself and at start
  (`check_backup_role`, `Revoked` handler). A backup administrator PC cannot export the key or remove the administrator PC.
- Sample data = break areas `ba01..ba22` named "Break Area NN" (`isSampleArea`); Delete Sample Data removes only those.
- The PC list (`nodes`) has several authors (administrator + backup PCs): `_fold_roster` keeps the newest change per
  field by (hlc, origin, cseq); a removal is final. Any new multi-author table needs the same.
- Before merging, wait for the automatic PR reviews too (they may arrive after CI is green).
- Since 2.4 new PCs join without code or approval (`join_open`, `_open_join`, `discover`, `/sync/hello`); the code
  method is still in `sync.py` (used by the test harness `pair()`), but not in the screens.
- The first start asks empty / sample data (`firstStartChoice`); browser tests must click the choice.
- Sample records are recognised by id *and* content of `buildSeed()` (`seedKeys`, `isSampleRec` in `js/app.js`), never
  by names (people rename sample break areas) and never by id pattern alone (the first program version saved real
  records with short ids like `h121`). `buildSeed()` must stay deterministic (no today(), no random).
- A window (`modal`) must not save records from before a reload: `save()` failing calls `load()`, which replaces `DB`.
  `modal()` remembers `DB` and the opening action (`OPENER`) and reopens itself (`reopenFresh`). New dialogs must be
  opened through an `ACT` action to get this.
- `form.elements.item` / `form.elements['item']` is a method – look fields up with `[name=…]`.
- Serial numbers: entity `pieces` (one record per piece, area child); the quantity stays the `inventory` counter.
  Any change of an item's quantity must think about its pieces (Removed/Transferred pick them, Delete Item and
  item-type delete remove them).
- Area-limited users: anything that affects all break areas (item type delete, backup restore, Recycle Bin, new
  break areas) needs "all areas" in the screen *and* on the server.
- The stylesheet is `css/styles.css` (not style.css).
- Area Log (`notes` entity, `areaTimeline`) and work: maintenance fields kind, cost, contractor, warrantyUntil, issueId, serial, repeatMonths;
  status `Cancelled` ranks below `Done`. Use `isOpenWork(m)` (not `status !== 'Done'`) for "still to do".
- Costs: `maintenance.cost` permission. The server hides `cost` in `/api/state`, `/api/audit` (`hide_costs`) and the Excel export (`cost=`) and
  restores it on save for people without the right. Any new place that lists maintenance rows or their changes must do the same.
- **Updates must never lose data**: `server/upgrade.py` runs at every start (snapshot in `data/upgrades/`, old rows compared before / after, refusal of newer data). A change
  that REWRITES existing data must be a `MIGRATIONS` step that declares the tables it touches; adding columns / entities is free. Before each release add its commit to
  `T41_UpgradeKeepsData.RELEASES` (the test runs the real old program on a data folder, then the new one). `Server(app=…)` starts another program version in tests.
- Text sizes: never write `font-size: 13px` in `css/styles.css` - write `calc(13px * var(--fs))` (`AppearanceFilesTest` fails otherwise); the font comes from `var(--font)`. New static folders go into `STATIC_DIRS`, `serve_static` and `tools/make_assets.py`.
- Never replace `DB` under an open window: background refreshes use `load(true)`; anything else that reloads (a save from outside a window) must finish before a window can open. Browser tests: wait for `#modal.open` to detach after the first-start choice.
- A PC only shares data after it JOINED (`Join an existing system`); a PC set up as a first PC is a separate system. Every text that tells someone how to start must say so (`startInstructionsModal`). `/api/node/leave` rescues a lone PC.
- In `do_POST` the routes before the session is read are public; authenticated routes (with `self.need`) go after it.
- Icons: `js/icons.js` is generated (`tools/make_icons.py`, Lucide, ISC) - never edit it by hand; `IconPackTest` fails when a screen uses an icon that does not exist.
  Since 2.8: ~600 icons in 15 `GROUPS` (a new name with an already offered drawing is dropped), new names = camelCase Lucide names, `ICON_TAGS` = search words. Never rename/remove a `PACK` name (item types
  store it). Regenerate: `npm pack lucide-static` into an EMPTY scratch folder (check the folder first – a failed `cd` unpacked it into the repo once),
  `tar -xzf`, then `python tools/make_icons.py <that folder>/package`. A name already drawn in `IC` (app.js) keeps that drawing.
- Dashboard (2.8): `dashKpis()` = one list ordered by importance, the first ten the person may see (`maintenance.view`, `surveys.view` cards are skipped), links use
  `pageHref` (`PAGE_PERMS`). Per-category overviews use `rankList()` (first 8 + Show all), never one column per category – the real factory has ~60 item types.
  Always check a screen with many item types (55+) and at 1366 / 1024 / 390 px.
- Look (2.8): Samsung UI kit (`D:\WORK\Software Development\GitHub\samsung-ui-kit\samsung-ui-kit`, `samsung-ui.css`) – base text 14 px, icons 20 px,
  cards radius 16, pill buttons. Keep `calc(Npx * var(--fs))` for every size.
- Windows dev PC: `NodeSafetyTest.test_interrupted_upgrade_is_repeated` and `ToolsTest.test_rebuild_gives_identical_data` fail with `PermissionError`
  (SQLite files cannot be renamed while open) – also on `main`; CI on Linux is the reference.
- Look at the screens without touching real data: `BAMS_CONFIG=<scratch>/config.json` with its own `data_dir`, port and sync port, `python server/app.py`.
  Playwright: if its Chromium is missing use `pw.chromium.launch(channel='msedge')`; accept dialogs (`page.on('dialog', d => d.accept())`) – the
  "first PC" choice asks for confirmation.
- Running the PC tests on Windows: the harness stops servers with SIGINT (Linux only) – patch `harness.Server.stop` to `proc.terminate()`.
  With Edge, `test_font_and_text_size_choice`, `test_area_log_finished_work_and_repeats` and `test_new_pc_screens_and_instructions` fail on
  console "401 / 404 Failed to load resource" (status check before login, favicon) – also on `main`; CI with Chromium is the reference.
- Excel import (`excel_import.plan`) never changes what exists; a new importable field needs a column name list, a warning for bad values, and a test in `ExcelImportTest`.
- `repr()` / `str()` of Python data is not JavaScript: write generated JS with explicit brackets.
- A new permission is not in the stored permission lists of existing accounts: `Auth._user()` adds `maintenance.cost` for `users.manage`.
- **Office mode** (2.7, `server/office.py`): config.json `office_url` → `BAMS.exe` runs only the small page on 127.0.0.1 (no `app` import, no data).
  Links and office mode use the web port 8080; join/sharing use 8443 (often blocked in company networks). After a switch the old server must close
  kept-alive browser connections (`OFFICE_SWITCH` in `do_GET/do_POST/send`). `BAMS.exe tool use-this-pc` ends it. Tests: `T44_OfficeMode`, `OfficeModeTest`.
- A page on 127.0.0.1 is reachable by any web site through DNS rebinding: local-only routes check Host/Origin with `office.local_request`, not only the IP.
- Never weaken login security (longer sessions, "remember me", fewer checks) without the owner's explicit yes – the session's safety check refuses it.
- Script files share one global scope: no short top-level names in new JS files. `<a data-act>` needs `data-href`
  to reach `ACT` – use `<button>` for in-page actions.
