# What is new

## 2.7.0

- **Use the office system** (field report: "Join" never connected in the office, only personal links worked). A new PC now offers
  **Use the office system (recommended)** first: it finds the administrator PC by itself (or you type its address, it is checked while you
  type), and from then on the program on that PC opens the administrator PC – the same way a personal link does. People log in there with their
  user name and password. The PC keeps no data of its own, shares nothing and needs no keys, so nothing can get out of step.
- If the administrator PC is off, the program says so in plain words, with **Try again** and a box for a new address.
- A PC that was set up alone by mistake: **Devices & Sync → Use the office system instead** (nothing is deleted, a backup is made first).
- The instructions shown after adding a person with a user name and password, the Help and the guides now describe this way.
- *Join an existing system (full copy)* is still there for PCs that must work while the administrator PC is off; it needs the sharing port 8443
  open in the network.
- Fixed: after switching a PC, a browser that still had a connection open to it kept showing the old setup page.
- 2.7 and 2.6 PCs work together (no change to the shared data).

## 2.6.0

- **Area Log** on every break area page: write notes (painting, renovation, repairs, visits…) and see everything that happened – notes, work,
  issues, inspections, Before / After photos – on one time line. Print it or save it as Excel. New reports: **Area History** and **Maintenance & Work Done**.
- **Record Finished Work**: write down work that is already done, with type, contractor, warranty and (by permission) cost. It can close the related issue.
- Maintenance has a **type of work**, a contractor, a related issue, and can **repeat** (the next one is planned when it is completed).
  Work due within a week or late is marked; the bell counts it.
- **Cancel** work instead of deleting it: it stays in the history.
- Photos can belong to a piece of work (before / after).
- **Costs** are only shown to people with the new permission *See and enter what maintenance work cost* (administrators always have it).
- Click a **serial number** to see everything that happened to that piece; three repairs suggest replacing it.
- **Future Plans** on every break area (target date, priority, status). *Schedule* turns a plan into planned work; when the work is completed the plan is done. Plans that are late show on the dashboard.
- **Updates never lose data**: before an update the program makes a verified copy of all data, checks after the update that every record is still there unchanged, refuses to start with data of a newer program, and shows it in **Settings → Data Safety** (with *Check my data now*).
- **Icon pack**: 124 professional icons in 7 groups for the item types, with a search box (old icons keep working).
- **Import from Excel** (Break Areas page): break areas, what is in them and serial numbers. You see what would be added first; nothing that exists is changed; a template can be downloaded.
- **Search everything** with Ctrl K (or the Search button): break areas, serial numbers, plans, issues, pages.
- **Needs Attention** on the dashboard: late work, urgent issues, plans past their date, warranties ending, pieces repaired 3 times, overdue inspections.
- **Appearance** (Settings, and *My Account* through the new **Aa** button at the top): choose one of six elegant fonts (Inter, Source Sans 3, IBM Plex Sans, DM Sans, Nunito Sans, Merriweather) or the standard look, and make the text smaller or larger (six sizes). Saved on the PC you use; works without internet.
- **A new person's PC shows no data?** (field report) The first screen of a new PC now puts **Join an existing system** first and says who it is for, asks before creating a separate "first PC",
  checks the administrator address while you type, tells you if it cannot reach the administrator PC, and a PC that was set up alone by mistake can move into the company system (**Devices & Sync →
  Join the company system instead**, nothing is deleted). After adding a person with a user name and password the administrator gets clear instructions (browser address or install + Join) to copy.
- All PCs must be updated to 2.6: changes made on a 2.6 PC wait on older PCs until they are updated too.

## 2.5.0

- **Serial numbers** for every piece: when you add items (Update → *Added*) type or scan their serial numbers, one per
  line. When you remove or transfer items you tick which pieces go. *Replaced* can change a serial number. The
  break area page lists them (*Serial numbers → Add / Edit*), *Furniture & Equipment* has a search box for them, and
  the inventory report shows them. The same serial number cannot be entered twice.
- **Delete Sample Data** no longer disappears when you renamed sample break areas: renamed ones are kept (with their
  inventory and everything you added) and only their sample photos, issues, surveys and history are removed.
- Fixed: pressing Save again after "someone else changed it" said "saved" but saved nothing. The window now opens
  again on the new data with what you typed.
- Fixed: the dashboard showed 0 TV screens and water dispensers on a system started empty; a system started empty
  now has the usual item types at once.
- Fixed: editing a break area after renaming a location changed its location; a note on a closed issue changed its
  closed date; deleting the last inspection kept the old next date; a transparent logo turned black; the first real
  photo did not replace the drawing of a new break area; completing maintenance recorded the team instead of you.
- Safer: a person limited to some break areas can no longer delete item types, restore a backup or see "Add New Break
  Area". Messages about changes made at the same time name the record ("Inventory Chairs of Break Area 01").
- All PCs must be updated to 2.5: changes made on a 2.5 PC wait on older PCs until they are updated too.

## 2.4.0

- Two simple ways to work: a **personal link** (open it, nothing else) or **user name and password** on a PC with the
  program installed.
- A new PC joins by itself: install the program, choose **Join an existing system** – it finds the administrator PC
  in the network. No code and no approval any more ("Add a PC" is gone).

## 2.3.1

- Several PCs: when the administrator PC and a backup administrator PC change the same PC at the same time, every
  PC now shows the same result.
- The second backup folder cannot be a mapped network drive (backups contain the passwords).

## 2.3.0

- **Help & User Guide** inside the program (left menu *Help*, and Settings → *Help & User Guide*): plain answers to
  the usual questions, grouped by topic, with a search box. Administrators also see how to add people (link or user
  name and password), give administrator rights, delete the sample data, backups and several PCs.
- **Deputy administrator and backup administrator PC**: give a trusted person administrator rights at any time and
  make a second PC a *backup administrator PC* (Devices & Sync). People can then be managed there too while the
  administrator PC is off. *End backup admin* takes it back.
- **Save the administrator key** from Devices & Sync (once, protected by a passphrase), for the day the
  administrator PC is lost.
- **Second backup folder** (Settings → Backups): every backup is also copied to a USB drive or another disk. The
  Backups card warns while the backups are only on one disk.
- First start: choose an empty system or sample data – sample data is never loaded by itself any more.
  *Delete Sample Data* appears only while sample data is there.
- No more "start.bat" texts in the installed program; clearer messages when the program cannot be reached.
- People with a personal link see how to log in again on the login screen.
- A failed save keeps the window open, so nothing typed is lost.
- The full Excel export contains the user activity log only for administrators.
- Add Person is greyed out on PCs where people cannot be managed (with the reason).

## 2.2.0

- The program now comes as one installer, **BAMS-Setup.exe**. The same file installs and updates. Your data is
  kept in a separate place and is never touched by an update.
- It starts with Windows in the background, so every PC always shares its changes. The desktop icon opens it.
- The administrator sees a warning when a PC has not shared its data for more than 3 days.
- Add Person: a name and a profile are enough; the person gets a personal link (no user name or password).
- Permissions as tick boxes with Select all / Clear all, and profiles (e.g. Visitor) that fill them in one click.
