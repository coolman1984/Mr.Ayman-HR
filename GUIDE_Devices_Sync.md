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

## 2. The sync light (top bar, administrators only)

Normal users do not see anything about sharing – they just work. Only if there is a real problem they see
one short message: **“Please tell the administrator”**. The administrator sees this light:

| Light | Meaning | What to do |
|---|---|---|
| 🟢 **All PCs up to date** | Everything is shared. | Nothing. |
| 🟡 **Sharing changes…** | Your changes are saved here and are being copied to the other PCs. | Nothing – it turns green by itself. |
| ⚪ **Working on this PC** | The other PCs are switched off or out of reach. Your work is saved here and will be shared later. | Nothing. This is normal when other PCs are off. |
| 🔴 **Needs attention** | A real problem (wrong PC, damaged history, repeated errors). Your work on this PC is still saved. | Tell the administrator. |

With only one PC the light is not shown to anybody.

---

## 3. Installing a second PC

1. On the new PC run **BAMS-Setup.exe** (the same file as on the administrator PC). Keep "Start with Windows"
   ticked, so the PC always shares its changes.
2. The browser opens. Choose **Join an existing system**.
3. On the **administrator PC** open **Devices & Sync → Add a PC**. It shows one **code**
   (works once, for 15 minutes).
4. On the new PC type the code and a name for the PC (e.g. "HR Office"), then press **Join**.
   It shows a **6-digit number**. (Only if the new PC cannot find the administrator PC by itself it asks for its
   address, e.g. `192.168.1.10`.)
5. On the administrator PC the new PC appears under **PCs asking to join** with a number.
   **Approve only if both numbers are the same.**
6. The new PC copies the user accounts and all the data (a few minutes the first time), then shows the login
   screen. Everybody logs in with their usual user name and password, or their personal link.

Nobody can join without a code *and* your approval. An unknown PC on the network cannot read or send data.
*Never copy the data folder (`C:\ProgramData\BAMS`) to another PC – the system would detect it and ask what to do.*

People who only use a **personal link** need nothing installed – a browser in the same network is enough.

---

## 4. Devices & Sync (administrator only)

**PCs** – every PC with its address and status:

| Status | Meaning |
|---|---|
| Online – *Same data ✓* | Reachable, and the data was confirmed identical. |
| Online – *n changes to send / receive* | Busy sharing. |
| Switched off / not reachable – *last seen …* | Normal when the PC is off. It catches up when it comes back. |
| Problem | See the text and **Warnings**. |

Buttons: **Share Now** (contact all PCs immediately), **Check Records** (checks that no old record was changed or
deleted), **Add a PC**, **Edit** (name, address after an IP change), **Remove** (a lost, replaced or retired PC:
it can no longer exchange data; everything it did before stays).

**Backup administrator PC** (delegation – for when the administrator PC is off or you are away):

* Next to a trusted PC press **Make backup admin**. At its next contact it receives a copy of the administrator key
  over the encrypted connection (the key never travels in any other way). From then on people with administrator
  rights can add people, change permissions and links there too, also while the administrator PC is switched off.
* **End backup admin** takes it back: the PC deletes its copy of the key at its next contact.
* Give the rights to a person as well (a deputy): GUIDE_Users_Permissions.md, section 7.
* Every step is in the security log (*Backup administrator PC chosen*, *Administrator key sent to backup PC*, …).

**Save the administrator key (once)** – a card at the top of Devices & Sync on the administrator PC. Choose a
passphrase of at least 12 characters; a file `BAMS-administrator-key.json` is downloaded. Keep it on a USB stick in
a safe place and the passphrase somewhere else. Only with it can a new PC become the administrator PC if the old one
is lost for good. This works only on the administrator PC itself, never from another device.

**Personal links** – an extra, faster way to log in (optional):

* Every user can get **their own fixed link**. Opening it logs that person in straight away – no user name, no
  password – **under their own name and with their own permissions**. So the logs still show exactly who did
  what, and on which PC.
* People who only use a link need **nothing installed** – just a browser in the same network. They are added in
  **Users & Permissions → Add Person** (see GUIDE_Users_Permissions.md); their link is shown right away.
* **Create link** → the link and a QR code are shown. Send it to that person only, or open it once on their PC
  and save it as a bookmark / desktop shortcut. **Show link** shows the same link again at any time.
* The list shows for everybody whether they have a link and **when and on which PC it was last used**.
* A link is like a key: whoever has it works under that person's name. If it got into the wrong hands press
  **New link** (the old one stops working at once on every PC and whoever used it is logged out) or
  **Switch off**. The normal user name and password always keep working.
* Administrator accounts never get a link – they always log in with their password.
* Links are created and shown only on the administrator PC, but they work on **every** PC, also while the
  administrator PC is switched off. The link contains the address of the PC it opens; on a PC where the
  program runs, `http://localhost:<port>/k/…` with the same ending works too.

**To decide** – things two PCs did at the same time that a person should look at:

* *Changed on two PCs at the same time* – both values are shown with who, when and on which PC. The one marked
  “shown” is used everywhere. Click **Use this** on the correct value; all PCs follow.
* *Deleted while changed on another PC* – it stays deleted (nothing is lost). **Bring it back with the changes**
  or **Keep it deleted**.
* *Quantity below zero* – items were probably removed on two PCs. Count them and correct the inventory.
* *Entered twice* – e.g. the same satisfaction result on two PCs. Delete the extra entry.

**Warnings** – security and integrity messages (wrong certificate, refused changes, history check
problems, a removed PC trying to connect, clock of a PC far off, damaged file copies). **Seen** hides a message
until it happens again.

**Details** – when each PC exchanged how much. Full details are in `data/logs/sync-YYYY-MM.jsonl`.

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
* Replication is **not** a backup: keep the automatic backups and a **second backup folder** on a USB drive or
  another disk (Settings → Backups → *Choose a second backup folder*, on the PC itself). The Backups card warns while
  there is none, and shows when the last copy failed.

---

## 7. Special situations

| Situation | What happens / what to do |
|---|---|
| Administrator PC switched off | Everybody works and shares data. Users, passwords and permissions can be changed again when it is back – or at once on a **backup administrator PC** (section 4). |
| A user was disabled while a PC was off | That PC applies it as soon as it reconnects (the person is logged out there). |
| A PC gets a new IP address | Nothing – it tells the others by itself when it connects to them. If a PC is never reached, Devices & Sync → Edit → Address. |
| A user cannot change their password on their PC (message about the administrator PC) | Only for accounts from before the upgrade: log in once on the administrator PC (or change the password there). |
| A PC is broken / lost | Devices & Sync → **Remove**. Install a new PC and add it (section 3). |
| The data folder was copied to another PC | The system asks on that PC: *same computer* (continue) or *copy on a new PC* (the copied data is set aside, the PC joins as a new PC). |
| The administrator PC is lost for good | If there is a **backup administrator PC**, it already has the key: nothing is lost. Otherwise only possible if the **administrator key** was saved (below): run `BAMS.exe tool import-authority <file>` on another PC. Without it user management cannot be changed any more (all other work continues). |
| A new version of the program | Install it on **every PC that has the program** (devices that only use a link need nothing). Until a PC is updated it keeps working, but the changes of the updated PCs wait there (Warnings shows "uses a newer version") – nothing is lost. |
| Database file damaged | `BAMS.exe tool rebuild` re-creates it from the history (the damaged file is kept). |

**Save the administrator key once**: Devices & Sync → *Save the administrator key* (section 4). The same with a
command window (program stopped, as administrator):
`"C:\Program Files\BAMS\BAMS.exe" tool export-authority E:\bams-admin-key.json` (portable version:
`runtime\python\python.exe server\nodectl.py export-authority E:\bams-admin-key.json`) – choose a passphrase of at
least 12 characters. Keep the file and the passphrase in a safe place, separately.

---

## 8. Settings (`config.json`)

| Setting | Default | Meaning |
|---|---|---|
| `sync_port` | 8443 | Port the PCs use to talk to each other (encrypted). Allow it in the Windows firewall. |
| `sync_interval_seconds` | 5 | How often each PC asks the others for news (changes are also sent immediately after saving). |
| `device_name` | computer name | Name of this PC shown to the administrator. |
| `peer_addresses` | `{}` | Optional fixed addresses `{"<PC id>": "192.168.1.20:8443"}` when the addresses in Devices & Sync are not usable. |

The file is `C:\\ProgramData\\BAMS\\config.json`. Restart the program after changing it.
