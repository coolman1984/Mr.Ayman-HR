# Guide: People, Links and Permissions

Every person has their **own** account, so everything they do is recorded with their name. A person logs in in one
of two ways:

* **Personal link** (easiest, the default) – the administrator gives the person a link. Opening it logs them in
  straight away. No user name, no password, nothing to install: any browser in the same network is enough.
* **User name and password** – needed for administrators.

The administrator decides with simple tick boxes what each person may open and do.

---

## 1. First start – create the administrator

1. Install **BAMS-Setup.exe** on the **administrator PC** and open the program (desktop icon). Choose
   **This is the first (or only) PC**.
2. Enter your full name, a user name (e.g. `ayman`) and a password, then click **Create Administrator**.
3. Choose **Start with my real data** (empty) or **Try it with sample data first**. Sample data is deleted later in
   one step: **Settings → Delete Sample Data**.

> This screen only works on the PC itself. On other PCs install the program and choose **Join an existing system** –
> they join by themselves (see GUIDE_Devices_Sync.md). People who only use a link do **not** need the program on their
> device.

**Two ways to log in**
* **Personal link** – open the link in any browser. Nothing to install, no user name, no password.
* **User name and password** – on a PC with the program (`BAMS-Setup.exe`) installed. Nothing else is needed.

---

## 2. Add a person (about 10 seconds)

1. **Users & Permissions** (left menu) → **Add Person**.
2. Type the **name**.
3. Choose a **profile** (e.g. *Visitor*). The right boxes are ticked for you. Change single ticks if you like.
4. **Create** → the person's **link** and a QR code appear. **Copy link** and send it to that person only, or open it
   once on their PC / phone and save it as a bookmark.

That is all. The person opens the link and works under their own name, with the permissions you ticked.

**Permissions**

* One tick box per page and per action. Ticking a group title ticks the whole group.
* **Select all** ticks everything except the orange group **Administrator rights**.
* **Clear all** removes every tick.
* The orange **Administrator rights** (manage people, see who clicked what, logins log, restore backups, import) are
  never given by accident and are **not possible with a personal link** – administrators use a password.

**Profiles** (button **Profiles** on the same page)

A profile is a named set of ticks, e.g. *Visitor*. Ready-made profiles:

| Profile | Typical person |
|---|---|
| Full access | Everything except the administrator rights (the default for a new person) |
| Administrator | Everything – always, cannot be changed |
| Data Entry | Sees the pages, records inventory, issues, inspections, maintenance, surveys, uploads photos |
| Maintenance Team | Sees break areas and maintenance, follows up issues, completes maintenance |
| Viewer | Sees everything and runs the reports, changes nothing |
| Visitor | Only the dashboard and the break areas list |

**New Profile** – give it a name and tick the boxes. **Edit** – change the ticks; *Also update the people who have
this profile* changes everybody with it at once, on every PC. **Delete** – the people who had it keep their ticks
(their profile shows as *Custom*).

**More options** (at the bottom of the person's window): limit the person to some break areas only, and notes.

Changes apply **immediately**, even if the person is logged in right now – on other PCs as soon as they receive the
change.

> **Several PCs:** people, links, profiles and permissions are changed only on the **administrator PC**. The links work
> on every PC. People with a password change their *own* password on any PC.

---

## 2a. Personal links – good to know

* The link opens the system on the PC whose address it contains (normally the administrator PC). That PC must be
  switched on and in the same network. Windows must allow the program on the **private network** (the question
  Windows asks the first time).
* If that PC gets a new network address, open the person and click **Show Link** – it shows the link with the new
  address. Ask IT for a fixed address for the administrator PC to avoid this.
* A link is like a key: whoever has it works under that person's name. If it gets into the wrong hands, open the person
  → **Show Link** → **New link**. The old link stops working at once, on every PC.
* After 30 minutes without activity the person is logged out – opening the link again logs them back in.
* To stop a person: **Account → Disabled**, or **Delete**.
* To switch a person from link to password: choose *User name and password* and give a temporary password (the link
  stops). And back: choose *Personal link*.
* **Devices & Sync → Personal links** lists everybody's link with **when and on which PC it was last used**.

---

## 3. Everyday administration

Open the user (**Users & Permissions** → **Edit**):

| Need | Button / field |
|---|---|
| Person forgot the password | **Reset Password** (new temporary password, logged out everywhere) – or give them a personal link |
| Account locked after 5 wrong passwords | **Unlock** (or wait 15 minutes; lockouts count per PC) |
| Throw someone out now | **Log Out Now** |
| Block for a while (vacation, suspension) | **Account → Disabled** |
| Person left the company | **Delete** (history stays in the logs, user name stays reserved) |
| See what the person did | **Activity** |

The list shows who is **online now**, the last login and badges such as *Locked* or *New password*.

---

## 4. Monitoring – who did what

**Activity Log** (left menu) has three tabs, with the entries of **all PCs** and a **PC** column:

- **Data Changes** – every added, changed or deleted record with the old and new values.
- **User Activity & Errors** – pages opened, clicks, exports, saves, refused attempts ("denied").
- **Logins & Security** – logins, logouts, wrong passwords, lockouts, automatic logouts, password
  changes and every change to a user or their permissions (who changed what, and when).

All tabs can be filtered by user, type, PC and date and exported to Excel.

*User Activity & Errors* and *Logins & Security* are **administrator-only**: they need "Manage users" in addition
to their own tick. This is checked by the server for every request, not only hidden in the menu.

---

## 5. Security rules built in

- Passwords: at least 8 characters, letters plus a number or symbol, not the person's name or user name,
  not a common password. They are stored only as a secure hash – nobody can read them, not even the administrator.
- 5 wrong passwords → account locked for 15 minutes.
- Automatic logout after 30 minutes without activity, and after 12 hours in any case.
- You cannot delete or disable yourself, and there is always at least one user who can manage users.
- All values can be changed in `C:\ProgramData\BAMS\config.json` (restart the program afterwards).

---

## 6. Administrator password lost

First ask a **deputy administrator** (see 7.) to reset it in **Users & Permissions**. Otherwise, on the
**administrator PC**: stop the program (Task Manager → Details → BAMS.exe → End task), open a command window as
administrator and run `"C:\Program Files\BAMS\BAMS.exe" tool reset-admin`. It shows a new temporary password for the
administrator account. Log in with it and choose a new password. This action is recorded in the security log.

---

## 7. A deputy administrator (when you are away)

Give a trusted person administrator rights at any time, and take them back at any time:

1. **Users & Permissions** → open the person.
2. **Logs in with: User name and password** (administrator rights are never possible with a personal link) and give
   a temporary password.
3. Profile **Administrator** (or tick the orange *Administrator rights* yourself) → **Save**.

People, permissions and PCs can only be changed on the **administrator PC** (from any browser in the network), because
only that PC holds the administrator key. If that PC may be switched off while you are away, also make a second PC a
**backup administrator PC** (Devices & Sync → *Make backup admin*, see GUIDE_Devices_Sync.md). The deputy can then
manage people there too. Everything they do is recorded with their name.

## 8. Help inside the program

**Help** (left menu, also **Settings → Help & User Guide**) answers the usual questions in plain words, with a search
box. Administrators also see the administrator topics.
