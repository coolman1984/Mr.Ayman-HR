# Distributed, Offline-First Sync – Architecture Decision Record

Status: implemented (see `TASKS.md` for the build log and test status).
Audience: the engineer who maintains this system after us. The administrator guide is
`GUIDE_Devices_Sync.md`.

---

## 1. Where we started (single-server architecture)

| Part | What it does |
|---|---|
| `server/app.py` | stdlib `ThreadingHTTPServer`; serves the SPA and a JSON API; every request is authorised server-side |
| `server/store.py` | `data/bams.db` (SQLite, WAL, `synchronous=FULL`). 12 business entities, one table each, common columns `id, ver, created_*, updated_*, deleted, deleted_*`. A save is one `commit()` = one SQLite transaction with optimistic `ver` checks, soft deletes, and audit rows (`audit_log` table + monthly `audit-*.jsonl`) |
| `server/auth.py` | `data/auth.db`: users (PBKDF2-SHA256 600k), sessions (hashed tokens), lockout, `security_log` (+ `security-*.jsonl`) |
| `server/backup.py` | online-backup API copies of `bams.db` (+ `auth.db`), integrity checked, uploads mirrored; restore = file copy back |
| `js/app.js` | SPA; edits an in-memory copy and sends *changed rows* (`put`/`del` with the row's `ver`) to `/api/commit` |

Strengths we keep: transactions, optimistic versioning, soft delete + Recycle Bin, server-side
permission checks per change, audit of every change, verified backups, zero-install runtime.

Limits: one PC is the server; if it is off nobody works. `audit_log`/`activity_log` live inside
`bams.db`, so a restore rolled them back (only the jsonl files survived).

## 2. Decision

**Keep Python + SQLite + the existing app, and add a purpose-built logical replication layer**
(operation journal + deterministic merge), written with the standard library only.

### Alternatives considered

| Option | Why not (for this app) |
|---|---|
| Copy / share `bams.db` files (network drive, file sync) | Corrupts SQLite under concurrent writers, loses concurrent work. Explicitly forbidden. |
| SQLite Session Extension (changesets) | C API, not exposed by Python's `sqlite3`; changesets carry no causality, conflict handler needs a central order. |
| cr-sqlite (CRDT SQLite extension) | Native loadable extension per platform, project activity has slowed; column-LWW only – wrong for inventory, no authority/permission model, no signed history. |
| Ditto | Commercial SDK, no Python SDK, licence + vendor lock-in. |
| CouchDB / PouchDB | Would need a CouchDB server installed on every PC and a rewrite of the data layer; revision-tree conflicts still need app-level merge. |
| PowerSync / Electric | Need a central Postgres (or Mongo/MySQL) + a sync service; server-authoritative, not peer-to-peer; admin PC would have to be always on. |
| LiteSync | Commercial modified SQLite library. |
| rqlite / dqlite (Raft) | Need a quorum: with 3 PCs and 2 switched off, nobody can write. Opposite of offline-first. |
| Litestream / LiteFS | Single writer replication / backups, not multi-master. |
| Automerge / Yjs | Document CRDTs with native bindings; mismatch with relational rows and reports. |

What we borrow from the literature: hybrid logical clocks (Kulkarni et al. 2014), version
vectors, op-based CRDTs with causal delivery (Shapiro et al. 2011), multi-value registers,
PN-counters, durable tombstones, local-first principles (Kleppmann et al. 2019), hash-chained
tamper-evident logs (Crosby & Wallach 2009; git / Certificate Transparency style chaining).
A research summary with sources is in `docs/RESEARCH_NOTES.md`.

The deciding factors, in the project's priority order: no data loss and deterministic
convergence need *business-aware* merge rules (inventory!), which no generic tool gives us;
authority over user accounts needs signatures bound to the administrator PC; and the
portable, zero-install deployment rules out servers and native extensions.

## 3. Vocabulary (used in code and UI)

| Term | Meaning | UI wording |
|---|---|---|
| node | one installation (one PC) with its own `data/` | "PC" / "device" |
| authority | the node holding the administrator key (the administrator PC) | "administrator PC" |
| replica id (`origin`) | `<node_id>-<epoch>`; the stream a node writes into. A new epoch starts whenever a node's own history might have been rolled back | – |
| changeset | one saved action (like a git commit): list of ops + metadata, signed, hash-chained | "change" |
| `cseq` | per-origin changeset counter 1,2,3… without gaps | – |
| version vector (vv) | `{origin: highest contiguous cseq}` – "I have everything up to X from A, Y from B" | – |
| HLC | hybrid logical clock `physical_ms << 16 | counter` | – |
| fold | applying a changeset to the materialised tables | – |

## 4. Architecture

```
            browser (same PC: http://localhost:8080)     other PCs' nodes
                    |                                        ^  TLS 1.3, pinned certs
                    v                                        |  session auth + HMAC
  +--------------------- node (server/app.py) -----------------------------+
  |  API (unchanged routes + /api/sync/*, /api/nodes/*, /api/monitor/*)    |
  |    |  Store.commit(): validate, permission guard, diff -> ops           |
  |    v                                                                   |
  |  journal.db  (append-only, never restored)      <---- sync.py -------+ |
  |    changes: origin,cseq,hlc,deps,kind,ops,prev,hash,sig,asig          | |
  |    views:   audit / activity / security (all PCs), nodes roster        | |
  |    |  fold (deterministic, exactly once via per-origin markers)        | |
  |    v                                                                   | |
  |  bams.db  business tables (same schema as before) + sync_field         | |
  |  auth.db  users (replicated) + sessions/lockouts (local only)          | |
  |  uploads/ files by content hash, fetched from peers, verified          | |
  +------------------------------------------------------------------------+
```

Modules (all in `server/`):

| Module | Responsibility |
|---|---|
| `ed25519.py` | RFC 8032 signatures (pure Python, cross-checked against OpenSSL and the RFC vectors) |
| `tlscert.py` | self-signed Ed25519 X.509 certificate + PKCS#8 key (DER by hand) |
| `node.py` | node identity, keys, epoch/rollback guard, authority key, clone detection |
| `journal.py` | `journal.db`: changesets, HLC, version vectors, validation, chain/signature checks, log views, roster, integrity verification |
| `replica.py` | deterministic fold: multi-value registers, resolvers, counters, tombstones, conflict flags |
| `store.py` | business tables; `commit()` now produces a changeset; compensating restore |
| `auth.py` | users/sessions; account changes become authority-signed changesets |
| `sync.py` | sync TLS server, sessions, pull/push, peer manager with backoff, pairing, attachment transfer, sync log |
| `backup.py` | backups now include `journal.db`; restore is compensating (see §11) |

## 5. Data flow of one save

1. Browser sends changed rows (unchanged protocol) to `/api/commit`.
2. Under the store lock, `Store.commit` reads current rows, runs the existing optimistic `ver`
   checks and validation, computes the per-field diff, runs the permission guard.
3. The diff becomes *ops* (§7). Under the journal lock a changeset is built: next `cseq`, HLC,
   `deps` = current version vector, `prev` = hash of this origin's previous changeset,
   `hash`, node signature.
4. The changeset is folded into `bams.db` inside the still-open transaction, then appended to
   `journal.db` (durable, fsync), then `bams.db` commits (with its fold marker).
   Crash between the two commits → on start the journal is re-folded beyond the marker.
5. Peers are nudged; they pull/push within seconds. Receivers verify and append, then fold.

Invariant: **business state = deterministic fold of the journal in causal order.** Every
node runs the same fold code on the same set of changesets, so all nodes converge.

## 6. Changeset format

```json
{"v":1,"id":"<uuid>","origin":"a1b2c3d4e5f6-1","node":"a1b2c3d4e5f6","cseq":42,
 "hlc":1790000000000000000,"deps":{"a1b2c3d4e5f6-1":41,"99aa..-1":17},
 "kind":"data","ts":"2026-09-26T10:00:00","actor":"Sara (sara)","actor_id":"<uid>","ip":"127.0.0.1",
 "label":"Added Chairs – Break Area 01","ops":[...],"prev":"<sha256 hex>"}
```

* canonical JSON (sorted keys, no spaces, UTF-8); `hash = SHA-256("BAMS-CS1\n" + canonical)`;
* `sig` = Ed25519(node key, hash) on **every** changeset; `asig` = Ed25519(authority key, hash)
  on `admin` changesets;
* kinds: `data`, `restore` (compensating restore – weak priority), `bootstrap` (upgrade),
  `admin` (users, nodes – authority only), `account` (own password change), `log` (activity
  and security events).

## 7. Merge semantics (fold)

Each row field is a **multi-value register**: `sync_field` stores the *frontier* – the writes
that no later write has seen. A new write removes the entries it causally dominates
(`deps[origin] >= cseq`) and joins the frontier. With causal delivery a new write is never
dominated by an existing entry. If the frontier holds more than one entry the writes were
concurrent; a deterministic **resolver** picks the displayed value, the other values stay
stored and are shown as a conflict until someone writes a newer value.

Ordering key for LWW: `(priority, hlc, origin)`; priority: restore 0 < data/bootstrap 1 <
account 2 < admin 3. Causally later writes always win (HLC respects causality), resolvers only
matter for truly concurrent writes.

Special registers per row: `_del` (tombstone), `_ins` (created at/by, earliest wins), `_upd`
(updated at/by, latest wins). Counters (`inventory.qty`) are not registers: ops carry deltas
that are added exactly once.

### Conflict policy matrix

| Entity | Insert | Different fields | Same field concurrently | Delete vs edit | Notes |
|---|---|---|---|---|---|
| break areas | keep both (random ids) | merged | LWW, surfaced | delete wins, edit kept in record + flagged | `lastInspection`, `nextInspection`: latest **date** wins; `inspectedBy` follows `lastInspection` |
| inventory | same id `area:item` merges | merged | `condition`,`note` LWW surfaced | delete wins, flagged | **`qty` = counter**: every movement is a delta, concurrent +5 and −2 give +3. Negative result is flagged "please count" |
| transactions (history) | keep all (immutable events) | – | – | delete only with its break area | the ground truth of movements |
| surveys | keep both | merged | LWW surfaced | delete wins | same area+month+department twice is flagged as possible duplicate |
| photos / documents | keep both | merged | LWW (`main` resolves consistently) | delete wins | file content: content-addressed, see §10 |
| issues | keep both | merged | LWW surfaced | delete wins | follow-ups are separate inserts, all kept |
| issue follow-ups | keep all | – | – | delete wins | |
| maintenance | keep both | merged | `status`: Done > In Progress > Scheduled; `doneDate`,`notes` follow; else LWW | delete wins | completion is a physical fact |
| inspections | keep all | merged | LWW | delete wins | |
| item types | same id merges | merged | LWW surfaced | delete wins | |
| settings | per key | – | LWW surfaced | – | |
| user accounts | authority only (single writer) | – | admin beats own-password change | – | see §8 |
| permissions / areas of a user | authority only | – | – | – | |
| devices (roster) | authority only | – | – | revoke is permanent | |
| logs (audit/activity/security) | append-only per PC, never merged | – | – | never deleted | hash chained |

Deletes are durable: an edit never writes `_del`, so an offline PC that edited a deleted row
cannot resurrect it. Only an explicit restore (Recycle Bin) writes `_del = false`; concurrent
delete vs restore → delete wins (the record stays in the Recycle Bin, nothing is lost).
A *compensating restore* delete loses against concurrent real edits (§11).

Open conflicts are **derived from the converged frontier**, so every PC shows the same list.
The administrator resolves one by choosing a value (a normal change that dominates both).

## 8. Authority, trust and threat model

* **Authority**: the administrator PC holds an Ed25519 *authority key*. Every change to users,
  passwords (reset), permissions, break-area restrictions and to the device list is an
  `admin` changeset signed with it. Every PC verifies `asig`; forged admin changesets are
  stored as *rejected* (for forensics), never applied, and raise an integrity alert.
  User management is therefore only possible on the administrator PC (any browser can open the
  administrator PC's address). Other PCs show it read-only with a link.
* **Own password change** works on every PC (`account` changeset): the fold only accepts it for
  `actor_id == user id` and only the password fields; a concurrent admin reset wins.
* **Offline login**: user records (including PBKDF2 hashes) are replicated to every PC.
  Sessions, failed-login counters and lockouts are local. Disable/delete/forced logout/unlock
  take effect on each PC when it receives the admin changeset (window = while it is offline).
* **Node authentication**: each PC has an Ed25519 node key; the roster (admin changesets) pins
  its public key and TLS certificate fingerprint. Revoked PCs cannot open sync sessions.
* **Enrolment**: short-lived single-use pairing code (contains an invite id, a secret and the
  administrator PC's certificate fingerprint) + explicit approval by the administrator with a
  6-digit confirmation code shown on both screens.

**Threat model – protected against:** unknown PCs on the LAN (cannot join or sync), passive
sniffing of sync traffic (TLS 1.3), active MITM between PCs (pinned certificates), replay of
sync requests (single-use challenges, per-session HMAC counters), a normal PC or user forging
administrator/permission changes (authority signatures), ordinary users reading monitoring data
(server-side admin checks), silent edits/deletions of history (hash chains, signatures, copies
on every PC, periodic verification), accidental folder copies (clone detection), restore
rolling back audit (journal outside restore).

**Not protected against (documented residual risks):** a person with OS administrator rights on
a PC can read that PC's data (including password hashes) and can make that PC sign arbitrary
*business* changes under its own identity (they are attributed to that PC and can be traced;
revoke the PC). Such a person can rewrite that PC's *own* chain but not other PCs' copies –
the fork is detected when it syncs. Browser ↔ server traffic stays HTTP (users now use their own
PC's local server, so passwords normally never cross the LAN; HTTPS for browsers can be added
with a company certificate). Lockout counters are per PC. Clock errors can make one PC win LWW
ties more often (they are flagged, never break convergence).

## 9. Sync protocol

Separate TLS port (`sync_port`, default 8443) served by the same process.

1. Client connects, checks the server certificate's SHA-256 against the roster; mismatch →
   disconnect before sending anything.
2. `GET /sync/challenge` → single-use random challenge (60 s).
3. `POST /sync/session` with Ed25519 signature over `BAMS-SESSION1|server|client|challenge` →
   session id + 256-bit session key (inside TLS).
4. Every further request carries `X-BAMS-Session`, strictly increasing `X-BAMS-Seq` and
   `X-BAMS-MAC = HMAC-SHA256(key, seq|method|path|sha256(body))`.
5. `POST /sync/pull {have: vv}` → changesets the client lacks, in the server's journal order
   (a causal order), whole changesets, ~2 MB per batch; `more` flag; server `vv` with head
   hashes (fork detection).
6. `POST /sync/push {changes}` → the server lacks these (computed from its `vv`); same
   validation as pull. Push makes one-directional firewalls work.
7. `GET /sync/file?path=…` with `Range` → attachment bytes.

Receiving rules (identical for pull and push): per origin only `cseq == have+1` is accepted
(duplicates ignored, gaps deferred); `prev` must equal our head hash; all `deps` must already be
present (causal delivery); the node must be in the roster; node signature must verify;
`asig` must verify for `admin`. Same `(origin,cseq)` with a different hash = **fork alert**.
Everything is idempotent: receiving the same changeset 1 or 100 times changes nothing.

Peer manager: one worker per peer, every `sync_interval_seconds` (default 5) and immediately
after a local save; failures back off 5 s → 5 min. "Offline" (connection refused / timeout) is
normal, not an error.

## 10. Attachments

New uploads are stored as `uploads/cas/<sha256>.<ext>` (content-addressed, deduplicated,
self-verifying). Existing files keep their paths; the upgrade records their SHA-256 in the
replicated `attachments` manifest. When a folded row references a file this PC does not have,
it is queued; the fetcher downloads it from any online peer into `uploads/.incoming/*.part`
(resumable with `Range`), verifies SHA-256 and size, fsyncs and atomically renames it into place.
A partial or corrupt file is never served. Missing files show a "being copied" placeholder that
is never cached. Files are never physically deleted (tombstones are on the rows).

## 11. Backups and restore

Replication is not backup; backups stay (and now also copy `journal.db`). `data/node/` keys are
not part of routine backups (the authority key has a passphrase-protected export).

**Restore = compensating change.** "Restore backup" computes the difference between the
current data and the backup and saves it as one `restore` changeset (labelled, audited,
replicated). It is weak: a concurrent real change made on another PC that this PC had not yet
received wins over it (fields, deletes), inventory is restored as deltas. History is never
rolled back; the pre-restore safety backup is still taken; a restore can be undone by
restoring the safety backup. Disaster recovery of damaged files: `python server/nodectl.py
rebuild` re-creates `bams.db` from the journal; a restored `journal.db` makes the node start a
new epoch so its sequence numbers are never reused, and peers send back what it lost.

## 12. Migration (upgrade in place)

On the first start of the new version:
1. Verified pre-upgrade backup of `bams.db` and `auth.db` (abort on failure).
2. Node identity, keys, TLS certificate; if users exist this PC becomes the authority.
3. `journal.db` with bootstrap changesets: users (admin-signed), this PC in the roster,
   every business row incl. deleted ones (timestamped with its own `updated_at`), attachment
   hashes, and the old audit / activity / security logs (marked "imported").
4. Fold → `sync_field` metadata; business rows are unchanged.
5. `data/node/identity.json` is written last. If anything fails before, the partial journal
   is moved aside and the upgrade is retried at the next start; the original data is untouched.

## 13. Failure recovery summary

| Failure | Behaviour |
|---|---|
| crash during save | journal append is the commit point; fold markers make re-fold exact |
| crash / cut connection during sync | nothing partial is applied (per-batch transactions, whole changesets); next round resumes from the version vector |
| duplicate / out-of-order delivery | duplicates ignored, gaps deferred |
| attachment transfer cut | `.part` resumes; hash verified before use |
| PC off for weeks | it catches up from any peer (every PC keeps full history) |
| admin PC off | everybody works; user management waits for it |
| folder copied to another PC | clone detected on start; the copy becomes a new device |
| `journal.db` rolled back / restored | new epoch; peers resend the lost tail |
| forged admin change | rejected everywhere, alert |
| tampered history | chain/signature verification fails, alert; peers hold intact copies |

## 14. Observability

`data/logs/sync-YYYY-MM.jsonl`: one line per sync round (peer, session, direction, counts,
bytes, duration, result, error, retry delay) and per attachment transfer; `journal.db`
`sync_log` keeps the recent entries for the UI. No passwords, tokens, keys or pairing secrets
are ever logged.

## 15. Test strategy

`tests/` (stdlib `unittest`, run `python -m unittest discover -s tests`):
unit tests (crypto vectors, canonical JSON, HLC, fold properties), in-process multi-replica
simulations with fixed seeds (random concurrent edits, partitions, duplicate / reordered /
truncated delivery → identical normalised state hashes), and a multi-process harness that
starts real servers on separate ports with temporary data folders, pairs them, kills them,
cuts connections through a controllable TCP proxy and checks convergence, security and
recovery. See `TASKS.md` for the scenario checklist and results.
