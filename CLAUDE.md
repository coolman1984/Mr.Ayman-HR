# Break Area Management System – rules for every change

Owner and developer: Mohamed Fawzy. Users are factory staff and HR managers who are **not technical**.
Before working, load the project skill `bams-development` (`.claude/skills/bams-development/SKILL.md`).

## Always (without being asked)

1. **Keep the memory up to date in the same pull request as the code:**
   - `DEVELOPMENT_HISTORY.md` – new entry at the top: what changed, why, mistakes made, lessons learned.
   - `.claude/skills/bams-development/SKILL.md` – new rules, pitfalls, files, commands.
   - The guides that describe what changed (`GUIDE_*.md`, `README.md`, `docs/*`), `TASKS.md` test map,
     `DISTRIBUTED_SYNC_ARCHITECTURE.md` for design changes, `docs/RELEASE_NOTES.md` for user-visible changes.
2. **Test before every push**: the fast tests always, the full suite before a pull request (see Tests).
   Add a regression test for every bug that is fixed.
3. **Review**: for bigger changes let an independent reviewer look for bugs and edge cases; verify and fix
   every real finding; write the lessons into the history.
4. **Simplicity first**: plain English, short sentences, one clear action per screen, nothing technical for normal
   users. The whole program is **English only** (no Arabic text in the program). Replies to the owner are in
   simple Egyptian Arabic.

## Never

- Never synchronise or copy database files between PCs; never share SQLite files over a network drive.
- Never let a personal link carry any administrator right (`auth.ADMIN_PERMS`).
- Never roll back the history (`journal.db`) or delete user data; restores are new changes.
- Never write passwords, session tokens, link tokens or keys into logs.
- Never add a setting that lets a PC stop sharing its changes.
- Never ship readable source code in the installer (`tools/build_windows.py` checks it).
- Never push to `main` directly or force-push; work on a branch, open a pull request, merge only when asked.

## Tests

```
cd tests
python3 -m unittest test_unit test_convergence   # fast
python3 -m unittest test_multinode                # several PCs, real processes (~3 min)
python3 -m unittest test_e2e_browser              # real browser (Playwright), skipped without it
```
Do not edit `server/` or `js/` while the multi-PC or browser tests run (they start servers from the files).
