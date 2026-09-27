# Development History and Lessons Learned

This file is the memory of the project. **Every change adds an entry here** (newest first): what changed, why, which
mistakes were made and what we learned. It is kept up to date together with the code (see `CLAUDE.md`).

Version numbers: `server/version.py`. Pull requests: github.com/coolman1984/Mr.Ayman-HR/pulls.

---

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
