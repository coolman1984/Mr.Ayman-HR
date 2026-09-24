# Break Area Management System

A local web app for the factory network. One PC runs the server; every other PC opens it in the browser.
No installation is needed: a portable Python is included in `runtime/python`.

## Start

1. On the server PC, double-click **start.bat**.
2. The browser opens automatically. The console window shows the address for the other PCs,
   e.g. `http://106.139.71.238:8080/`. Keep that window open (closing it stops the system).
3. The first time Windows may ask to allow Python through the firewall – allow it on the
   *private/domain* network, otherwise the other PCs cannot connect.

## Sample data

On the very first start the database is filled with sample data (22 break areas, inventory, photos, issues,
transactions and 8 months of satisfaction surveys) so users can see every feature in action.
When you are ready for real use: **Settings → Delete All Sample Data** (type DELETE to confirm).
A backup is taken first and everything stays restorable from the Recycle Bin. The sample data is never
loaded again by itself.

## Where the data is

| Folder | Content |
|---|---|
| `data/bams.db` | SQLite database (all records, audit log, activity log) |
| `data/uploads/` | Photos (original quality) and documents |
| `data/logs/` | `audit-YYYY-MM.jsonl` (every change, never overwritten) and `server.log` |
| `backups/` | Database backups + a mirror of the uploads |

## How data is protected

- Every save is one transaction: it is stored completely or not at all.
- Nothing is erased. Deleted records are only marked and can be restored in **Settings → Recycle Bin**.
- If two PCs change the same record at the same time, the second one is told to refresh instead of overwriting.
- Backups: at every server start, every 6 hours when data changed, before any import or restore, and on demand
  (**Settings → Backup Now**). Each backup is checked for integrity. Restoring saves the current data first.
- Put a network drive in `extra_backup_dirs` in `config.json` to keep a second copy on another machine, e.g.
  `"extra_backup_dirs": ["\\\\fileserver\\share\\BAMS-Backups"]`.

## Settings (`config.json`)

`port`, `backup_interval_hours`, `keep_auto_backups` (only automatic backups are ever pruned), `max_upload_mb`,
`extra_backup_dirs`, `open_browser`. Restart start.bat after changing it.

## Moving data from the old browser-only version

Open the old `index.html` → Settings → **Download Backup (JSON)**, then in the new system use
**Import Old Version (JSON)** (dashboard or Settings).
