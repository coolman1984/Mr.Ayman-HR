# Guide: Several PCs – Devices & Sync

The system can run on **several PCs at the same time** (for example the administrator PC and 2–4 user PCs).
Every PC has the **complete system and all the data**. People work on their own PC, even when the other PCs
are switched off. As soon as the PCs can reach each other again, they exchange the changes automatically.
No files have to be copied by hand and no internet is needed.

A company with only one PC does not need any of this – everything works as before.

---

## 1. The idea in one minute

| | |
|---|---|
| **Every PC works on its own** | Saving never waits for another PC. If the network or another PC is down, your work is saved safely on your PC. |
| **Changes travel automatically** | Every few seconds each PC asks the others “what is new?” and sends what they are missing. Only new changes travel, never the whole database. |
| **Nothing is overwritten silently** | If two PCs change the same thing at the same time, the system decides the same way on every PC and shows it to the administrator in **Devices & Sync → Conflicts**. Quantities in the inventory are *added up* (+5 on one PC and −2 on another give +3). A deleted record never comes back by itself. |
| **One administrator PC** | Users, passwords and permissions are managed only on the administrator PC. Everybody can still log in on any PC while the administrator PC is switched off. |
| **Tamper-proof history** | Every change of every PC is recorded in a chained, signed history that is copied to all PCs. If somebody edits or deletes old entries, the check shows it. |

---

## 2. The sync light (top bar, every user)

| Light | Meaning | What to do |
|---|---|---|
| 🟢 **All PCs up to date** | Everything is shared. | Nothing. |
| 🟡 **Sharing changes…** | Your changes are saved here and are being copied to the other PCs. | Nothing – it turns green by itself. |
| ⚪ **Working on this PC** | The other PCs are switched off or out of reach. Your work is saved here and will be shared later. | Nothing. This is normal when other PCs are off. |
| 🔴 **Needs attention** | A real problem (wrong PC, damaged history, repeated errors). Your work on this PC is still saved. | Tell the administrator. |

With only one PC the light is not shown.

---

## 3. Installing a second PC

1. On the new PC copy the program folder **without** the `data` folder (and without `backups`).
   *Never copy the `data` folder to another PC – the system would detect it and ask what to do.*
2. Start **start.bat** on the new PC. Windows may ask to allow Python through the firewall: allow it on the
   **private / domain** network (the PCs talk to each other on port **8443**).
3. The browser opens. Choose **Join an existing system**.
4. On the **administrator PC** open **Devices & Sync → Add a PC**. It shows the administrator PC's address
   (e.g. `192.168.1.10:8443`) and a **pairing code**. The code works once and for 15 minutes.
5. On the new PC type the address, the pairing code and a name for the PC (e.g. “HR Office”), then
   **Send Join Request**. It shows a **6-digit confirmation number**.
6. On the administrator PC the request appears under **PCs asking to join** with a confirmation number.
   **Approve only if both numbers are the same.**
7. The new PC copies the user accounts and all the data (a few minutes the first time), then shows the login
   screen. Everybody logs in with their usual user name and password.

Nobody can join without a code *and* your approval. An unknown PC on the network cannot read or send data.

---

## 4. Devices & Sync (administrator only)

**PCs** – every PC with its address and status:

| Status | Meaning |
|---|---|
| Online – *Same data ✓* | Reachable, and the data was confirmed identical. |
| Online – *n changes to send / receive* | Busy sharing. |
| Switched off / not reachable – *last seen …* | Normal when the PC is off. It catches up when it comes back. |
| Problem | See the text and **Problems & Alerts**. |

Buttons: **Share Now** (contact all PCs immediately), **Check History** (recalculates the fingerprints of the whole
history), **Add a PC**, **Edit** (name, address after an IP change), **Remove** (a lost, replaced or retired PC:
it can no longer exchange data; everything it did before stays).

**Conflicts** – things two PCs did at the same time that a person should look at:

* *Changed on two PCs at the same time* – both values are shown with who, when and on which PC. The one marked
  “shown” is used everywhere. Click **Use this** on the correct value; all PCs follow.
* *Deleted while changed on another PC* – it stays deleted (nothing is lost). **Bring it back with the changes**
  or **Keep it deleted**.
* *Quantity below zero* – items were probably removed on two PCs. Count them and correct the inventory.
* *Entered twice* – e.g. the same satisfaction result on two PCs. Delete the extra entry.

**Problems & Alerts** – security and integrity messages (wrong certificate, refused changes, history check
problems, a removed PC trying to connect, clock of a PC far off, damaged file copies). **Seen** hides a message
until it happens again.

**Sync History** – when each PC exchanged how much. Full details are in `data/logs/sync-YYYY-MM.jsonl`.

---

## 5. Monitoring – who did what, on which PC

**Activity Log** now shows the entries of **all PCs** with a **PC** column and a PC filter:

* *Data Changes* – every added / changed / deleted record with old and new values.
* *User Activity & Errors* and *Logins & Security* – **administrators only** (checked by the server, not only
  hidden in the menu). Logins, failed logins, lockouts, user and permission changes, PCs added or removed,
  restores, history checks, refused changes.

Entries from before the upgrade are marked “before upgrade”.

---

## 6. Backups and restore with several PCs

* Every PC keeps its own backups as before (plus a copy of the history `journal_<time>.db`).
* **Restore** brings the data back to the backup **on all PCs**. It is saved as one new change: the history is
  never rolled back, user accounts are not touched, and a change another PC made meanwhile (that this PC had
  not received yet) is kept. A safety backup is taken first, so a restore can always be undone.
* Replication is **not** a backup: keep the automatic backups and the `extra_backup_dirs` copy.

---

## 7. Special situations

| Situation | What happens / what to do |
|---|---|
| Administrator PC switched off | Everybody works and shares data. Users, passwords and permissions can be changed again when it is back. |
| A user was disabled while a PC was off | That PC applies it as soon as it reconnects (the person is logged out there). |
| A PC gets a new IP address | Devices & Sync → Edit → Address. |
| A PC is broken / lost | Devices & Sync → **Remove**. Install a new PC and add it (section 3). |
| The data folder was copied to another PC | The system asks on that PC: *same computer* (continue) or *copy on a new PC* (the copied data is set aside, the PC joins as a new PC). |
| The administrator PC is lost for good | Only possible if the **administrator key** was exported (below): run `python server\nodectl.py import-authority <file>` on another PC. Without it user management cannot be changed any more (all other work continues). |
| Database file damaged | `python server\nodectl.py rebuild` re-creates it from the history (the damaged file is kept). |

**Export the administrator key once** (on the administrator PC, program stopped):
`runtime\python\python.exe server\nodectl.py export-authority E:\bams-admin-key.json` – choose a passphrase of at
least 12 characters. Keep the file and the passphrase in a safe place, separately.

---

## 8. Settings (`config.json`)

| Setting | Default | Meaning |
|---|---|---|
| `sync_port` | 8443 | Port the PCs use to talk to each other (encrypted). Allow it in the Windows firewall. |
| `sync_interval_seconds` | 5 | How often each PC asks the others for news (changes are also sent immediately after saving). |
| `sync_enabled` | true | `false` switches exchanging off on this PC. |
| `device_name` | computer name | Name of this PC shown to the administrator. |
| `peer_addresses` | `{}` | Optional fixed addresses `{"<PC id>": "192.168.1.20:8443"}` when the addresses in Devices & Sync are not usable. |

Restart start.bat after changing it.
