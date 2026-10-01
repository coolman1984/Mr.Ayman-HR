# Break Area Management System

A local web app for the factory network, delivered as one installer **BAMS-Setup.exe** (install and update).
For developers it also runs portable with `start.bat` (a portable Python in `runtime/python`).

It works on **one PC** (every other PC opens it in the browser, as before) or on **several PCs at the same time**:
each PC has the complete system and all data, keeps working when the others are switched off, and exchanges
changes with them automatically and encrypted over the company network – see **GUIDE_Devices_Sync.md**.

## Install / update

1. Run **BAMS-Setup.exe** on the administrator PC (Next → Next → Finish). The same file updates an installed PC;
   the data is never touched.
2. The system opens in the browser. **Settings** shows the address for other PCs and phones, e.g.
   `http://192.168.1.10:8080/`. People with a personal link just open their link.
3. On other PCs: install it and choose **Use the office system** – the PC then opens the administrator PC like a
   personal link (people log in with user name and password, nothing is stored there). **Join an existing system
   (full copy)** is for PCs that should keep working when the administrator PC is off and needs the sharing port 8443
   open in the network (see GUIDE_Devices_Sync.md).

Program: `C:\Program Files\BAMS` (compiled). Data, settings and backups: `C:\ProgramData\BAMS`.
Developers: `docs/BUILD_AND_RELEASE.md`, rules in `CLAUDE.md`, history in `DEVELOPMENT_HISTORY.md`.

**Help inside the program:** the **Help** page (left menu, also Settings → *Help & User Guide*) answers the usual
questions of users and administrators in plain words, with a search box.

## Users, passwords and permissions

- **First start:** open the program on the administrator PC itself and create the administrator account (this is not
  possible from other PCs, so nobody else can claim it). Then choose an empty system or sample data to try it;
  sample data is removed in one step with **Settings → Delete Sample Data**.
- Everybody logs in with a personal user name and password. The administrator manages accounts in
  **Users & Permissions**: add, disable, delete, reset password, unlock, log out now.
- For each user the administrator ticks exactly what they may **see** (pages, survey results, logs) and **do**
  (add / edit / delete per area of the system, which reports, Excel export, print, backups, settings, users),
  and can limit the user to **selected break areas only**. Profiles (Full access, Administrator, Data Entry,
  Maintenance Team, Viewer, Visitor, and your own) fill the ticks in one click. A person can also log in with
  only a **personal link** (no user name or password). Changes apply immediately, even on PCs already logged in.
- Every permission is checked by the server for every request, not only hidden in the browser.
- Everything a user does is logged with their name and PC: data changes, clicks and pages, exports, and
  refused attempts. **Activity Log → Logins & Security** shows every login, wrong password, lockout, logout and
  every change to a user or their permissions.
- Security: passwords stored only as salted PBKDF2 hashes; 5 wrong passwords lock the account for 15 minutes;
  automatic logout after 30 minutes without activity (12 hours at most); new users must choose their own
  password at the first login. These values can be changed in `config.json`.
- **Administrator password lost?** On the administrator PC run `"C:\Program Files\BAMS\BAMS.exe" tool reset-admin`
  in a command window as administrator (program stopped; portable version: **reset_admin.bat**) – it prints a new
  temporary password. A deputy administrator can also reset it.
- **Deputy administrator / delegation:** give a trusted person the profile *Administrator* (user name and password) and,
  for times when the administrator PC is off, make a second PC a **backup administrator PC** (Devices & Sync).
- User accounts live in `data/auth.db`. Restoring a data backup never changes them (a copy is saved with every
  backup as `auth_<time>.db`).
- With several PCs, users and permissions are managed on the **administrator PC** (the PC where the first
  administrator was created); every PC can log everybody in, also while the administrator PC is off.
- The *User Activity* and *Logins & Security* logs are for administrators only (users who may manage users).

See **GUIDE_Users_Permissions.md** for step-by-step instructions.

## Sample data

On the very first start the administrator chooses an empty system or sample data (22 break areas, inventory, photos,
issues, transactions and 8 months of satisfaction surveys) to see every feature in action.
When you are ready for real use: **Settings → Delete Sample Data** (type DELETE to confirm). Sample break areas that
were renamed are kept with their inventory and everything added by hand; only their sample records are removed.
A backup is taken first and everything stays restorable from the Recycle Bin. The sample data is never
loaded again by itself.

## Area Log and maintenance

Every break area has an **Area Log**: notes (painting, renovation, repairs…) and a time line of all work, issues and inspections; work can be planned
(also repeating), recorded when already finished, cancelled, linked to an issue, a piece (serial number) and photos; costs are shown by permission only.
See **GUIDE_Area_Log.md**.

## Serial numbers

Every piece (TV screen, fridge, chair…) can carry its serial number: type or scan them when adding items
(*Update → Added*, one per line), tick which pieces go when removing or transferring, change one with *Replaced*.
The break area page lists them, **Furniture & Equipment** finds them, the inventory report and the full Excel export
show them. See **GUIDE_Serial_Numbers.md**.

## Where the data is

Installed program: the folders below are in `C:\ProgramData\BAMS`. Portable version: in the program folder.

| Folder | Content |
|---|---|
| `data/bams.db` | SQLite database with all records (rebuilt from the history if ever damaged) |
| `data/journal.db` | The permanent, signed history of every change on every PC, and the logs of all PCs (never restored backwards) |
| `data/node/` | This PC's identity and keys – never copy it to another PC |
| `data/auth.db` | User accounts, login sessions and the security log |
| `data/uploads/` | Photos (original quality) and documents (new files are named by their SHA-256 checksum) |
| `data/logs/` | `audit-YYYY-MM.jsonl` (every change), `security-YYYY-MM.jsonl` (logins, users), `sync-YYYY-MM.jsonl` (exchange with other PCs) – never overwritten – and `server.log` |
| `backups/` | Database backups (+ `auth_…` and `journal_…` copies) + a mirror of the uploads |

## How data is protected

- Every save is one transaction: it is stored completely or not at all.
- Nothing is erased. Deleted records are only marked and can be restored in **Settings → Recycle Bin**.
- If two people change the same record at the same time on the same PC, the second one is told to refresh instead of
  overwriting. Changes made at the same time on *different* PCs are merged by fixed rules and shown in
  **Devices & Sync → To decide** when a person should look at them.
- Every change is part of a chained, signed history that is copied to every PC: editing or deleting old entries is detected
  (**Devices & Sync → Check Records**).
- Backups: at every server start, every 6 hours when data changed, before any import or restore, and on demand
  (**Settings → Backup Now**). Each backup is checked for integrity. Restoring saves the current data first and is
  saved as a new change (history and logs are never rolled back; with several PCs all PCs follow).
- Keep a second copy on a USB drive or another disk: **Settings → Backups → Choose a second backup folder** (on the PC
  itself). It is stored as `extra_backup_dirs` in `config.json`.

## Settings (`config.json`)

`port`, `backup_interval_hours`, `keep_auto_backups` (only automatic backups are ever pruned), `max_upload_mb`,
`extra_backup_dirs`, `open_browser`, `session_idle_minutes`, `session_max_hours`, `max_failed_logins`,
`lockout_minutes`, `min_password_length`, and for several PCs `sync_port` (8443), `sync_interval_seconds`,
`device_name`, `peer_addresses`. The file is `C:\ProgramData\BAMS\config.json` (portable: in the program folder).
Restart the program after changing it.

## Upgrading from the single-server version

Run **BAMS-Setup.exe**; on its first install it offers to bring the data of the old portable folder (the one with
`start.bat`). Portable (developers): replace the program files and start `start.bat` as usual.
On the first start the existing data is backed up (`bams_…_pre-upgrade.db`), checked, and prepared for several PCs;
all records, users, logs, photos and backups are kept. The PC becomes the administrator PC.

## Tests (for developers)

`python -m unittest discover -s tests` – unit tests, randomized multi-PC convergence simulations and real multi-process
scenarios (see `TASKS.md`). The browser test needs Playwright and is skipped without it.
Design: `DISTRIBUTED_SYNC_ARCHITECTURE.md`.

## Moving data from the old browser-only version

Open the old `index.html` → Settings → **Download Backup (JSON)**, then in the new system use
**Import Old Version (JSON)** (dashboard or Settings).
