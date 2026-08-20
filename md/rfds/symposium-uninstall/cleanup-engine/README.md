# Cleanup engine

## TL;DR

- Uninstall discovers only known locations and recorded project roots.
- Dry-run and apply share the same planning and ownership classification.
- External artifacts are retired, mutated, and verified one at a time.
- Blocked or interrupted runs retain all discovery and repair evidence.
- Symposium-private state is finalized only after external integrations are absent or acknowledged.

## Command surface

```text
cargo agents uninstall [--dry-run] [--include-tracked]
                       [--acknowledge <BLOCKER-ID>]...
                       [--quiet] [--json]
```

`--dry-run` performs the same discovery, path validation, Git classification, and ownership verification as apply. It creates no receipt state or tombstone and changes no target.

`--include-tracked` permits structural removal from tracked project configuration after the ordinary identity checks. It never authorizes whole-file deletion.

`--acknowledge` preserves a blocker and transfers responsibility to the user. It does not weaken deletion proof.

`--quiet` suppresses progress, but not errors or the final assessment. The existing global `--json` flag emits one versioned document on stdout while diagnostics remain on stderr.

| Exit code | Meaning |
| --- | --- |
| `0` | Planning or cleanup completed reliably with no live blockers |
| `1` | An operational failure prevented reliable planning or verification |
| `2` | Command-line usage error |
| `3` | Planning or cleanup completed reliably, but live blockers remain |

A dry run with blockers exits `3`.

## Bounded discovery

Uninstall never crawls the user's home directory or disks. It examines only:

1. known global configuration targets for supported adapters;
2. the current workspace when one is explicitly available;
3. targets and roots named by receipts;
4. roots or targets named by permits, notices, tombstones, or acknowledgements;
5. legacy workspace-state files that already contain a root; and
6. fixed Symposium-private directories.

A deleted, moved, or renamed root costs one failed bounded lookup. A project at a new path becomes a separate scope after `cargo agents sync`.

Historical workspace state improves discovery but is not a complete inventory because earlier versions did not record every manually synchronized root. The final assessment reports that limitation instead of claiming knowledge of an unknown pre-receipt checkout.

## Planning

Every candidate receives one disposition:

| Disposition | Meaning |
| --- | --- |
| Removable | Discovery and current identity evidence agree |
| Already absent | The recorded artifact no longer exists |
| Preserved | Policy excludes it from automatic cleanup |
| Acknowledged | The user accepted responsibility for the preserved artifact |
| Conflicting | The current artifact no longer matches Symposium's evidence |
| Operationally unverifiable | A reliable ownership or absence decision could not be made |

The engine builds and prints the complete plan before the first mutation. Ownership decisions use the rules in [Ownership and managed state](../ownership/README.md).

Dry-run stops after planning. It takes shared locks for a consistent snapshot and never writes recovery state.

## Tracked project configuration

Before planning a project-file mutation, uninstall walks ancestors for a `.git` file or directory without launching Git. If none exists, ordinary ownership rules apply and Git need not be installed.

When a repository exists:

- tracked configuration is preserved by default and reported as committed by the project;
- `--include-tracked` authorizes removal of only the proven Symposium structure;
- an unavailable or indeterminate Git tracking query preserves the file as a blocker; and
- reports name the file and structural locator without printing secrets.

Acknowledgement may transfer an entry to the user, but preserving a live unguarded `cargo-agents` invocation or an MCP server that launches it cannot produce a clean assessment. That reference must be removed manually or through `--include-tracked` before the package is removed.

## Applying the plan

Apply follows these phases:

1. Acquire the exclusive installation barrier.
2. Load and reconcile receipts, activation records, acknowledgements, signatures, and bounded legacy roots.
3. Discover, classify, and print the complete plan.
4. For each removable external artifact:
   1. mark only its receipt `retiring`;
   2. retire its project permit or create its global tombstone;
   3. lock, reread, and revalidate the target;
   4. remove only the verified structure;
   5. verify absence; and
   6. retain the completed receipt until finalization.
5. If blockers remain, keep every receipt, activation record, cache, workspace record, log, and telemetry file needed for repair or a rerun.
6. Otherwise finalize telemetry and Symposium-private state.
7. Recompute the assessment, delete completed lifecycle records, release locks, and report.

Retirement is per artifact and occurs immediately before that mutation. Uninstall never disables all hooks as an initial global phase. Private discovery state is never removed while a live blocker remains.

Within a shared configuration file, cleanup parses and revalidates the current structure, edits only the owned entry, writes a sibling temporary file, flushes, atomically replaces, reopens, and verifies. Goose delegates to its verified marker-delimited block editor. A concurrent content change replans the target rather than overwriting it.

## Failure and recovery

A failure before external mutation restores that artifact to `applied` when its registration still matches, republishing its project permit or removing its global tombstone as appropriate.

A crash after retirement leaves only that artifact inactive and repairable. Successful removals are not rolled back. Rerunning uninstall resumes cleanup; `cargo agents sync` restores a still-applied retiring registration.

Transient filesystem failures receive one initial attempt and at most two bounded retries. Every retry reopens and revalidates the target. Permission failures, identity conflicts, unsafe links, indeterminate Git state, and concurrent content changes become blockers rather than unbounded retry loops.

The command is idempotent: a verified absence is an `Already absent` result, and a rerun does not recreate removed state.

## Concurrency and locks

Managed mutation uses this lock order:

```text
installation barrier
    → managed-state lock
    → global target when needed
    → workspace targets sorted by normalized path
```

- Uninstall holds the installation barrier exclusively for plan, mutation, and verification.
- Dry-run holds the barrier and discovered targets in shared mode so it cannot observe a target mid-mutation.
- Init, sync, and repair use shared installation access with exclusive locks for state and targets they change.
- Hook-triggered auto-sync uses a non-blocking try-lock. On contention it skips that cache refresh and continues from already-published state.

After dry-run locks its discovered targets, it checks the managed-state generation. One change retries the snapshot; a second is an operational failure rather than an inconsistent preview.

Platform implementations use native advisory locking and multi-process tests. Lock diagnostics may include operation, process, and start metadata, but age alone never proves a lock is stale.

## Blockers and acknowledgements

A blocker ID is stable over:

```text
artifact type + adapter + normalized target + structural locator
```

The acknowledgement stores that complete locator and the artifact's current identity instead of trusting the display ID alone. A moved locator creates a new blocker, and a changed artifact invalidates the acknowledgement.

Acknowledgement:

- preserves the artifact;
- records that the user accepts responsibility;
- retires Symposium's ownership claim;
- prints a redacted manual edit; and
- makes a later installation treat the occupied slot as a structural collision.

Acknowledgement records can be deleted at successful finalization because collision detection inspects the current occupied entry. There is no `--force`: bypassing identity checks would permit deletion of user or third-party state.

## Minimal startup and finalization

Uninstall dispatches before ordinary startup. It initializes only argument parsing, managed-state path resolution, minimal diagnostics, locking, cleanup, and reporting. It does not refresh registries, load plugins, run update checks, auto-sync, or initialize ordinary telemetry recording.

Telemetry finalization uses the telemetry subsystem's supported coordination path. If telemetry cannot be finalized, the command retains discovery and recovery state and reports a blocker. The uninstall result itself is not recorded as new telemetry.

Only after every external integration is absent or validly acknowledged does cleanup remove private caches, workspace state, telemetry, logs, receipts, permits, tombstones, notices, acknowledgements, and the empty managed-state directory. It verifies finalization before reporting success.

## Reporting

Human output groups:

- `Removed`;
- `Already absent`;
- `Preserved`;
- `Acknowledged`;
- `Blocked`; and
- `Next steps`.

Every machine-readable item has a stable kind, adapter, scope, target, structural locator where applicable, disposition, reason code, and live-reference flag. Secret-bearing fields are redacted. The proposed [command reference](../cargo-agents-uninstall/README.md) defines the complete JSON shape and human examples.

## Removal assessment

| Assessment | Meaning |
| --- | --- |
| `ready` | No live integration remains in recorded and inspectable scopes, and no historical limitation applies |
| `ready-for-known-scopes` | Known scopes are clean, but a pre-receipt project may be unrecorded |
| `blocked` | A live reference, ownership conflict, or operational verification failure remains |

The durable coverage origin defined by the ownership model makes this decidable:

- only `managed-only` can produce `ready`;
- `pre-receipt` and `unknown` produce at best `ready-for-known-scopes`; and
- any live blocker produces `blocked`.

The origin is never promoted automatically. Output says that known scopes are clean rather than claiming universal safety when an unknown checkout may exist.

## Acceptance tests

The feature extends the existing deterministic integration harness. Tests cover:

- bounded global, current-workspace, receipt, and historical discovery;
- dry-run and apply classification parity, output, and exit codes;
- tracked, untracked, read-only, and indeterminate-Git configuration;
- interruption at every lifecycle boundary and idempotent reruns;
- target contention, shared previews, concurrent edits, and auto-sync try-locks;
- stable acknowledgements, changed artifacts, and reinstall collisions;
- two bounded retries and permanent failures;
- telemetry and private-state finalization failures;
- `ready`, `ready-for-known-scopes`, and `blocked` assessments; and
- the original stale-global-hook regression after package removal.
