# Development History and Lessons Learned

This file is the memory of the project. **Every change adds an entry here** (newest first): what changed, why, which
mistakes were made and what we learned. It is kept up to date together with the code (see `CLAUDE.md`).

Version numbers: `server/version.py`. Pull requests: github.com/coolman1984/Mr.Ayman-HR/pulls.

---

## 2.7.0 – Use the office system: a PC that opens the administrator PC like a personal link (2026-10-01)

**Why (field report):** the owner installed 2.6.0; in the office only the **personal links** worked – a PC with the program and a user name /
password never connected ("Join an existing system" failed). The owner asked to use the way that works (the link) together with the installed
program and the user name and password, so that people "do not feel anything", and to drop logic that does not work in their network.

**Root cause:** a personal link uses the **web port 8080** of the administrator PC; joining and sharing between PCs use the **separate TLS port
8443**. The office network lets 8080 through and blocks 8443 (the Devices & Sync screenshot also showed an unusual address, `106.x`, which points to
a managed company network). Nothing in the program can open a port that the network blocks.

**What changed**
- New **office mode** (`server/office.py`): config.json `office_url`. `BAMS.exe` then starts only a tiny page on 127.0.0.1 that checks the
  administrator PC (`/api/auth/status`) and redirects the browser there, or shows "The system cannot be opened right now" with *Try again* and a
  box for a new address. No database, no sharing, no keys on that PC; `--background` (Windows start) does nothing.
- First screen: **Use the office system (recommended)** first, then *Join an existing system (full copy)*, then *first PC*. The address is found by
  scanning the local /24 networks on the web port, or typed and checked live (`/api/office/discover|probe|use`, only on the PC itself, only while it is
  not set up). A whole web address or a personal link is understood.
- Rescue: **Devices & Sync → Use the office system instead** (`/api/node/office`, administrator of that lone PC, on the PC itself, only while it shares
  with no other PC; a backup `pre-office` is made; its data stays untouched).
- `BAMS.exe tool use-this-pc` ends office mode. Instructions after *Add Person*, Help, guides and README describe the new way.
- Version 2.7.0, no schema change (2.6 and 2.7 PCs work together). `T41` now also starts the real 2.6.0 program.

**Mistakes and lessons**
- First idea also contained "Keep me logged in on this PC" (long login for non-administrators) to make it feel like a link. The automatic safety check
  of the session refused it as a weakening of login security; it was taken out completely and left to the owner's explicit decision. Lesson: changes
  that weaken security need the owner's explicit, informed yes – ask first.
- The browser test found a real bug: after the switch, Chrome kept its open keep-alive connection to the old server and showed the old setup page.
  Fix: after the switch the old server answers every request on old connections with a redirect / "reload" and closes the connection.
- Independent review (all fixed, with tests): **DNS rebinding** – a web page whose name is switched to 127.0.0.1 sends its own name as Host and
  Origin, so "Origin equals Host" was not enough; the small page and the office endpoints now accept only Host/Origin `localhost`/`127.0.0.1`
  (`office.local_request`), otherwise a web site could point every PC at a fake login page. A device in the network that does not speak proper HTTP
  (`http.client.HTTPException`) broke the search; the live address check of the rescue window used a route closed for a set-up PC (`?check=1` now);
  the old backup thread kept running after the switch; old `/api/` calls got redirects instead of a clear answer; bare IPv6 addresses; `0.0.0.0` /
  `127.0.0.2` were not recognised as this PC; the portable start ignored `--background`; the security log could say "switched" before the setting
  was written. Lesson: a page on 127.0.0.1 is reachable by every web site through DNS rebinding – always check Host, not only Origin.
- `T44` checks the sharing port is *not* accepted as a web address (`Nothing answers`), the address of this PC is refused, and another web site cannot
  change the saved address (Origin check on the small page).

---

## 2.6.0 – Area Log, finished work, costs by permission, repeating work, piece history (2026-09-30)

**Why:** the owner asked whether a break area can carry notes (painting, renovation, repairs, maintenance) and to think through the real cases; all three
proposed phases were built, each shown with screenshots before the next.

**What changed** (`journal.SCHEMA` and `sync.SCHEMA_VERSION` 4 → 5)
- **Phase 1:** new entity `notes` (Area Log) + `areaTimeline()` (notes, work, issues, inspections, Before/After photos on one time line, printable,
  Excel), *Record Finished Work* (a maintenance record that is already Done), work type on maintenance, reports *Area History* and *Maintenance & Work Done*.
- **Phase 2:** maintenance gets contractor, warranty, cost, related issue (closed together with the work); *Cancel* (status `Cancelled`, ranks below
  `Done` so done wins a concurrent cancel) instead of only delete; photos get `workId` ("belongs to this work") and the work details window shows them.
  **Cost is by permission** `maintenance.cost`: the server removes it from the state, the change log and the Excel export for people without it, and
  fills the old value back in when such a person saves a work (`STORE.maintenance_cost`), so saving can neither read, change nor erase it.
  Users with `users.manage` always get it (the right is newer than the stored permission lists of existing accounts).
- **Phase 3:** `repeatMonths` (completing repeating work plans the next one, `planNext`, `addMonths` keeps month ends), work due in a week or late is
  marked / counted at the bell and on the Maintenance page, `serial` on maintenance and `pieceHistory` (click a serial number; three repairs → replace).
- Tests: `T40_AreaLogAndWork` (two PCs, cost hiding, cancel vs done), browser `test_area_log_finished_work_and_repeats`.

**Second batch of 2.6.0 (owner's requests)**
- **Review fixes of the first batch** (independent review, all fixed): cost could be found digit by digit through the change-log *search* (now the search does not look inside
  maintenance changes for people without the right); *Record Finished Work* and *close the related issue* failed with "not allowed" for people who had only `maintenance.create` /
  `maintenance.complete` (history permission widened, issue controls shown only with `issues.followup`); completing work twice planned two "next" works (`maintDone` refuses work that
  is not open, the next work has the fixed id `nx<id>` so two PCs plan the same one); a cleared date gave `NaN-NaN-NaN`; scheduling rights could set a work to Done (now needs
  `maintenance.complete`); non-string ids gave error 500; cost must be a number from 0.
- **Strong data migration** (`server/upgrade.py`, see its text): `data/program.json`, verified snapshot in `data/upgrades/` before an update touches the files, old rows compared
  before / after (values of the old columns, no row lost, SQLite integrity), history (`journal.db`) append-only check, refusal to start with data of a newer program (message box
  on Windows + `logs/STARTUP_PROBLEM.txt`), migration registry `MIGRATIONS`, Settings → Data Safety with *Check my data now* (`/api/data-safety`), `Server(app=…)` in the tests to run
  a real previous release (`git archive`) on a data folder and then the current program: `T41_UpgradeKeepsData` (2.5.0 and 2.4.0) + `UpgradeGuardTest`.
- **Future Plans** (`plans` entity): *Schedule* opens the work dialog filled in and links the plan to the work; completing the work marks the plan done (done wins over dropped on two PCs).
- **Icon pack** (`js/icons.js`, generated by `tools/make_icons.py` from Lucide, ISC, `docs/ICONS_LICENSE.txt`): 124 icons in 7 groups, searchable picker in the item type window, old
  icon names keep working; `IconPackTest` checks that every icon the screens use exists.
- **From the sibling project Trip Orders** (studied in full; taken: the dependency-free Excel reader, import with review, search palette, attention list, design test idea):
  **Import from Excel** (`server/xlsx_read.py` + `server/excel_import.py`: header names found in any order, nothing existing is changed so a second import adds nothing, every problem a line,
  preview then one saved change after a backup), **Search everything** (Ctrl K, `js/palette.js`, `e.code` so any keyboard layout works), **Needs Attention** on the dashboard.
  Not taken (for later if wanted): phone app for inspections with camera and offline outbox (needs a cloud gateway), five colour themes and dark mode, Arabic / RTL, Word forms,
  guided tour and welcome slides.
- Tests: `T42_PlansAndImport`, `ExcelImportTest`, `test_plans_search_icons_import_and_data_safety`.
- **Field report: "the administrator made a user with user name and password, gave the person the setup, made changes – no data for the new user".** Investigated with real processes: a PC
  that JOINS shares everything both ways (accounts, data, changes, users made later, permission changes, works while the administrator PC is off) - nothing was broken there. The trap was the
  first screen and the texts: the first screen offered "This is the first (or only) PC" before "Join", the administrator's "Person added" text said the person "can log in on any PC in the
  network" and never said that a PC with its own copy must JOIN first, so the person made a separate empty system (which cannot join later: the PC is "already set up"). Fixed: join is the first
  choice and explains who it is for, "first PC" asks to make sure, the join screen checks the address while typing (`/api/join/probe`), the waiting screen shows errors and does not silently
  fall back, the administrator gets honest copyable instructions (every address, numbers first; browser = nothing to install; own PC = install + Join) and a hint on the Users page,
  and **Devices & Sync → Join the company system instead** (`/api/node/leave`: only on a lone administrator PC, backup first, data set aside in `copied-…` like a copied folder) rescues a PC that was
  set up alone. Tests: `T43_NewPcTrap`, `test_new_pc_screens_and_instructions`.
- **Independent review of the whole branch – found and fixed:** one far-away cell (`XFD1048576`) in an Excel file made the import loop run for hours (sheet size capped, only rows
  that hold cells are read); the technician who only completes work could not finish work scheduled from a plan (completing work may update its plan); a person who only plans could
  record work as already done (finished work needs `maintenance.complete`); the id of repeating work grew by 2 letters per generation and would pass the 120 limit after ~4.75 years
  (fixed-length `nx` + hash); failed starts could push the untouched snapshot out by pruning (pruning only after a good update, the oldest copy of the same update is reused and compared);
  a full disk or a locked `program.json` ended the start without a message (clear message / not fatal); Ctrl K opened behind a window; `nan`/`inf`/`1,000` in an Excel number; a plan whose
  work was cancelled could never be scheduled again; `program.json` now moves with copied data; the old start-up message is removed after a good start.

- **Appearance** (owner's request: more elegant fonts, font choice in settings, larger / smaller text): six variable fonts (Inter, Source Sans 3, IBM Plex Sans, DM Sans, Nunito Sans,
  Merriweather; SIL OFL, `fonts/`, `docs/FONTS_LICENSE.txt`, 290 KB, from the Fontsource packages) loaded by `css/fonts.css`; every text size in `styles.css` is `calc(Npx * var(--fs))` so one
  switch scales the text (not the layout); the font is `var(--font)` set by `html[data-font]`; `js/boot.js` applies the choice from `localStorage` before the page is drawn (no flash; inline scripts
  are blocked by the CSP); `appearanceCard()` in Settings and My Account, **Aa** button at the top; the program serves `/fonts/`. Tests: `AppearanceFilesTest` (no fixed px font size may
  come back), `test_font_and_text_size_choice`.

**More mistakes and lessons**
- A window holds records of the data it was opened on, so NOTHING may replace `DB` while a window is open except a failed save: the 10-second background refresh now loads "quietly"
  (`load(true)` does not replace the data when a window opened meanwhile), and the first-start save (`startEmpty`) finishes before the welcome window closes. A flaky browser test found it
  ("Someone else changed this" on a plain Add Person). Browser tests that start the program must wait for the welcome window to close (`#modal.open` detached), not for text that is already under it.
- A route added in the wrong block of `do_POST` (before the session is read) made `need()` refuse everybody: new authenticated routes go after `self.u` is known (the routes before it are the public ones).
- When a real user reports "it does not work", reproduce their steps with real programs first: the engine was right, the words on the screens were wrong.
- The static-file rules exist in two places (`STATIC_DIRS` and `serve_static`): a new folder such as `fonts/` must be added to both, and to `tools/make_assets.py` for the installed program.
- `repr()` of a Python list of tuples is not a JavaScript array: `('name', [...])` is a comma expression, the picker showed nothing. Generate JS with explicit brackets and open the window in a browser.
- A digest of rows must not depend on the row type: a connection with `sqlite3.Row` gave another `repr` than a plain one and the upgrade check refused a healthy history. Use `tuple(row)`.
- The first version of the history check compared bookkeeping columns (`status`, `note`, `via`) that legitimately move; compare only what never changes.

**Mistakes and lessons**
- `form.elements.item` is the collection's *method* (again!) – it broke the serial select of the new work windows until a screenshot run showed the
  select never appeared. Always run the new window in a browser, not only read the code.
- A new permission does not reach stored accounts: give it to administrators at run time (`_user`) and tell the administrator to tick it for others.
- Hiding a value only on screen is not hiding it: the state, the change log (before / after / changes) and the Excel export all carried the cost.
- Known and left: photos of a work cannot be uploaded while recording finished work itself (upload afterwards with *Add photo*);
  a piece's history is linked by serial text, so renaming a serial number breaks the link to older work.

## 2.5.0 – serial numbers, sample data fix, 12 bugs from a whole-program hunt (2026-09-29)

**Why:** the customer reported that *Delete Sample Data* disappears, "many bugs and problems", and asked to record the
serial number of every piece in a break area.

**What changed**
- **Delete Sample Data disappeared** (reproduced in the browser): the button looked for sample break areas by their
  *names* ("Break Area 03"). People start real use by renaming them, so the button vanished while the fake issues,
  photos, surveys and history stayed. Now sample records are recognised by their fixed short ids (`SAMPLE_REC`,
  `sampleLeft`): untouched sample areas are deleted completely, renamed ones are kept with their inventory and
  everything added by hand; only their sample records go. The button shows while any sample record is left.
- **Serial numbers**: new replicated entity `pieces` (one record per piece: item, serial, date, break area;
  `journal.SCHEMA` and `sync.SCHEMA_VERSION` 3 → 4). Update → *Added* asks the serial numbers (one per line, barcode
  scanners work; the quantity follows), *Removed / Transferred* ask which pieces go (required when fewer pieces would
  remain than serial numbers), *Replaced* changes old → new, *Delete Item* removes them. Area page list with
  Add/Edit (`serialModal`), search on Furniture & Equipment, column in the inventory report, sheet in the full export.
  Duplicates refused with where the number is; duplicates from two PCs at once are marked "twice". Server: serial
  required (≤ 80), permission `inventory.edit` (delete also `inventory.delete`), area scope as everywhere.
- **Bug hunt** (independent reviewer, browser-reproduced), all fixed:
  1. Save again after "changed by another user" said "saved" but saved nothing (the window kept the old records after
     the reload) → a window opened on older data is opened again on the new data with the typed values
     (`reopenFresh`, `OPENER`).
  2. Dashboard TV / water columns were 0 on a system started empty (item type ids `tv_screens`) → `mainItem`.
  3. A system started empty had no item types → the usual ones are added at the empty start.
  4. Editing an area after a location was renamed silently changed its location → the current value is always offered.
  5. A note on a closed issue changed its closed date.
  6. An area-limited user could delete item types used elsewhere → refused in the screen and on the server.
  7. "Add New Break Area" in the menu for area-limited users (refused only at the end) → hidden and blocked.
  8. Transparent PNG logos turned black (JPEG) → white background.
  9. Deleting the latest inspection kept its next inspection date.
  10. The first real photo never replaced the drawing of a new break area as main photo.
  11. Conflict messages showed ids (`Inventory "ba01:chairs"`) → names (`Inventory "Chairs" of Break Area 01`).
  12. Completing maintenance recorded the team as "Updated By" instead of the person.
  Also: backup restore refused for area-limited users; a transfer no longer changes the condition of the pieces
  already in the other area; the maintenance page no longer breaks on an old record without a date.
- Tests: `T39_SerialNumbers` (two PCs), browser tests `test_serial_numbers_and_renamed_sample_area`,
  `test_save_again_after_a_conflict`.

**Mistakes and lessons**
- Recognising demo data by a *name* people can change was the root of the "disappearing" button. Recognise it by an
  id nobody sees.
- Keeping a form open after a failed save (2.3, "nothing typed is lost") created a silent data-loss bug: the form
  kept references to records that the reload had replaced. Whenever data objects are replaced, anything holding
  them (open windows, closures) must be refreshed – test "fail, then retry" for every save path.
- `form.elements['item']` is a *method* of the elements collection, not the field named "item" – use
  `querySelector('[name=…]')`.
- `>>` to a new file name by mistake created a second stylesheet (`style.css` next to `styles.css`) – check the file
  name before appending.
- Known and left: the first save of a person with settings rights writes the default settings into the database
  (noise in the log only).

**Independent review of 2.5 – found and fixed**
- My own fix for "a note changes the closed date" broke closing: the status was set *before* comparing it, so closing
  an issue lost its closed date ("Closed This Month" stayed 0). Lesson: when a fix compares old and new, read the
  lines around it – the old value may already be overwritten.
- Sample records by id pattern alone matched real records of the very first program version (history `h121`, areas
  `ba23`, kept by the old-backup import) → a sample record now needs the id *and* the content of the sample data
  (`seedKeys` from `buildSeed`, which is always the same).
- "Save again" when the record was deleted meanwhile crashed silently → clear message; `OPENER` reset in `finally`.
- Smaller: a case-only correction of a serial number was not saved; "Removed" could get stuck when two PCs left more
  serial numbers than pieces; deleting an item type with left-over serial numbers needs `itemtypes.manage` there too;
  a hand-made request with a list value gave error 500; one date was not escaped; only a *Current* photo becomes
  the main photo; the conflict list names a serial number by its serial.
- Browser tests extended: closing an issue keeps its date, an old real record with a short id survives Delete Sample
  Data, a record deleted while its window is open.

## 2.4.0 – new PCs join by themselves, no "Add a PC" (2026-09-27)

**Why:** the HR team asked for two simple ways only: a **personal link** (nothing else needed) and **user name and
password** on a PC that has the program – without the code-and-approval screen of "Add a PC". Small trusted team,
needed quickly; the owner chose "every PC keeps its own full copy" (works while the administrator PC is off).

**What changed**
- "Add a PC" button, its code window and "PCs asking to join" are gone from the screens.
- A new PC: **Join an existing system** → it searches the network for the administrator PC (`/sync/hello` on every
  address of its networks, 64 at a time, 1.5 s each) and fills in the address, or the person types it (also the web
  address from Settings is accepted). The administrator PC adds it **at once** (`_open_join` → `decide`), no code,
  no approval; the new PC copies accounts and data and shows the login.
- The connection still pins the administrator PC's certificate from the first contact on.
- The code method stays in the code (tests, possible later use) but is not shown.
- Help page, guides, IDEAS.md updated. Test `T38_OpenJoin`; browser test joins with the address only.

**Automatic review (Codex) – fixed**
- If the answer to the join got lost, the new PC was already in the list and could never join (asking again was
  refused) → asking again with the same identity and keys returns the same approved request.
- A pasted web address with another web port than 8080 tried to join on the web port → a web address (`http://…`)
  always uses the sync port; a typed `host:port` is tried first, then the usual sync port.
  Test `T38_OpenJoin.test_join_answer_lost_then_asked_again`.

**Lessons**
- Every "do it once" network step needs a safe answer when it is asked again (the first answer can be lost).
- A security step the users do not want gets skipped anyway; offer a documented "easy mode" for small trusted teams
  and keep the safe mode in the code for later.

 – book of reusable ideas (2026-09-27)

- New file `IDEAS.md`: every idea and technology of this project in plain words (problem → idea → how → where →
  reuse), so the owner can reuse them in other projects. Kept up to date with every change (rule in `CLAUDE.md`).
- Why: the owner has about 100 repositories and wants one place per project with its best ideas (sync, sharing,
  security), later collected into one central file.

## 2.3.1 – fixes from the automatic review of 2.3.0 (2026-09-27)

The Codex review of pull request #7 arrived a moment after the merge; its findings were checked and fixed here.
- **PC list not the same on every PC** (convergence): since a backup administrator PC can also sign PC changes, the
  administrator PC and a backup PC could change the same PC (name, address, role) at the same time. The PC list
  applied changes in arrival order, so two PCs could end with different values. Now every field keeps the newest
  change by (clock, PC, number) – the same result on every PC in any order – and a removal stays final
  (`Journal._fold_roster`, column `nodes.vers`). Test `test_unit.Review231Test`.
- The second Codex review (on the fix) found two more: two PCs removing the same PC at the same time kept whichever
  removal arrived first (and `_consider` used it to refuse later changes) → the earliest removal names who and when,
  and *all* removals are remembered (`revoked_change` lists them; a change that had seen any of them is refused).
  And a 2.3.0 database had no field versions, so two PCs could swap values after the update → the PC list is folded
  again from the history once when the column is added (`Journal.rebuild_roster`).
- **Mapped network drives** (like `Z:`) passed the "no network folder" rule for the second backup folder; they are
  now recognised with Windows' drive type (`backup.network_folder`).
- **Known limit, documented, not changed**: a backup PC that is switched off does not know yet that its role was
  ended; administrator changes it makes before it hears about it are accepted everywhere (like decisions a deputy
  made before being told). Accepting them on some PCs and refusing them on others would break "same data
  everywhere". Stopping it completely needs a new administrator key (key rotation) – a possible later step.

**Lessons**
- When a second PC may sign a kind of change that only one PC signed before, every fold of that kind must become
  order-independent. Check each `_fold_*` for "last arrival wins" whenever a new author is added.
- Wait for the automatic reviews (Codex, Claude) to finish before merging, not only for the CI checks.
- A new "version" column for folded data is not enough: rows folded before it existed must be rebuilt from the
  history, or two PCs upgraded at different moments disagree. "Final" states (removal) also need an order-independent
  rule for *which* of several final changes is kept.

## 2.3.0 – Help page, delegation, safer first start and backups (2026-09-27)

**Why**: the owner uses the installed `BAMS.exe` and still saw "start.bat" in screens; asked for a user guide under
Settings, a way to give administrator rights to somebody while away, and a whole-program review for missing
essentials.

**What changed**
- **Help & User Guide** page (`js/help.js`, route `#/help`, left menu + Settings card): questions and answers per
  topic with search; administrator topics only for people who manage users. Every screen change must update its
  answer there.
- **Delegation**: a person gets administrator rights with the *Administrator* profile (user name and password), and a
  second PC can become a **backup administrator PC** (`Devices & Sync → Make backup admin`). It receives the
  administrator key over the pinned TLS sync connection (`/sync/authority`, only to a PC whose roster role is
  `backup`), can then sign people/permission changes, and deletes the key when the role ends (`Node.drop_backup_key`).
- **Save the administrator key** from the screen (`/api/devices/export-key`, on the administrator PC itself only,
  passphrase ≥ 12, same sealed format as `nodectl export-authority`), with a reminder card until done.
- **Second backup folder** from Settings (`/api/backups/folder`, administrators on the PC itself only, refused inside
  the data folder, tested by writing, stored in `config.json`, a backup is copied at once). Warning while backups
  are on one disk only.
- First start: the administrator chooses empty or sample data (no automatic sample data any more). *Delete Sample
  Data* only while sample data is there (`settings.sampleData` or sample ids/names); *Load Sample Data* only when
  there are no break areas.
- Installed-program texts: no start.bat / reset_admin.bat; "cannot reach the program" help; login shows the site
  name (no fixed SAMSUNG) and a hint for personal-link users; logout message for link users.
- A failed save keeps the dialog open (the text is not lost). Activity Log page needs one of the log permissions.
- Full Excel export: the *User Activity Log* sheet only for administrators; account/device/profile records never.
- Add Person is greyed out on PCs that cannot manage people; security log labels for the new events.
- Browser test updated (first-start choice, Help page), new `T36_BackupAdminPC`, `T37_AdminSafety`.

**Mistakes and lessons**
- The product review found the program still spoke about the portable version everywhere. Lesson: when the way of
  delivery changes, search **all** user-visible texts (`js/`, server messages, tools, guides) for the old way.
- Loading sample data by itself on the first start made it hard to tell real from sample data. Ask once instead.
- A top-level `const` in a new classic script shares one global scope with `app.js`: keep names specific
  (`helpBold`, `HELP_F`) to avoid a clash that stops the whole page.
- Links (`<a>`) with `data-act` are ignored by the click handler unless they have `data-href` – use buttons for
  in-page actions.
- The browser test assumed automatic sample data; every change of the first screens must update that test.

**Independent review of 2.3 – found and fixed (regression tests `T36.test_z_removed_while_off`, `T37`)**
- HIGH: a backup administrator PC removed while switched off kept the administrator key for ever – a removed PC
  never receives its own removal (every PC refuses it). Now it deletes the key when a PC answers "removed", and
  checks its role at every start.
- A backup PC could save (export) the administrator key and could remove the administrator PC → both refused (also
  in the tool), the buttons are hidden there.
- After a key import on a former backup PC the `backup` mark stayed, so another backup PC could end its role and
  delete the real key → the mark is cleared on import; the administrator PC can never get the backup role.
- PCs added on a backup PC named the backup PC as administrator PC → they get the real one.
- *Delete Sample Data* trusted a flag that could stay on after the sample areas were gone, and then deleted **all**
  break areas → it appears only while sample break areas exist and deletes only those (real ones are kept).
- Backup folder: network folders refused (backups contain the password hashes), links resolved (`realpath`),
  other folders from `config.json` kept, a damaged `config.json` gives a clear message.
- Two help answers named buttons that do not exist; a "Save it again" link did nothing (`<a data-act>`).

**Lessons**
- A revoked PC is cut off from exactly the message that tells it so: anything a PC must undo when removed has to
  be triggered by the refusal itself (and checked again at start), not by the roster change.
- "Delegated" copies of an authority must have fewer powers than the original (no export, cannot remove the
  original), otherwise ending the delegation means nothing.
- A delete-everything button must be tied to what it deletes (the sample records), never to a flag that can drift.

## 2.2.0 – permanent release on GitHub (2026-09-27)

- Every version that reaches `main` is now published once under **Releases** (`v<version>` with its
  `BAMS-Setup-<version>.exe`) by the build workflow – no tag is needed.
- Lesson: this Claude session may only push its own branch; pushing a tag was refused (HTTP 403). Releases are
  therefore made by GitHub Actions on `main`.

## 2.2.0 – Windows installer, protected program, sharing always on (2026-09-27)

**What changed**
- The program is delivered as **one installer, `BAMS-Setup-<version>.exe`**. The same file installs the program on a
  new PC and updates a PC that already has it. Only the program in `Program Files\BAMS` is replaced; the data
  stays in `%ProgramData%\BAMS` (config, data, backups) and is never removed, not even when the program is uninstalled.
- The program is **compiled** with Nuitka (Python → C → `BAMS.exe`) and the web pages are packed inside it
  (`tools/make_assets.py`). The installed PC has no readable source files that a person or an AI agent could
  change. `tools/build_windows.py` refuses to build if a `.py` file would be shipped.
- The installer stops the running program before an update, adds the Windows firewall rule (no Windows question),
  offers "start with Windows" (runs in the background with `--background`) and a desktop icon, and can bring
  the data of the old portable version (it renames the old `data` folder first, so the old copy can never run
  again with the same identity).
- Licence (`LICENSE.txt`) on the installer page; version, developer and copyright shown quietly on the login and
  account windows (`server/version.py`).
- GitHub workflow `.github/workflows/build.yml`: tests on every change, builds the installer on Windows, checks
  that the built `BAMS.exe` starts and serves its pages, publishes it for tags `v*`.
- **Sharing can no longer be switched off** (`sync_enabled` removed). The administrator PC warns once a day about
  a PC that has not shared its data for more than 3 days ("PC not sharing").

**Second whole-code review – found and fixed (with regression tests `T35_SecondReview`, `SecondReviewTest`)**
- CRITICAL (portable version only): `/css/../data/node/authority.key` served the administrator key and the databases
  without login, because static files were checked against the whole program folder. Now only `index.html` and
  files inside `css/`, `js/`, `lib/` with known extensions are served, and `..` is refused.
- New break areas got numbered ids (`ba23`): two PCs adding an area at the same time produced the same id and the two
  areas merged. Ids are now random.
- A save could fail *after* it was stored in the history (a small note file could not be written) → the user retried
  and the change was counted twice. The note file can no longer fail a save.
- Received changes that could not be applied at once (file locked by antivirus) waited until the next change or a
  restart – also account changes like a disabled user. Now retried every 10 seconds, accounts separately.
- An area-limited user could move a record *out of* another area (only the new area was checked). Both are checked.
- Conflict decisions (`resolve`) could be sent through a normal save by anybody. Only the administrator screen can.
- A silent connection to the sync port held up all other PCs (TLS handshake in the accept loop) → handshake per thread.
- Before login, requests up to 200 MB and unlimited failed logins (each one a slow password check and a log entry on
  every PC). Now 64 kB before login, and more than 10 failures per minute from one address are cut short.
- A bad file reference in a photo stopped photo copying on every PC → refused on save, skipped when copying.
- Two copies of the program on one PC (autostart + desktop icon) could both open the data → one lock per data folder;
  the maintenance tools also wait until the program is stopped.
- A PC whose clock had been far ahead kept writing future times after the clock was fixed → capped at start.
- A long form was lost when the automatic logout came while typing → the session stays alive while the person is active.
- Small: logo address escaped, log paging limits, half emojis in the activity log, recycle bin only for users with
  all break areas.

**Lessons**
- Review the portable and the installed layout separately: a check that is safe in one (pages inside the program)
  can be dangerous in the other (data next to the pages).
- Ids made by counting (`length + 1`) are never safe when several PCs work offline – always random ids.
- Anything a request can send (like `resolve`) is sent by somebody one day: internal options never come from the client.
- The automatic PR review found four more: the disk warning itself could fail a stored save (now best effort), a local
  Windows build left the packed pages next to the source (removed after building), a failed copy of the old data
  left half the data behind (removed, the old folder is restored), the silent-PC warning repeated after every
  restart (remembered in the journal).
- CI (GitHub) found two test problems the local machine hid: the upgrade tests need the full git history
  (`fetch-depth: 0`), and the attachment test depended on *when* a simulated network cut hit an already-open
  connection. Tests must create the situation they check directly (here: a half-downloaded file) instead of
  hoping for a timing. The test proxy now applies a cut limit to already-open connections too.
- A process killer that matches a command line (`pkill -f`, `ps | grep`) also matches the shell that runs it:
  stop test processes by process name or by PID.
- Inno Setup `[InstallDelete] {app}\*` looks harmless but wipes whatever folder the user picked: never delete by
  wildcard in the program folder; the folder page is disabled instead.
- Starting the program from the elevated installer would create data files owned by the administrator: start it
  with `runasoriginaluser`, and give `%ProgramData%\BAMS` `users-modify` rights.

---

## 2.1 – People with only a personal link, permission tick boxes, profiles (PR #3, #4 – 2026-09-27)

**What changed**
- Personal links: every person can get a fixed link `http://<PC>:8080/k/<token>` that logs them in under their own
  name on any PC. The token is an HMAC of the administrator key (only the administrator PC can make or show it),
  the PCs only store its SHA-256. Opening the link shows a small page that logs in with a same-origin POST
  (`js/quick.js`), so chat previews and virus scanners never log anybody in.
- **Add Person**: a name and a profile are enough; the link is the default way to log in (no user name or password).
- Permissions as tick boxes with *Select all* / *Clear all*; administrator rights in their own orange group that is
  never possible with a link. **Profiles** (ready-made and own), applied to everybody who has them on every PC.
- Plainer Settings, whole program checked to be English only.
- Data schema 3 (PCs with the old program hold the new changes until updated instead of dropping new fields).

**Mistakes found by the independent review and fixed**
- Switching a password person to "link" left the old password working → a random password is set.
- Choosing the "Administrator" profile for a link person gave every admin right except "manage people" →
  a link never carries *any* administrator right (checked for people, profiles and every request).
- A profile named "Manager" collided with the old role name → reserved.
- The link page switched the logged-in person without asking (login CSRF) → it asks when somebody else is logged in.
- `<meta name="referrer" content="no-referrer">` on the link page made browsers send `Origin: null`, which the
  anti-forgery check refused. Lesson: the referrer policy also changes the `Origin` header of form posts.

---

## 2.0 – Several PCs, offline-first (PR #2 – 2026-09-26)

**What changed**
- Every PC has the complete system and all data and keeps working alone. PCs exchange **signed, hash-chained
  changesets** (never database files) over TLS 1.3 with pinned certificates; version vectors, HLC clocks,
  deterministic fold (multi-value registers, inventory as +/− movements, durable deletes, conflict flags).
- Administrator authority: only the administrator PC can sign user, permission and device changes; a user can
  change their own password on any PC with a proof of the old password.
- Pairing with one code + 6-digit confirmation; revocation; tamper-evident history on every PC; attachments by
  SHA-256 with resumable transfers; compensating restore (history never rolled back); in-place upgrade with a
  verified pre-upgrade backup; clone detection; `nodectl.py` tools.
- Devices & Sync page, sync light (administrators only), conflict screen, monitoring with PC column.
- 32 scenario tests, randomized convergence tests, real multi-process tests, browser test.

**Mistakes and lessons**
- Dependencies of a new change must come from what was *folded*, not from what was *received*; otherwise a PC
  could claim knowledge it did not apply (critical review finding).
- An unexpected exception inside the fold stopped all later changes → deterministic errors are caught per
  operation, only environment errors (disk, memory) stop the fold.
- A batch delivered in reverse order was never accepted → receive loops until nothing more can be accepted.
- Upgrading doubled inventory quantities (counter + stored value) → the upgrade resets counters in the same
  transaction.
- Tests failed on Linux because a restarted server could not reuse its port (TIME_WAIT) →
  `allow_reuse_address` only outside Windows (on Windows it would hide a second running copy).
- Test passwords that contained the user name were refused by the password rules → use realistic test data.
- Editing server files while the test suite runs gives false failures (servers start with half-changed code).
- Users are not technical: the first screens were too detailed. Rule since then: one sentence, plain words,
  sync details only for administrators.

---

## 1.x – Shared SQLite server with logins (PR #1 – 2026-09-24/25)

- The browser-only app was turned into a local web server (Python standard library + SQLite) started with
  `start.bat`, with a portable Python in `runtime/python`.
- Users, passwords (PBKDF2), permissions per page and action, lockout, automatic logout, activity and security logs,
  backups every 6 hours and before risky actions, recycle bin, Excel export.
