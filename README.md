# Break Area Management System

A local web app for the factory network. No installation is needed: a portable Python is included in `runtime/python`.

It works on **one PC** (every other PC opens it in the browser, as before) or on **several PCs at the same time**:
each PC has the complete system and all data, keeps working when the others are switched off, and exchanges
changes with them automatically and encrypted over the company network – see **GUIDE_Devices_Sync.md**.

## Start

1. On the server PC, double-click **start.bat**.
2. The browser opens automatically. The console window shows the address for the other PCs,
   e.g. `http://106.139.71.238:8080/`. Keep that window open (closing it stops the system).
3. The first time Windows may ask to allow Python through the firewall – allow it on the
   *private/domain* network, otherwise the other PCs cannot connect.

## Users, passwords and permissions

- **First start:** open `http://localhost:8080/` **on the server PC itself** and create the administrator account
  (this is not possible from other PCs, so nobody else can claim it).
- Everybody logs in with a personal user name and password. The administrator manages accounts in
  **Users & Permissions**: add, disable, delete, reset password, unlock, log out now.
- For each user the administrator ticks exactly what they may **see** (pages, survey results, logs) and **do**
  (add / edit / delete per area of the system, which reports, Excel export, print, backups, settings, users),
  and can limit the user to **selected break areas only**. Quick roles (Administrator, Manager, Data Entry,
  Maintenance Team, Viewer) fill the ticks in one click. Changes apply immediately, even on PCs already logged in.
- Every permission is checked by the server for every request, not only hidden in the browser.
- Everything a user does is logged with their name and PC: data changes, clicks and pages, exports, and
  refused attempts. **Activity Log → Logins & Security** shows every login, wrong password, lockout, logout and
  every change to a user or their permissions.
- Security: passwords stored only as salted PBKDF2 hashes; 5 wrong passwords lock the account for 15 minutes;
  automatic logout after 30 minutes without activity (12 hours at most); new users must choose their own
  password at the first login. These values can be changed in `config.json`.
- **Administrator password lost?** On the server PC run **reset_admin.bat** – it prints a new temporary password.
- User accounts live in `data/auth.db`. Restoring a data backup never changes them (a copy is saved with every
  backup as `auth_<time>.db`).
- With several PCs, users and permissions are managed on the **administrator PC** (the PC where the first
  administrator was created); every PC can log everybody in, also while the administrator PC is off.
- The *User Activity* and *Logins & Security* logs are for administrators only (users who may manage users).

See **GUIDE_Users_Permissions.md** for step-by-step instructions.

## Sample data

On the very first start the database is filled with sample data (22 break areas, inventory, photos, issues,
transactions and 8 months of satisfaction surveys) so users can see every feature in action.
When you are ready for real use: **Settings → Delete All Sample Data** (type DELETE to confirm).
A backup is taken first and everything stays restorable from the Recycle Bin. The sample data is never
loaded again by itself.

## Where the data is

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
  **Devices & Sync → Conflicts** when a person should look at them.
- Every change is part of a chained, signed history that is copied to every PC: editing or deleting old entries is detected
  (**Devices & Sync → Check History**).
- Backups: at every server start, every 6 hours when data changed, before any import or restore, and on demand
  (**Settings → Backup Now**). Each backup is checked for integrity. Restoring saves the current data first and is
  saved as a new change (history and logs are never rolled back; with several PCs all PCs follow).
- Put a network drive in `extra_backup_dirs` in `config.json` to keep a second copy on another machine, e.g.
  `"extra_backup_dirs": ["\\\\fileserver\\share\\BAMS-Backups"]`.

## Settings (`config.json`)

`port`, `backup_interval_hours`, `keep_auto_backups` (only automatic backups are ever pruned), `max_upload_mb`,
`extra_backup_dirs`, `open_browser`, `session_idle_minutes`, `session_max_hours`, `max_failed_logins`,
`lockout_minutes`, `min_password_length`, and for several PCs `sync_port` (8443), `sync_interval_seconds`, `sync_enabled`,
`device_name`, `peer_addresses`. Restart start.bat after changing it.

## Upgrading from the single-server version

Replace the program files (`server`, `js`, `css`, `index.html`, `lib`, `*.bat`) and start **start.bat** as usual.
On the first start the existing data is backed up (`bams_…_pre-upgrade.db`), checked, and prepared for several PCs;
all records, users, logs, photos and backups are kept. The PC becomes the administrator PC.

## Tests (for developers)

`python -m unittest discover -s tests` – unit tests, randomized multi-PC convergence simulations and real multi-process
scenarios (see `TASKS.md`). The browser test needs Playwright and is skipped without it.
Design: `DISTRIBUTED_SYNC_ARCHITECTURE.md`.

## Moving data from the old browser-only version

Open the old `index.html` → Settings → **Download Backup (JSON)**, then in the new system use
**Import Old Version (JSON)** (dashboard or Settings).
