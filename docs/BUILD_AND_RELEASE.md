# Building and Releasing a New Version

Everything below happens on GitHub; no Windows PC is needed for building. For the developer only.

## Make a new version

1. Change the code on a branch, run the tests (`CLAUDE.md` → Tests), and open a pull request.
   The workflow **Test and build** runs on every pull request: tests on Linux, then the Windows build.
2. In the same pull request raise the version in `server/version.py` (e.g. `2.2.0` → `2.2.1` for fixes,
   `2.3.0` for new features), add the entry to `DEVELOPMENT_HISTORY.md` and write `docs/RELEASE_NOTES.md`
   (what the users notice, short).
3. Merge the pull request. GitHub builds `BAMS-Setup-<version>.exe` again from `main` and publishes it under
   **Releases** as `v<version>` (about 5–10 minutes). Nothing else to do – no tag needed.
   A version that already has a release is not published twice (raise the version for a new release).
4. The installer of every build (also pull requests) is under **Actions → the run → Artifacts** for 30 days.

## Data safety of every release

Before a release: add the commit of the PREVIOUS release to `RELEASES` in `tests/test_multinode.py` (`T41_UpgradeKeepsData`). The test starts that real program on a
data folder, fills it, and starts the new program on the same folder: everything must still be there. Nothing else may rewrite user data without a `MIGRATIONS` step
(`server/upgrade.py`). The installer never touches `%ProgramData%\BAMS`; the program itself makes a verified copy of the data (`data/upgrades/`) before an update
changes anything, and refuses to start with data of a newer version.

## Give it to the company

1. Install it on the **administrator PC** first, then on every other PC **that has the program**.
   People who only use a personal link need nothing.
2. The same `BAMS-Setup.exe` installs (new PC) or updates (PC that has it). The data is never touched.
3. A PC that is updated later keeps working; the changes of updated PCs wait there until it is updated
   (Devices & Sync → Warnings shows "Update needed").
4. Windows may show "Windows protected your PC / unknown publisher" the first time → **More info → Run anyway**.
   (Only a paid code-signing certificate removes this message.)

## What the installer does

| | |
|---|---|
| Program | `C:\Program Files\BAMS\BAMS.exe` (compiled, no source files) |
| Data, settings, backups | `C:\ProgramData\BAMS\` – kept on update and on uninstall |
| Start | Start menu + desktop icon; optional "start with Windows" (runs in the background) |
| Network | Windows firewall rule for `BAMS.exe` (web 8080, PCs 8443) |
| Update | stops the running program, replaces the program, starts it again |
| Old portable version | on a first install it can bring the data of the old folder (with `start.bat`) |

Maintenance tools on an installed PC (command window as administrator):
`"C:\Program Files\BAMS\BAMS.exe" tool status` – also `verify`, `rebuild`, `reset-admin`,
`export-authority <file>`, `import-authority <file>` (see `server/nodectl.py`).

## Build on a Windows PC by hand (optional)

```
py -3.11 -m pip install "nuitka>=2.4,<3" ordered-set zstandard
(install Inno Setup 6)
py -3.11 tools\build_windows.py
```
The installer is written to `dist\`.

## Protection – what it does and does not do

- The installed PC has no readable program files: the code is compiled to machine code and the web pages are
  inside `BAMS.exe`. Nobody changes the program by editing files, and an AI agent on that PC finds no source code.
- The source code lives only in the developer's GitHub repository – keep the repository **private**.
- Licence and copyright are shown on the installer and in the program.
- Like every program on a PC, a specialist with a lot of time could still take it apart; this level of protection
  is meant against editing, copying and casual changes.
