# Distributed Sync – Work Plan and Status

Design: `DISTRIBUTED_SYNC_ARCHITECTURE.md`. Research: `docs/RESEARCH_NOTES.md`.
Branch: `claude/distributed-offline-first-sync-cg26d2`.

## Phases

- [x] 0. Read the whole code base; research alternatives; decision record
- [x] 1. Crypto foundations: `ed25519.py` (RFC vectors + OpenSSL cross-check), `tlscert.py` (TLS 1.3 handshake verified)
- [x] 2. Node identity + journal (`node.py`, `journal.py`): changesets, HLC, version vectors, chain, signatures, log views, integrity check
- [x] 3. Deterministic fold (`replica.py`) + `Store.commit` producing changesets; recovery on start
- [x] 4. Accounts: authority-signed admin changesets, own-password changesets, local sessions/lockouts, admin-only monitoring
- [x] 5. Sync transport (`sync.py`): TLS server, sessions, pull/push, peer manager, pairing, attachments, sync log
- [x] 6. Upgrade migration, backups incl. journal, compensating restore, disaster rebuild (`nodectl.py`), clone detection
- [x] 7. UI: Devices & Sync, sync light, conflicts, monitoring (PC column), join wizard, read-only users on member PCs
- [x] 8. Tests (below) + browser end-to-end
- [x] 9. Independent reviews (correctness, security) – all verified findings fixed with regression tests (see DISTRIBUTED_SYNC_ARCHITECTURE.md §13a)
- [x] 10. Simpler screens for non-technical users: sync light only for administrators, one code to add a PC, plain wording, automatic IP follow-up
- [x] 11. Personal links: a fixed link per user that logs in under their own name on any PC (Devices & Sync → Personal links)
- [x] 13. Windows installer (compiled BAMS.exe, one setup for install and update, data in ProgramData), sharing always on, warning for silent PCs, development history, project rules and skill
- [x] 12. People with only a link (no user name / password), permission tick boxes with Select all / Clear all, profiles (ready-made and own, applied to everybody who has them), plainer Settings

## How to run the tests

```
cd tests
python3 -m unittest test_unit test_convergence        # ~35 s
python3 -m unittest test_multinode                    # ~2.5 min, starts real server processes
python3 -m unittest test_e2e_browser                  # needs Playwright + Chromium, skipped otherwise
```

## Test scenarios (tests/)

| # | Scenario | Test | Status |
|---|---|---|---|
| 1 | fresh one-node installation | `test_multinode.T01_SingleNode` | pass |
| 2 | upgrade of an existing database | `T02_Upgrade`, `test_unit.NodeSafetyTest.test_interrupted_upgrade_is_repeated` | pass |
| 3 | administrator creates users | `T03_Cluster.test_a`, `T00_DefinitionOfSuccess` | pass |
| 4 | node enrolment | `harness.pair` (every multi-node test), browser test | pass |
| 5 | initial full sync | `T03_Cluster.test_a`, browser test | pass |
| 6 | normal real-time sync | `T03_Cluster.test_b` (< 10 s) | pass |
| 7 | administrator PC disappears | `T03_Cluster.test_c`, `T00` | pass |
| 8 | other nodes continue working | `T03_Cluster.test_c`, `T00` | pass |
| 9 | administrator PC returns | `T03_Cluster.test_c`, `T00` | pass |
| 10 | automatic catch-up | `T03_Cluster.test_c`, `T00` | pass |
| 11 | two offline nodes add different records | `T11_Conflicts.test_concurrent_everything` | pass |
| 12 | … modify different fields of one record | same | pass |
| 13 | … modify the same field | same + `test_unit.FoldRulesTest`, browser test (resolve in UI) | pass |
| 14 | concurrent inventory movements | same + `test_convergence` counter check | pass |
| 15 | delete while another node edits | same + `test_unit.FoldRulesTest.test_no_resurrection_by_old_edit` | pass |
| 16 | tombstone propagation | same | pass |
| 17 | duplicate operation delivery | `test_unit.JournalRulesTest.test_duplicates_and_out_of_order`, `test_convergence` | pass |
| 18 | out-of-order delivery | same + `test_gap_waits_and_causal_order` | pass |
| 19 | network interruption halfway | `T19_Crashes.test_a_interrupted_transfer` | pass |
| 20 | process crash during sync | `T19_Crashes.test_b_crash_during_sync_and_restart` | pass |
| 21 | restart after crash | same | pass |
| 22 | attachment transfer interruption | `T19_Crashes.test_c_attachments` | pass |
| 23 | attachment hash verification | `T19_Crashes.test_c_attachments`, `test_d_corrupt_copy_rejected` | pass |
| 24 | user disabled while another node offline | `T03_Cluster.test_d_user_disabled_while_pc_offline` | pass |
| 25 | permission changes propagate | same, `T00` | pass |
| 26 | unauthorised user attempts admin action | `T03_Cluster.test_e_member_cannot_do_admin_actions`, `T00`, browser test | pass |
| 27 | unauthorised node attempts sync | `T03_Cluster.test_f_unknown_pc_and_replay`, `test_g_revoke` | pass |
| 28 | replay of an old authenticated sync request | `T03_Cluster.test_f_unknown_pc_and_replay` | pass |
| 29 | audit log tampering detection | `T29_Tamper`, `test_unit.JournalRulesTest.test_bad_signature_refused`, `test_fork_detected` | pass |
| 30 | backup and restore interaction | `T30_Restore`, `test_unit.NodeSafetyTest.test_rolled_back_journal_gets_new_epoch`, `ToolsTest.test_rebuild_gives_identical_data` | pass |
| 31 | three or four nodes changing data independently | `T31_FourPCs`, `test_convergence` (4 PCs) | pass |
| 32 | repeated disconnect/reconnect cycles | `T11_Conflicts.test_repeated_disconnects` | pass |
| – | randomized deterministic convergence (6 fixed seeds, partitions, duplicate / reordered / truncated delivery) | `test_convergence` | pass |
| – | forged administrator change, own-password-only rule, data changes touching accounts | `test_unit.JournalRulesTest` | pass |
| – | acceptance story (definition of success) | `T00_DefinitionOfSuccess` | pass |
| – | review regressions: save between receive and fold, impossible change, followers, weak restore delete, fingerprint cache, password proof, pre-auth limits, account records hidden | `test_unit.ReviewFindingsTest`, `T03_Cluster.test_f2`, `test_f3`, `test_e` | pass |
| – | personal links: create/show on the administrator PC only, use on another PC, preview does not log in, own name and permissions, last used on which PC, wrong link refused and logged, new link kills the old one and its sessions, switch off, administrators refused | `T32_PersonalLinks`, `test_e2e_browser.test_personal_link` | pass |
| – | people & profiles: link-only person (automatic user name, no password), link never with administrator rights (person, profile), own profile made / renamed / applied on every PC / deleted, ready-made profile changed, Administrator profile locked, only on the administrator PC, link → password and back, account and profile changes hidden from non-administrators | `T33_PeopleAndProfiles`, `test_e2e_browser.test_personal_link` | pass |
| – | installed program: data in BAMS_HOME, pages from inside the program, nothing else fetchable, tools, second start | `T34_InstalledMode`, GitHub workflow smoke test of BAMS.exe | pass |
| – | second review: program folder unreadable, area limits on old+new area, no client conflict decisions, bad file references, failed-login limit, small requests before login, tools wait, recycle bin scope, saved change survives a failing note file, applying retried, future clock capped | `T35_SecondReview`, `test_unit.SecondReviewTest` | pass |
| – | silent PC warning (once a day, only active PCs) | `test_unit.QuietPcTest` | pass |
| – | 2.3.1: PC list identical in any arrival order with two signing PCs (removal final, concurrent removals, rebuilt on upgrade); network folders and mapped network drives refused for backups | `test_unit.Review231Test` | pass |
| – | delegation: backup administrator PC gets the key over the pinned connection, manages people while the administrator PC is off, role ended → key deleted; only the administrator PC can give the role | `T36_BackupAdminPC` | pass |
| – | 2.3 admin safety: second backup folder (refused inside the data / relative, copy at once and on every backup, saved in config.json, removed), administrator key saved from the screen (passphrase ≥ 12, never readable, remembered), activity log in the Excel export only for administrators | `T37_AdminSafety` | pass |
| – | first start: choice empty / sample data; Help & User Guide from Settings, administrator answers, search | `test_e2e_browser` | pass |
| – | browser: setup, pairing through the screens, login on 2nd PC, viewer has no access (UI + API 403), live change, sync light green/offline, logs with PC, conflict shown and resolved in UI, no console errors | `test_e2e_browser` | pass |
