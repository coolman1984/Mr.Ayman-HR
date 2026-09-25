# Guide: Users, Passwords and Permissions

Every person logs in with their **own** user name and password. The administrator decides, with simple
tick boxes, what each person may see and do. Everything each person does is recorded with their name.

---

## 1. First start – create the administrator

1. On the **server PC** (the PC running `start.bat`) the browser opens by itself.
2. Enter your full name, a user name (e.g. `ayman`) and a password, then click **Create Administrator**.

> This screen only works on the server PC. Other PCs see "System not set up yet" until it is done.

---

## 2. Add a user

1. **Users & Permissions** (left menu) → **Add User**.
2. Fill in the full name, a user name and (optionally) job title. A temporary password is already suggested.
3. **Break areas:** *All break areas*, or *Only the selected break areas* and tick them.
   The user will not even see the other areas.
4. **Permissions:** choose a **Quick role** to fill the ticks, then add or remove single ticks as you like.
   Ticking a group title ticks the whole group.
5. **Create User** → give the shown user name and password to the person privately.
   At the first login they must choose their own password.

| Quick role | Typical person |
|---|---|
| Administrator | You – everything, including users and backups |
| Manager | Everything except users, restoring backups, import and the security log |
| Data Entry | Sees the pages, records inventory, issues, inspections, maintenance, surveys, uploads photos |
| Maintenance Team | Sees break areas and maintenance, follows up issues, completes maintenance |
| Viewer | Sees everything and runs the reports, changes nothing |

Changes to a user apply **immediately**, even if that person is logged in right now.

---

## 3. Everyday administration

Open the user (**Users & Permissions** → **Edit**):

| Need | Button / field |
|---|---|
| Person forgot the password | **Reset Password** (new temporary password, logged out everywhere) |
| Account locked after 5 wrong passwords | **Unlock** (or wait 15 minutes) |
| Throw someone out now | **Log Out Now** |
| Block for a while (vacation, suspension) | **Account → Disabled** |
| Person left the company | **Delete** (history stays in the logs, user name stays reserved) |
| See what the person did | **Activity** |

The list shows who is **online now**, the last login and badges such as *Locked* or *New password*.

---

## 4. Monitoring – who did what

**Activity Log** (left menu) has three tabs:

- **Data Changes** – every added, changed or deleted record with the old and new values.
- **User Activity & Errors** – pages opened, clicks, exports, saves, refused attempts ("denied").
- **Logins & Security** – logins, logouts, wrong passwords, lockouts, automatic logouts, password
  changes and every change to a user or their permissions (who changed what, and when).

All tabs can be filtered by user, type and date and exported to Excel.

---

## 5. Security rules built in

- Passwords: at least 8 characters, letters plus a number or symbol, not the person's name or user name,
  not a common password. They are stored only as a secure hash – nobody can read them, not even the administrator.
- 5 wrong passwords → account locked for 15 minutes.
- Automatic logout after 30 minutes without activity, and after 12 hours in any case.
- You cannot delete or disable yourself, and there is always at least one user who can manage users.
- All values can be changed in `config.json` (restart `start.bat` afterwards).

---

## 6. Administrator password lost

On the **server PC** double-click **reset_admin.bat**. It shows a new temporary password for the
administrator account. Log in with it and choose a new password. This action is recorded in the security log.
