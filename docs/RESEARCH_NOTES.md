# Research notes – replication options (collected 2026-09-26)

Collected with web search and shallow clones of the primary repositories. Sites blocked by the
research proxy (sqlite.org, rfc-editor.org, docs.ditto.live, litesync.io, powersync.com) were
read through search extracts; re-check quotes before citing them externally.

## Options

| Option | Status (Sept 2026) | Topology / deployment | Conflicts | Verdict |
|---|---|---|---|---|
| SQLite Session Extension – https://sqlite.org/sessionintro.html | part of SQLite, public domain; needs `SQLITE_ENABLE_SESSION` | C API; **not exposed by CPython `sqlite3`**, the Windows 3.12 build does not compile it in | conflict handler (OMIT/REPLACE/ABORT), no causality | capture/apply tool, not a replication protocol; unusable without a custom `sqlite3.dll` |
| cr-sqlite – https://github.com/vlcn-io/cr-sqlite | MIT; last release v0.16.3 (Jan 2024), sparse community commits | native loadable extension (loadable from Windows CPython) | column LWW + causal-length delete sets; no counters/resolvers/signing | closest fit but dormant, native, LWW-only (wrong for inventory) |
| Ditto – https://docs.ditto.live | commercial, SDK v5 active | P2P mesh, CRDTs; no Python SDK | delta CRDTs | licence + no Python |
| CouchDB / PouchDB – https://docs.couchdb.org/en/stable/replication/conflicts.html | Apache-2.0, active | Erlang server on every PC; documents | deterministic winner + kept `_conflicts` | would replace the data layer; idea borrowed (winner + kept losers) |
| PowerSync – https://docs.powersync.com | active, FSL service licence | central DB + sync service, hub-and-spoke | server authoritative | needs central server |
| Electric – https://electric.ax | Apache-2.0, active | central Postgres read-path sync | server authoritative | needs central server |
| LiteSync – https://litesync.io | closed source, commercial | modified SQLite DLL, primary/secondary roles | deterministic statement order | closed, opaque semantics |
| Litestream | active | WAL shipping, single writer | – | backup only |
| LiteFS | stalled (last commit 2025-04) | FUSE, Linux, single primary | – | no |
| rqlite / dqlite | active | Raft, quorum needed | – | writes stop without majority – violates offline-first |
| libSQL / Turso embedded replicas | active | hub-and-spoke to cloud | last push wins | needs cloud |
| Automerge / Yjs | active (Rust cores; `automerge`, `pycrdt` native wheels) | document CRDTs | CRDT | native wheels, model mismatch |

## Concepts and sources

* Hybrid logical clocks – Kulkarni, Demirbas et al., 2014, https://cse.buffalo.edu/tech-reports/2014-04.pdf
* Lamport clocks – CACM 1978, https://lamport.azurewebsites.net/pubs/time-clocks.pdf
* Dotted version vectors – Preguiça et al. 2010, https://arxiv.org/abs/1011.5808
* CRDTs (op-based need causal delivery; MV-register; PN-counter; tombstones) – Shapiro et al.
  2011, https://inria.hal.science/inria-00609399 and RR-7506 https://inria.hal.science/inria-00555588
* Local-first software – Kleppmann et al. 2019, https://www.inkandswitch.com/local-first/
* Tamper-evident logging – Crosby & Wallach 2009,
  https://static.usenix.org/event/sec09/tech/full_papers/crosby.pdf ; Certificate Transparency
  RFC 6962 / 9162; git parent hashes. A per-node hash chain is tamper-evident for its entries and
  proves consistency only when peers keep and compare chain heads (we do: every sync compares
  head hashes).

## Standard-library facts verified

* Python `ssl` (OpenSSL 3.0.x, also bundled with CPython 3.12 for Windows) completes TLS 1.3
  handshakes with self-signed Ed25519 certificates and PKCS#8 keys; `getpeercert(True)` gives the
  DER for fingerprint pinning. Verified locally with the certificates produced by
  `server/tlscert.py`.
* The standard library cannot generate keys or X.509 certificates → `server/tlscert.py` +
  `server/ed25519.py`.
* SQLite WAL: "Transactions that involve changes against multiple ATTACHed databases are atomic
  for each individual database, but are not atomic across all databases as a set"
  (https://www.sqlite.org/wal.html). We therefore do **not** rely on cross-file transactions:
  `journal.db` is the source of truth and each materialised database stores per-origin fold
  markers inside its own transactions, so a crash between the two commits is repaired by
  re-folding. The journal is deliberately a separate file so that a business-data restore can
  never roll back history.
* RFC 8032 §6 reference code is "not intended for production" (slow, not side-channel safe).
  Our implementation follows §5.1 with a precomputed base table; it is cross-checked against the
  RFC 8032 test vectors and OpenSSL. Verification uses only public data; signing timing is only
  observable on the signing PC itself (outside the threat model).
