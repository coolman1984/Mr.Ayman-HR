# Ideas Book – reusable ideas from this project

Owner: Mohamed Fawzy. This file keeps the **ideas, tricks and technologies** of this project in plain words, so they
can be reused in any other project. It is not a manual of this program (see `README.md`) and not its history (see
`DEVELOPMENT_HISTORY.md`).

Every idea follows the same shape:
**Problem** (what hurt) → **Idea** (one sentence) → **How** (simple steps) → **Where** (files here) → **Reuse when / watch out**.

Kept up to date with every change (rule in `CLAUDE.md`). New idea → new card in the right chapter.

---

## Chapter 1 – Several PCs that work alone and share (offline-first)

### 1.1 Every PC has everything, PCs share *changes*, never database files
- **Problem:** one server PC = when it is off, nobody works. Sharing one database file over the network breaks it.
- **Idea:** every PC keeps the complete data and works alone; PCs send each other small "change packets".
- **How:** each save becomes one *changeset* (who, when, what changed). PCs ask each other "what do you have that I
  don't?" and exchange only the missing changesets. Each PC applies them to its own database.
- **Where:** `server/journal.py` (changesets), `server/sync.py` (exchange), `server/replica.py` (apply).
- **Reuse when:** shops, branches, field teams, factories with weak network. **Watch out:** never copy or share the
  database file itself (SQLite over a network drive corrupts).

### 1.2 Same result on every PC, whatever the order (deterministic merge)
- **Problem:** PC A and PC B change things at the same time without seeing each other. Who wins?
- **Idea:** fixed rules that give the same answer on every PC, no matter which change arrives first.
- **How (the rules):**
  - A text field: the newest change wins, "newest" = (clock, PC id, number) – a tie is impossible.
  - A quantity (stock): store **movements** (+5, −2), not the final number → both changes count (+3).
  - A delete stays a delete; the record is kept hidden, never erased.
  - When a person should decide (two different values, delete vs. edit) → show both in a "To decide" list.
- **Where:** `server/replica.py`, `Journal._fold_roster` (PC list), conflict screen in `js/devices.js`.
- **Watch out:** when a *second* author can write something that had only one author before, check that its merge
  still does not depend on arrival order (lesson of version 2.3.1). When you add a "version" column later, rebuild
  the old rows from the history.

### 1.3 A clock that never goes backwards (hybrid logical clock) + "what I have" lists
- **Problem:** PC clocks are wrong or change; "newest" by wall time is unreliable.
- **Idea:** a clock that is the wall time, but always a bit bigger than anything already seen.
- **How:** every change carries this clock. Each PC also keeps a short list "from PC X I have changes up to number N"
  (version vector) → the exchange asks only for what is missing.
- **Where:** `HLC` in `server/journal.py`.

### 1.4 Tamper-evident history (hash chain + signatures)
- **Problem:** somebody edits or deletes old records directly in the database.
- **Idea:** chain the changes like a blockchain-lite and sign them.
- **How:** each change contains the fingerprint (hash) of the previous change of the same PC and is signed with that
  PC's key (Ed25519). Changing an old one breaks the chain → detected. Every PC keeps a copy of all chains.
- **Where:** `server/journal.py`, `server/ed25519.py`; "Check Records" button.

### 1.5 Wait for a newer program instead of losing data
- **Problem:** an updated PC sends new fields that an old PC does not know; the old PC would drop them.
- **Idea:** a data "schema number" in every change; an old PC keeps such changes aside until it is updated.
- **Where:** `journal.SCHEMA`, `sync.SCHEMA_VERSION`. **Watch out:** raise it with every new field.

---

## Chapter 2 – Trust and security between PCs

### 2.1 One "authority key" for the dangerous changes
- **Problem:** any PC could pretend to give itself administrator rights.
- **Idea:** user, permission and PC changes must be signed with a special key that only the administrator PC has.
- **How:** every PC knows the public half; it refuses such changes without a valid signature.
- **Where:** `server/node.py`, `Journal._check`.

### 2.2 Delegation: a backup administrator PC
- **Problem:** the administrator is on holiday or their PC is off → nobody can add people.
- **Idea:** give a copy of the authority key to one trusted PC, and take it back later.
- **How:** the administrator marks a PC "backup"; that PC fetches the key over the encrypted, pinned connection.
  When the role ends – or the PC is removed, even while it was off – it deletes the key. A backup PC may not export
  the key and may not remove the main administrator PC.
- **Where:** `set_backup`, `/sync/authority`, `Node.drop_backup_key`, `check_backup_role` in `server/sync.py`.
- **Watch out:** a removed PC never receives the message "you are removed" (everyone refuses it) → react to the
  refusal itself and check again at every start. Full revocation needs a new key (key rotation).

### 2.3 Pairing a new PC like Bluetooth
- **Problem:** how does a new PC join safely without IT knowledge?
- **Idea:** a one-time code (15 minutes) + the same 6-digit number shown on both screens.
- **How:** admin clicks "Add a PC" → code; new PC types it → both show a number; admin approves only if equal.
- **Where:** `create_invite`, join flow in `server/sync.py`, screens in `js/devices.js`.

### 2.4 Encrypted connections with "pinned" certificates
- **Idea:** each PC makes its own certificate; the others remember its fingerprint at pairing and accept only that one
  (no certificate authority needed, a fake PC in the middle is refused).
- **Where:** `server/tlscert.py`, `server/sync.py`.

### 2.5 Clone detection
- **Problem:** someone copies the data folder to a second PC → two PCs with the same identity.
- **Idea:** remember a machine fingerprint; if it changed, ask "same computer or a copy?".
- **Where:** `machine_fingerprint` in `server/node.py`.

---

## Chapter 3 – People, logins and permissions

### 3.1 Personal link instead of user name and password
- **Problem:** factory staff forget passwords; installing software for everyone is heavy.
- **Idea:** every person gets a fixed secret link that logs them in under their own name.
- **How:** token = HMAC(secret key, person + random number); the PCs store only a hash of it. Opening the link shows a
  small page that logs in by itself from inside the page (a POST), so chat previews and virus scanners that only
  *read* the link never log anybody in.
  "New link" kills the old one everywhere at once.
- **Where:** `server/auth.py` (links), `js/quick.js`.
- **Watch out:** a link never carries administrator rights (checked on every request, not only in the screen).

### 3.2 Tick boxes + profiles
- **Idea:** one tick per page and per action, grouped; ready-made profiles (Viewer, Data Entry…) tick them for you;
  dangerous rights in their own orange group that "Select all" never ticks.
- **Where:** `PERMISSIONS`, `ADMIN_PERMS` in `server/auth.py`; `permPicker` in `js/app.js`.
- **Watch out:** the server checks every request; hiding a button is only comfort.

### 3.3 Password and login safety kit
- Passwords stored only as salted PBKDF2 hashes; rules: length, letters + number, not the name.
- 5 wrong passwords → locked 15 minutes; max 10 failures per minute per address.
- Before login only small requests (64 kB) are read.
- Automatic logout after 30 minutes idle – but **not while the person is typing** (a long form is never lost).
- Tokens, passwords and keys never written into logs.
- **Where:** `server/auth.py`, `too_many_failures` in `server/app.py`.

### 3.4 Actions that only work on the PC itself
- **Idea:** first administrator, saving the key, choosing the backup folder: accepted only from `127.0.0.1`.
  Nobody on the network can do them, even with a stolen password.

---

## Chapter 4 – Data safety

### 4.1 Never erase, never roll back
- **Idea:** deletes only hide (Recycle Bin); "restore a backup" is saved as a **new** change that puts old values
  back – history and logs are never rolled back, and other PCs follow.
- **Where:** `Backups.restore` in `server/backup.py`, `Store.restore_from` / `Store.restore_txn` in `server/store.py`.

### 4.2 Backups done right
- Automatic at start, every 6 hours when something changed, and before every risky action.
- Every backup is checked (`PRAGMA integrity_check`) before it counts.
- A second copy on another disk or USB drive (not a network folder: it contains password hashes).
- A warning card while backups exist on one disk only.

### 4.3 Random ids, never "count + 1"
- **Problem:** two PCs offline both create "area 23" → they merge into one.
- **Idea:** random ids for everything created.

### 4.4 One program per data folder
- **Idea:** a lock file; a second copy (autostart + double click) refuses to start instead of damaging data.
- **Where:** `lock_data` in `server/system.py`.

### 4.5 Upgrade in place
- **Idea:** on the first start of a new version: backup, check, convert, continue – the user sees nothing.

### 4.6 Files by fingerprint
- **Idea:** photos and documents are named by their SHA-256; copying between PCs is resumable and a damaged copy is
  detected.

---

## Chapter 5 – Delivery: installer, protection, releases

### 5.1 One installer that installs *and* updates
- **Idea:** program in `C:\Program Files\BAMS`, data in `C:\ProgramData\BAMS`; the same `Setup.exe` replaces only
  the program, the data is never touched (not even by uninstall).
- **Tools:** Inno Setup (`installer/bams.iss`): stops the program, firewall rule, start with Windows.

### 5.2 No readable source code on the customer PC
- **Idea:** compile Python to machine code (Nuitka) and pack the web pages *inside* the `.exe`.
- **Where:** `tools/make_assets.py`, `tools/build_windows.py` (refuses to ship a `.py` file).

### 5.3 Releases without any tools on your own PC
- **Idea:** GitHub Actions tests, builds the Windows installer and publishes it under Releases for every new
  version merged into `main` – nothing to install on your PC.
- **Where:** `.github/workflows/build.yml`, `docs/BUILD_AND_RELEASE.md`.

### 5.4 Standard library only
- **Idea:** Python standard library + SQLite + plain JavaScript: nothing to install, nothing that breaks with updates.

---

## Chapter 6 – Simple screens for non-technical people

- One sentence per message, plain English, one clear action per screen.
- Technical details (sync light, warnings) only for administrators; others see "Please tell the administrator".
- First start asks: "empty system" or "try with sample data"; sample data is deleted in one step and only the
  sample records are deleted.
- A failed save keeps the form open with the text.
- A **Help page** of questions and answers with a search box, with extra topics for administrators.
- Buttons that cannot work on this PC are greyed out with the reason.

---

## Chapter 7 – How we work (the method)

- **Project memory in the repo:** `CLAUDE.md` (rules), a project skill (`.claude/skills/…/SKILL.md`: how the program
  works, pitfalls), `DEVELOPMENT_HISTORY.md` (what, why, mistakes, lessons), this `IDEAS.md`.
- **Tests on three levels:** fast unit tests; real multi-PC tests (several programs, a network cable that can be
  "unplugged" by a proxy); a real browser test (Playwright). A regression test for every bug.
- **Review loop:** independent reviewer + automatic PR reviews (Codex/Claude) → verify each finding → fix → test →
  write the lesson. Wait for the automatic reviews before merging, not only for green checks.
- **Branch → pull request → merge only when the owner says so.** Never force-push, never rewrite history.

---

## Technologies used (quick list)

| Technology | Used for |
|---|---|
| Python 3 (standard library only) | server, sync, security |
| SQLite | data, history (journal), accounts |
| Plain JavaScript + HTML + CSS | all screens (no framework) |
| Ed25519 signatures, SHA-256, HMAC, PBKDF2 | signing changes, file fingerprints, links, passwords |
| TLS 1.3 with pinned certificates | PC-to-PC connections |
| Hybrid logical clock, version vectors | ordering and exchanging changes |
| Nuitka | compiling Python to a protected `.exe` |
| Inno Setup | Windows installer |
| GitHub Actions | tests, Windows build, automatic releases |
| Playwright + Chromium | browser tests |
