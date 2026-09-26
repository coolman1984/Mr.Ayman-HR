# Distributed Sync – Work Plan and Status

Design: `DISTRIBUTED_SYNC_ARCHITECTURE.md`. Research: `docs/RESEARCH_NOTES.md`.
Branch: `claude/distributed-offline-first-sync-cg26d2`.

## Phases

- [x] 0. Read the whole code base; research alternatives; decision record
- [x] 1. Crypto foundations: `ed25519.py` (RFC vectors + OpenSSL cross-check), `tlscert.py` (TLS 1.3 handshake verified)
- [ ] 2. Node identity + journal (`node.py`, `journal.py`): changesets, HLC, version vectors, chain, signatures, log views, integrity check
- [ ] 3. Deterministic fold (`replica.py`) + `Store.commit` producing changesets; recovery on start
- [ ] 4. Accounts: authority-signed admin changesets, own-password changesets, local sessions/lockouts, admin-only monitoring
- [ ] 5. Sync transport (`sync.py`): TLS server, sessions, pull/push, peer manager, pairing, attachments, sync log
- [ ] 6. Upgrade migration, backups incl. journal, compensating restore, disaster rebuild, clone detection
- [ ] 7. UI: Devices & Sync, sync indicator, conflicts, monitoring, join wizard, read-only users on member PCs
- [ ] 8. Tests (below) + browser end-to-end
- [ ] 9. Independent review, fixes, docs, PR

## Test scenarios (tests/)

| # | Scenario | Test | Status |
|---|---|---|---|
| 1 | fresh one-node install | | |
| 2 | upgrade of an existing database | | |
| 3 | administrator creates users | | |
| 4 | node enrolment | | |
| 5 | initial full sync | | |
| 6 | normal real-time sync | | |
| 7 | administrator PC disappears | | |
| 8 | other nodes continue working | | |
| 9 | administrator PC returns | | |
| 10 | automatic catch-up | | |
| 11 | two offline nodes add different records | | |
| 12 | … modify different fields of one record | | |
| 13 | … modify the same field | | |
| 14 | concurrent inventory movements | | |
| 15 | delete while another node edits | | |
| 16 | tombstone propagation | | |
| 17 | duplicate delivery | | |
| 18 | out-of-order delivery | | |
| 19 | network interruption halfway | | |
| 20 | process crash during sync | | |
| 21 | restart after crash | | |
| 22 | attachment transfer interruption | | |
| 23 | attachment hash verification | | |
| 24 | user disabled while a node is offline | | |
| 25 | permission changes propagate | | |
| 26 | unauthorised user attempts admin action | | |
| 27 | unauthorised node attempts sync | | |
| 28 | replay of an old authenticated sync request | | |
| 29 | audit log tampering detection | | |
| 30 | backup and restore interaction | | |
| 31 | three/four nodes changing data independently | | |
| 32 | repeated disconnect/reconnect cycles | | |
| – | randomized deterministic convergence (fixed seeds) | | |
