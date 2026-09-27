# Building and Releasing a New Version

Everything below happens on GitHub; no Windows PC is needed for building. For the developer only.

## Make a new version

1. Change the code on a branch, run the tests (`CLAUDE.md` → Tests) and merge the pull request.
   The workflow **Test and build** runs on every pull request: tests on Linux, then the Windows build.
2. Raise the version in `server/version.py` (e.g. `2.2.0` → `2.2.1` for fixes, `2.3.0` for new features).
3. Add the entry to `DEVELOPMENT_HISTORY.md` and write `docs/RELEASE_NOTES.md` (what the users notice, short).
4. Create the tag on `main`: `git tag v2.2.1 && git push origin v2.2.1`.
5. GitHub builds `BAMS-Setup-2.2.1.exe` and publishes it under **Releases** (about 15–20 minutes).
   Without a tag, the installer of every build is under **Actions → the run → Artifacts** for 30 days.

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
