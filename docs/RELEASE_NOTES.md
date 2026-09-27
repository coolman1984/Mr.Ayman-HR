# What is new

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
