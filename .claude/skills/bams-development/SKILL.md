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
- A new permission is not in the stored permission lists of existing accounts: `Auth._user()` adds `maintenance.cost` for `users.manage`.
- Script files share one global scope: no short top-level names in new JS files. `<a data-act>` needs `data-href`
  to reach `ACT` – use `<button>` for in-page actions.
