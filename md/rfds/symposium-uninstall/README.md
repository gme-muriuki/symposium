#  Managed Symposium uninstall

## TL;DR

- Add `cargo agents uninstall` as an idempotent cleanup command that runs before `cargo uninstall symposium`.
- Ask users to quit every running agent before cleanup, then restart agents only after the binary has been removed.
- Record Symposium-owned writes in durable receipts. Use receipts to discover artifacts and adapter-specific evidence to prove their identity.
- Give project hook registrations stable IDs and root-bound activation permits. A permit for an ID alone is never enough to run a project hook.
- Use positive permits for project hooks and positive retirement tombstones for global hooks. Losing the managed store must not disable the recommended global workflow.
- Preserve user configuration, custom plugin sources, shared tools, tracked project configuration by default, and every ambiguous artifact.
- Report removed, preserved, acknowledged, and blocked items, followed by a qualified binary-removal assessment.

## Motivation

`cargo uninstall symposium` knows which package binaries Cargo installed. It does not know that Symposium also wrote hook registrations, MCP server entries, generated skills, cache data, or workspace state.

Today an unguarded hook registration can survive removal of the `cargo-agents` binary. Every later hook event then asks the shell to run a command that no longer exists:

```text
/usr/bin/bash: line 1: cargo-agents: command not found
PostToolUse:Bash hook error
```

This is especially visible after a global installation because the stale registration runs in every project. Project-scoped installation creates a different problem: cleanup cannot find arbitrary historical workspaces by scanning the user's filesystem, and a similar-looking entry may belong to another program.

The cleanup contract therefore needs durable discovery evidence, type-specific identity checks, bounded project lookup, and generated commands that become harmless when their binary is absent.

## User workflow

The recommended sequence is:

1. Quit every running Claude, Gemini, Copilot, Codex, Kiro, Goose, OpenCode, or other agent process that may have loaded Symposium-managed configuration.
2. From an ordinary terminal, run `cargo agents uninstall`.
3. Resolve or acknowledge any reported blockers and rerun until the command reports no live integrations in the applicable scopes.
4. Run `cargo uninstall symposium`.
5. Start the agents again.

Quitting first avoids an agent rewriting a settings file from its in-memory copy after cleanup has verified and removed an entry. Restarting after binary removal makes every agent reload the cleaned configuration.

`cargo agents uninstall` does not remove its own executable. A running process cannot portably and reliably remove the package that supplied it, and Cargo already owns package removal.

## Goals

This RFD aims to:

- remove integrations Symposium can prove it manages in global and recorded project scopes;
- remove Symposium-private files only after external integrations are absent or explicitly transferred to the user;
- preserve user-authored and third-party state;
- make interrupted cleanup resumable;
- make copied, moved, and deleted projects safe without filesystem-wide scanning;
- keep the ordinary hook path bounded and free of Cargo subprocesses;
- give humans and automation precise, non-overclaiming results; and
- make new instances of existing managed artifact types participate automatically.

## Non-goals

This RFD does not:

- make a global hook safe to run arbitrary untrusted workspace configuration;
- discover every project ever touched by a pre-receipt Symposium release;
- uninstall shared packages from Cargo or another package manager;
- reverse arbitrary plugin `install_commands`;
- delete user configuration or custom plugin sources; or
- restart or terminate agent processes.

## Threat model and security boundary

Receipts, project permits, and global retirement tombstones primarily provide deterministic cleanup, collision resistance, and a local activation boundary for **project-scoped registrations**. They are not capabilities and they are not secrets.

A project hook may run only when its managed ID and exact registration-owning root match one active permit. Copying a committed ID to another checkout grants no authority because that checkout owns a different configuration path. The hot path resolves the owning root from the process working directory and adapter-relative configuration path; it does not invoke Cargo.

A **global** hook is intentionally valid in every working directory. Symposium currently recommends global hook installation, and ordinary hook startup may discover and load workspace plugin configuration. Therefore this design does not claim that permits protect global-hook users from a hostile repository. Changing that trust model would require gating workspace plugin activation itself and belongs in a separate security design.

The uninstall safety invariant is narrower:

> Symposium deletes external state only when bounded discovery evidence and artifact-specific identity evidence both agree that Symposium manages it.

## Detailed plans

### Terminology and identity

- A **managed ID** is a stable UUID for one logical registration. All event entries belonging to one agent-and-scope hook registration share that ID.
- An **ownership receipt** is durable discovery evidence describing one intended managed mutation, its target, adapter, scope, and lifecycle.
- A **static signature** is a versioned, secret-free structural description of a registration form emitted by a released Symposium version.
- A **dynamic fingerprint** is a receipt-recorded, secret-free identity for an instance whose command or URL came from plugin configuration.
- An **activation permit** is a small positive record for a project hook. It binds a managed ID to exactly one normalized registration-owning root.
- A **retirement tombstone** is a small positive record that temporarily disables a global hook while its registration is being removed.
- A **blocker ID** is a stable, domain-separated hash of artifact kind, adapter, normalized target, and structural locator.

A managed ID is a correlation key, not proof of ownership and not permission to execute. Deletion always requires the expected target and type-specific identity. Project execution always requires a root match.

A blocker ID is `blk_` followed by the lowercase hexadecimal first 16 bytes of SHA-256 over the domain `symposium-blocker-v1` and length-prefixed UTF-8 fields for artifact kind, adapter, normalized target, and canonical adapter-specific structural locator. The acknowledgement stores the full tuple rather than trusting the truncated display ID alone.

### Path and scope identity

Symposium defines one normalization function for receipt targets, permit roots, and runtime comparison:

1. make the path absolute;
2. canonicalize the existing portion of the path;
3. remove the Windows verbatim-path prefix when present;
4. apply platform filesystem case rules on Windows; and
5. compare path components rather than string prefixes.

Every generated invocation carries `--managed-id <UUID>`, but it does not carry an authoritative scope. The binary classifies scope from the directly addressed local receipt, project permit, or global tombstone. An ID or scope-like text in the command is never sufficient.

When local state for the ID is missing or unavailable, preflight enters a bounded degraded classifier. It uses the same registration-owning-root walk defined below and checks the adapter's known global target for an exact released registration signature containing that ID. Exactly one match is required: a project match remains inactive and may show the one-time sync hint; a global match runs and reports degraded health; zero or multiple matches deny plugin dispatch and report ambiguity. This fallback opens only those adapter files and does not invoke Cargo.

For a project registration, the hook preflight starts at the process working directory and performs a depth-bounded ancestor walk. The **registration-owning root** is the nearest ancestor whose adapter project configuration contains an exact released registration signature for this managed ID. Candidate configuration files without that registration are ignored. Execution requires all of:

1. trusted local state or exact degraded classification identifies project scope;
2. the nearest registration-owning root exists;
3. the active permit has the same managed ID; and
4. the normalized permit root equals the normalized registration-owning root exactly.

The permit root being merely an ancestor of the working directory is not enough. An unrelated nested adapter configuration is ignored, while a nested checkout containing a copied matching registration resolves to its own nearer root and is denied. Sync refuses to create a project permit whose root is a filesystem root or the user's home directory.

Adapters must establish the documented working directory before invoking a project hook. An adapter that cannot provide that contract cannot use a project-scoped guarded registration.

Resolved paths, not inode or file IDs, identify targets. This permits a dotfile repository to be recloned without creating an unrecoverable inode conflict. A dev container, WSL environment, and Windows host are separate permit environments even when they expose the same repository through different paths; each requires `cargo agents sync`.

An acknowledgement stores the same locator tuple plus the artifact's identity fingerprint at acknowledgement time. It remains stable across identical reruns, but a moved locator produces a new blocker ID and changed artifact identity invalidates the old acknowledgement.

### Cleanup boundary

The boundary is based on ownership, not on whether a path or command contains the word `symposium`.


| Artifact                                                                                              | Default cleanup behavior                                                                     | Required identity evidence                                              |
| ----------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| Static hook registration                                                                              | Remove its owned entries or dedicated file                                                   | Receipt for discovery plus a released static signature                  |
| Dynamic plugin MCP registration except Goose                                                          | Remove its owned structural entry                                                            | Receipt plus an exact dynamic fingerprint                               |
| Goose dynamic MCP registration                                                                        | Remove one verified marker-delimited YAML block without reserializing surrounding YAML       | Receipt, unique marker pair, indentation, and exact dynamic fingerprint |
| Static built-in MCP registration                                                                      | Remove its owned structural entry                                                            | Receipt or bounded legacy discovery plus a released static signature    |
| Generated skill or mirror                                                                             | Remove generated files; remove the directory only when its manifest accounts for every entry | Receipt, marker, and manifest                                           |
| Dedicated generated file                                                                              | Remove the file                                                                              | Receipt plus marker or released content signature                       |
| Symposium-private cache, logs, telemetry, receipts, permits, tombstones, notices, and workspace state | Remove only during finalization                                                              | Fixed private root and successful external cleanup                      |
| `config.toml`                                                                                         | Preserve                                                                                     | User-owned configuration                                                |
| Custom plugin source                                                                                  | Preserve                                                                                     | User-authored or user-selected source                                   |
| Tracked project configuration                                                                         | Preserve unless `--include-tracked` is given                                                 | Git tracking plus ordinary artifact identity                            |
| User or third-party entry near a managed entry                                                        | Preserve                                                                                     | Symposium evidence is absent or conflicts                               |
| Cargo-installed shared tool                                                                           | Preserve and report                                                                          | Package-manager location is not exclusively owned                       |
| Side effect of arbitrary `install_commands`                                                           | Preserve and report when known                                                               | The effect cannot be reconstructed safely                               |
| Unknown pre-receipt checkout                                                                          | Not automatically discoverable                                                               | No recorded root                                                        |


Preserving `config.toml` retains preferences and plugin declarations, but removing their derived hook, MCP, and skill integrations stops Symposium affecting the agents. A future installation may reuse those preferences only after an explicit sync.

### Central managed mutations

All code that writes externally visible agent state goes through one managed-mutation layer. Callers declare an artifact type and desired value. The layer supplies:

- IDs, receipts, and lifecycle transitions;
- adapter-specific identity evidence;
- collision detection by structurally inspecting the current adapter slot: init and sync do not adopt or overwrite an occupied slot without matching `pending` or `applied` ownership evidence, and signature-catalog migration is a separate explicit path;
- safe target validation and path containment;
- structural read-modify-write behavior or Goose's verified byte-extent block edit;
- atomic file replacement; and
- the corresponding cleanup operation.

Adding another hook, skill, or MCP server through an existing artifact type therefore does not require uninstall-specific code. A genuinely new side-effect type needs a new ownership adapter because its proof and safe deletion rules differ.

### Receipt lifecycle

Receipts live below a versioned managed-state directory in the resolved Symposium configuration home. They contain paths and identity metadata, never executable instructions, tokens, environment values, or header values.

A receipt moves through:

1. `pending`: intent is durable, but the external write is not yet confirmed;
2. `applied`: the external artifact matches;
3. `retiring`: this artifact is being removed or has an interrupted removal; and
4. `acknowledged`: the user accepted responsibility for the preserved artifact.

Writers store `pending` before the external mutation, verify the mutation, then store `applied`. Recovery reconciles incomplete states by inspecting the target; it never assumes a write succeeded.

For project hooks, the derived positive permit is published last. A project registration cannot become active before its receipt and external write are durable. Global hooks have no positive permit: they run unless a retirement tombstone for their managed ID is present. A completed receipt remains available until the whole uninstall reaches finalization, so a running agent, crash, or blocker cannot erase the only discovery evidence.

`cargo agents sync` is the explicit restore path after interrupted cleanup. When the receipt still describes an applied registration, sync changes a repairable `retiring` state back to `applied`, republishes a project permit, or removes a global retirement tombstone as appropriate. `cargo agents status` reports the repairable state and the exact sync command.

### Static signature catalog

Symposium maintains a versioned catalog of every released **static** registration form, including current forms rather than only legacy forms. Receipts answer “where should cleanup look?”; signatures answer “is the structure at that location one Symposium released?”

The catalog covers:

- static hook commands and their containing structural shape;
- dedicated generated agent files;
- static built-in MCP registrations; and
- generated file markers and manifests where applicable.

Signatures compare parsed structure, normalized executable identity, fixed arguments, and managed ID placement. They do not match on a broad key name, event name, or the presence of `cargo-agents` alone.

The hidden hook CLI accepts an optional managed ID. Its presence selects the new preflight; its absence selects legacy behavior. Scope comes from trusted local state or exact degraded classification, never from the invocation. Legacy hooks continue to run exactly as they do today and are not put behind a new runtime verification step. The next `init` or `sync` may migrate an exact historical signature to the guarded form, and uninstall may remove an exact historical signature from a known location.

### Dynamic MCP identity

Plugin-provided MCP commands, URLs, arguments, and names are not a finite released signature catalog. Their identity is captured when the managed mutation is written.


| Adapter              | Structural container           |
| -------------------- | ------------------------------ |
| Claude, Gemini, Kiro | `mcpServers.<name>`            |
| GitHub Copilot       | Top-level MCP server map entry |
| Codex                | `mcp_servers.<name>`           |
| Goose                | `extensions.<name>`            |
| OpenCode             | `mcp.<name>`                   |


The fingerprint includes the adapter, normalized target, structural container, entry name, transport, and command-plus-arguments or URL. It deliberately excludes environment and header values so receipts do not copy secrets. Removal requires the current entry to match every non-secret identity field; changing one transfers the entry out of automatic cleanup and produces a blocker.

If a dynamic MCP receipt is missing, Symposium preserves the entry. A name and command resemblance are not upgraded into proof. Future schemas may reserve a Symposium metadata field or namespace where the host permits one, but this RFD does not assume such a field exists.

Goose is an explicit editing exception. Its YAML configuration is not round-tripped through a general serializer because doing so would discard comments and user formatting. New Symposium blocks are enclosed by behavior-neutral managed-ID comment markers. Cleanup locates one unique marker pair at the recorded indentation, parses only the enclosed mapping to verify its dynamic fingerprint, and removes that exact byte extent. Missing markers, duplicate markers, invalid indentation, or any fingerprint mismatch preserve the block. Supporting this verified block editor and its malformed-YAML fixtures is a distinct implementation cost.

### Git-tracked project configuration

Project hook registrations may live in files a team intentionally commits. Before planning a project mutation, uninstall asks Git whether the containing file is tracked. This query is outside the hook hot path.

- Uninstall first walks ancestors for a `.git` file or directory without launching Git. If none exists, ordinary ownership rules apply and Git need not be installed.
- A tracked file is preserved by default and reported as “committed by your project.”
- `--include-tracked` authorizes structural removal of the proven Symposium entry, not deletion or wholesale rewriting of the file.
- Only when a `.git` ancestor exists does uninstall query tracking. If Git is then unavailable or returns an indeterminate result, the file is preserved as a blocker.

The report includes the file and structural locator, whether the integration remains live, and a redacted fragment the user can remove or review. It never prints secret values.

### Activation permits and hook preflight

Project and global hooks deliberately fail in opposite directions:

- Project scope is positive-permit: missing, corrupt, unavailable, or non-matching state denies plugin dispatch.
- Global scope is positive-retirement: only a present retirement tombstone disables dispatch. Missing or unavailable managed state does not make the recommended global installation silently inert.

The binary classifies preflight before ordinary startup:


| Trusted classification and state                                                   | Behavior                                                                                                                                   |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Project permit with exact managed ID and registration-owning root                  | Continue to ordinary hook startup                                                                                                          |
| Project permit missing, corrupt, unavailable, or non-matching                      | Do not load plugins or auto-sync; SessionStart may emit one bounded activation or repair hint, other events exit successfully and silently |
| Global retirement tombstone present                                                | Exit successfully and silently                                                                                                             |
| Global retirement tombstone present but corrupt                                    | Exit successfully without plugin dispatch and surface a repair warning                                                                     |
| Global registration proven by receipt or exact degraded signature, no tombstone    | Continue to ordinary hook startup and report degraded health when local state was missing                                                   |
| Missing state with zero or multiple exact registration matches                     | Deny plugin dispatch and surface an ambiguity warning                                                                                       |


An inactive project SessionStart may perform only preflight and emit static `additionalContext` naming `cargo agents sync`. It may not read workspace plugin configuration, refresh a registry, run plugin code, or auto-sync. After the first successful hint for a managed ID and normalized registration-owning root, preflight atomically writes a small notice-suppression record. That root receives no further activation hint unless sync activates it or local managed state is reset. Notice records are capped at 64 roots per managed ID; after the cap, new roots receive neither another stored record nor a repeated hint, and status reports the suppressed count.

Missing project state that means “correctly inactive” is quiet outside the one-time SessionStart hint. Failure to determine project state receives a repair hint. Missing global state continues to run only after the bounded exact global registration check succeeds, because global retirement, not global activation, is the only property this RFD needs.

When the managed-state directory is writable, corrupt project state or missing global state records a health flag for `cargo agents status` and one best-effort log line. When the store itself is unavailable, no persistent flag can be written by definition: status detects the failure on demand, and a bounded SessionStart warning is the only guaranteed signal. Symposium does not invent a second fallback state directory. Corrupt records inside a writable store are quarantined and recreated by the next explicit sync.

### Integration with `cargo agents status`

The uninstall work does not add or own a second status command. It exposes a read-only managed-health snapshot from the managed-state layer for the existing or concurrently developed `cargo agents status` command to consume.

The snapshot contains versioned data for inactive, retiring, corrupt, unavailable, and cleanup-in-progress states, with stable reason codes and recommended commands. Presentation, filtering, and the rest of status output remain owned by the status command.

Status never repairs receipts, permits, or tombstones as a side effect of reading them. It attempts the installation barrier and managed-state lock in shared mode:

- when acquired, it reads one consistent snapshot;
- while uninstall owns the exclusive barrier, it reports `cleanup-in-progress` from lock metadata and does not inspect half-mutated targets; and
- if state is corrupt or unreadable, it returns a diagnostic snapshot rather than panicking.

The shared types live below the CLI layer. This lets either branch merge first without adding a duplicate `Commands::Status` variant, output schema, or lock implementation. A compatibility test invokes status before, during, and after uninstall to prove both commands coexist.

### Generated outer guards

The outer shell guard has one job: an absent binary must produce exit code 0 and no output. Scope-aware permit or tombstone preflight remains inside the binary.

Machine-local global registrations record the absolute resolved `cargo-agents` path at registration time and try it first. If that path is absent, they fall back to `PATH`. A committed project registration cannot contain another user's absolute path, so its portable template tries the Cargo home convention and then `PATH`.

The fixtures below are the exact single-line command values before the host's JSON, TOML, or YAML serializer escapes them. The versioned POSIX machine-local global template is:

```sh
if [ -x <ABSOLUTE_PATH_POSIX_LITERAL> ]; then exec <ABSOLUTE_PATH_POSIX_LITERAL> hook <AGENT> <EVENT> --managed-id <UUID>; elif command -v cargo-agents >/dev/null 2>&1; then exec cargo-agents hook <AGENT> <EVENT> --managed-id <UUID>; else exit 0; fi
```

The versioned portable POSIX project template is:

```sh
if [ -x "${CARGO_HOME:-$HOME/.cargo}/bin/cargo-agents" ]; then exec "${CARGO_HOME:-$HOME/.cargo}/bin/cargo-agents" hook <AGENT> <EVENT> --managed-id <UUID>; elif command -v cargo-agents >/dev/null 2>&1; then exec cargo-agents hook <AGENT> <EVENT> --managed-id <UUID>; else exit 0; fi
```

The versioned PowerShell machine-local global template is:

```powershell
$symposiumBin = <ABSOLUTE_PATH_POWERSHELL_LITERAL>; if (-not (Test-Path -LiteralPath $symposiumBin -PathType Leaf)) { $symposiumCommand = Get-Command cargo-agents -CommandType Application -ErrorAction SilentlyContinue; if ($null -eq $symposiumCommand) { exit 0 }; $symposiumBin = $symposiumCommand.Source }; $global:LASTEXITCODE = $null; & $symposiumBin hook <AGENT> <EVENT> --managed-id <UUID>; if ($null -eq $LASTEXITCODE) { exit 1 }; exit $LASTEXITCODE
```

The versioned portable PowerShell project template is:

```powershell
$cargoHome = $env:CARGO_HOME; if ([string]::IsNullOrWhiteSpace($cargoHome)) { $cargoHome = Join-Path $HOME '.cargo' }; $symposiumBin = Join-Path $cargoHome 'bin/cargo-agents.exe'; if (-not (Test-Path -LiteralPath $symposiumBin -PathType Leaf)) { $symposiumCommand = Get-Command cargo-agents -CommandType Application -ErrorAction SilentlyContinue; if ($null -eq $symposiumCommand) { exit 0 }; $symposiumBin = $symposiumCommand.Source }; $global:LASTEXITCODE = $null; & $symposiumBin hook <AGENT> <EVENT> --managed-id <UUID>; if ($null -eq $LASTEXITCODE) { exit 1 }; exit $LASTEXITCODE
```

The POSIX literal encoder wraps the path in single quotes and replaces each embedded apostrophe with the shell sequence `'\''`. The PowerShell literal encoder wraps the path in single quotes and doubles every embedded apostrophe. The placeholders above are already-encoded literals, never raw paths.

Copilot publishes and tests both shell forms. Adapter fixtures are versioned as part of the static signature catalog. Fixtures assert the decoded one-line command value and the exact raw host serialization. Every fixture test also asserts:

- absent absolute candidate and stripped `PATH` produce exit 0 and empty output;
- absolute paths are encoded with the adapter's shell-literal encoder rather than raw placeholder substitution;
- paths containing spaces, apostrophes, quotes, and shell metacharacters are quoted correctly;
- a present but unlaunchable executable produces a nonzero result even when `LASTEXITCODE` was previously unset or zero;
- a present binary receives the event, payload, managed ID, and working directory unchanged; and
- the binary's real nonzero status propagates.

### Command surface

```text
cargo agents uninstall [--dry-run] [--include-tracked]
                       [--acknowledge <BLOCKER-ID>]...
                       [--quiet] [--json]
```

`--dry-run` performs the same bounded discovery, path validation, scope normalization, Git classification, and ownership verification as a real run. It writes nothing, creates no tombstone, and deletes nothing. Its output says what would be removed, preserved, acknowledged, or blocked. A dry run with blockers exits 3; an operationally unreliable preview exits 1.

`--include-tracked` permits structural removal from tracked project configuration after ordinary identity checks. It never permits whole-file deletion or weakens ownership checks.

`--acknowledge <BLOCKER-ID>` is an evidence-preserving transfer of responsibility, not a force delete. It records that the user accepts the reported artifact as user-owned, retires Symposium's claim, preserves the artifact, and prints a redacted fragment for manual removal. A later installation treats the occupied location as a collision rather than reclaiming it.

Acknowledgement cannot produce a ready assessment while the preserved artifact contains an unguarded invocation of `cargo-agents`, or is an MCP server that directly launches it. Such a live binary reference must be removed manually or with `--include-tracked`; otherwise deleting the binary would recreate the original failure.

Exit codes are:


| Code | Meaning                                                                                   |
| ---- | ----------------------------------------------------------------------------------------- |
| 0    | Planning or cleanup completed with no live blockers in the applicable assessment boundary |
| 1    | Operational failure prevented a reliable plan or verification                             |
| 2    | Command-line usage error, retaining Clap's conventional exit code                         |
| 3    | Preview or cleanup completed, but one or more live blockers remain                        |


`--quiet` suppresses progress but not errors or the final assessment. The existing global `--json` option emits one versioned document on stdout; diagnostics remain on stderr.

### Bounded discovery

Uninstall never crawls the user's home directory or disks. It examines only:

1. known global configuration targets for supported adapters;
2. the current workspace when one is explicitly available;
3. roots named by ownership receipts;
4. targets or roots named by project permits, notice records, or retirement tombstones;
5. legacy workspace-state files that already contain a root; and
6. fixed Symposium-private directories.

Legacy coverage is qualified. Today `WorkspaceState::workspace_root` is written by hook-triggered auto-sync, not by every manual `cargo agents sync`. Historical state therefore improves discovery but is not a complete inventory. The command reports this limitation when pre-receipt versions may have created unrecorded project integrations.

Deleted, moved, or renamed roots cost only a failed bounded lookup. An existing root at a new path becomes a separate scope after `cargo agents sync`. Confirmed-absent records are pruned only during successful finalization.

### Cleanup algorithm

The real command follows this order:

1. Acquire the exclusive uninstall barrier described below.
2. Load receipts, project permits, global tombstones, notice and acknowledgement records, the signature catalog, and bounded legacy roots.
3. Discover candidate artifacts without mutating them.
4. Classify every candidate as removable, already absent, preserved, acknowledged, conflicting, or operationally unverifiable.
5. Build and print the complete plan.
6. For each removable external artifact, perform one ordered transaction: mark only that receipt `retiring`, retire its project permit or create its global tombstone; re-read and revalidate the target under its target lock; perform the narrow removal; verify absence; then retain the receipt with its completed disposition.
7. If any blocker or operational failure remains, retain all discovery-bearing workspace state, receipts, project permits, global tombstones, notices, caches, logs, and telemetry needed for repair or a rerun.
8. Only when every external integration is absent or validly acknowledged, finalize Symposium-private cache, workspace state, telemetry, and logs.
9. Verify private finalization and recompute the assessment.
10. Delete completed receipts, project permits, global tombstones, notice records, acknowledgements, and the now-empty managed-state directory.
11. Release locks and print the result.

A failure before external mutation restores that artifact to `applied` when its registration still matches, republishing a project permit or deleting a global tombstone as appropriate. A crash after retirement leaves only that artifact inactive and repairable. Successful removals are not rolled back. `cargo agents sync` restores a still-applied retiring registration; rerunning uninstall resumes removal.

`--dry-run` executes steps 2 through 5 and the same read-only classification used by verification. It takes the installation barrier in shared mode, the managed-state lock in shared mode, and sorted shared locks for every discovered target. It writes no recovery state and performs no finalization.

Within an external configuration file, cleanup normally uses read, parse, validate, edit only the owned structure, write a sibling temporary file, flush, atomically replace, reopen, and verify. Goose YAML uses the verified marker-delimited block editor described above and never reserializes the surrounding file. If a file changes between read and replacement, the operation replans that target rather than overwriting the concurrent edit.

Transient filesystem failures receive one initial attempt and at most two bounded retries. Each retry reopens and revalidates the target. Permission failures, ownership conflicts, indeterminate Git state, unsafe links, and content changes are blockers rather than retry loops.

### Concurrency and locks

One installation-wide mutex would put routine hook auto-sync behind a long uninstall. Instead, managed mutation uses:

- a shared/exclusive installation barrier;
- a shared/exclusive managed-state lock;
- a shared/exclusive global-target lock for shared agent configuration; and
- one shared/exclusive target lock per normalized workspace root.

Manual init, sync, and repair take the installation barrier in shared mode, then the managed-state and target locks they modify in exclusive mode. Dry-run takes the barrier, managed-state lock, and discovered target locks in shared mode, which prevents it from observing a target mid-mutation. Uninstall takes the installation barrier exclusively for the whole plan-mutate-verify interval, then takes the managed-state and target locks it mutates exclusively.

Hook-triggered auto-sync uses a non-blocking try-lock. On contention it skips that cache refresh and allows the hook to continue from already-published state; auto-sync is not a correctness prerequisite.

The complete order is installation barrier, managed-state lock, global-target lock when needed, then workspace-target locks sorted by normalized path. A dry-run that discovers a target set, acquires those read locks, and then sees a changed managed-state generation retries the snapshot once; a second change is an operational failure rather than an inconsistent preview.

Lock metadata contains a version, operation, process identifier, and start time for diagnostics. Liveness, not age alone, determines whether a lock is stale. Platform implementations use native advisory locking and are covered by multi-process tests.

### Filesystem safety

Receipts are untrusted input even though Symposium wrote them. Before mutation, cleanup validates:

- supported schema version and artifact kind;
- strict UUID and enum forms;
- normalized containment below an allowlisted adapter or Symposium-private root;
- expected file-versus-directory shape;
- component-wise ancestor relationships;
- link policy for the artifact type; and
- current identity evidence.

Cleanup refuses to traverse a symlink or junction while deleting a generated tree. If a managed path has been replaced by a link, it is preserved and reported. A generated directory is removed only when its manifest accounts for every remaining entry.

### Minimal startup and telemetry finalization

`uninstall` dispatches before ordinary startup. It may initialize only argument parsing, managed-state path resolution, minimal diagnostics, locking, the cleanup engine, and final reporting. It does not refresh registries, load plugins, run update checks, auto-sync, or initialize normal telemetry recording.

Telemetry finalization uses the telemetry subsystem's supported coordination path. If telemetry cannot be finalized, cleanup retains discovery and recovery state and reports a blocker; it does not silently claim completion. The final uninstall result itself is not recorded as new telemetry.

### Reporting and binary-removal assessment

Human output groups:

- `Removed`: artifacts verified absent during this run;
- `Already absent`: recorded artifacts already gone;
- `Preserved`: user, shared, tracked, unsupported, or ambiguous state left untouched;
- `Acknowledged`: artifacts whose ownership the user explicitly accepted;
- `Blocked`: live references or failures that prevent the stated assessment; and
- `Next steps`: exact commands or redacted manual edits.

The assessment is an enum:


| Value                    | Meaning                                                                                                                       |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| `ready`                  | No live Symposium integration remains in every recorded and inspectable scope, and no historical-discovery limitation applies |
| `ready-for-known-scopes` | No live integration remains in known scopes, but pre-receipt project scopes may be unrecorded                                 |
| `blocked`                | At least one live binary reference, ownership conflict, or operational verification failure remains                           |


`ready` is decided from a durable coverage-origin field created by the first receipt-aware release. Before ordinary startup overwrites `state.toml.version`, migration reads that previous semver and records exactly one of:

- `managed-only`: the configuration and managed store are first created by a receipt-aware release and initial bounded discovery finds no existing Symposium integration signature or legacy state;
- `pre-receipt`: the previous version predates receipts or initial discovery finds an exact legacy artifact; or
- `unknown`: provenance is missing or corrupt for a nonempty existing configuration, or an integration signature exists without its expected receipt-aware provenance.

The origin is never promoted automatically. Only `managed-only` can produce `ready`; `pre-receipt` and `unknown` produce at best `ready-for-known-scopes`. The existing last-touched version stamp is useful only at first migration because later startup replaces it.

The corresponding human lines are:

```text
No remaining live Symposium integrations in recorded scopes.
```

or:

```text
No remaining Symposium integrations in known scopes.
Older unrecorded project integrations may still exist; see the preserved items above.
```

The RFD intentionally avoids “It is safe to remove the Symposium binary,” because uninstall cannot prove the absence of an unknown pre-receipt checkout.

JSON output contains:

```text
schema_version
mode
binary_removal_assessment
actions
preserved
acknowledgements
blockers
next_steps
```

Every item includes a stable kind, adapter, scope, target, structural locator where applicable, disposition, reason code, and whether it remains a live reference. Secret-bearing fields are redacted. The old boolean `safe_to_remove_binary` is not part of the schema.

### Performance and cost

The hook preflight performs no directory-wide scan, network access, registry refresh, plugin loading, Cargo metadata query, or subprocess. It reads one directly addressed project permit or checks one global tombstone path, normalizes the process working directory, and performs depth-bounded reads and signature checks of candidate adapter configurations to find the nearest registration-owning root.

Guarded hooks may become the default only while p95 **added** preflight latency is no more than `max(2 ms, 5% of baseline hook-dispatch latency)`. The baseline is the same generated outer guard and no managed-state preflight on the same host and local filesystem. CI records p50 and p95 for active, inactive, missing-store, and nested-checkout cases on Linux, macOS, and Windows with small and large receipt stores. Store size must not change the number of hot-path reads or path probes.

The design adds these costs:


| Area                    | Cost and bound                                                                                                                                  |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Storage                 | One receipt per integration, one permit per active project registration, short-lived global tombstones, and bounded notice records              |
| Hook startup            | One direct state lookup, path normalization, and bounded adapter-configuration signature checks                                                  |
| Generated configuration | A one-line absent-binary guard and managed ID; scope is not trusted from command text                                                           |
| Project workflow        | One explicit `cargo agents sync` after a clone, move, or new container                                                                          |
| Implementation          | State schemas, identity adapters, Goose block editing, safe writers, lock hierarchy, recovery, catalog maintenance, and failure-injection tests |


Receipt growth is linear in recorded integrations and checkouts. Confirmed-absent records are removed at successful finalization. Long-lived receipts disclose normalized local project paths only to principals already able to read the private Symposium configuration directory. They are never telemetry or uploaded.

Maintaining the static signature catalog is an intentional compatibility cost: every change to a released generated static form adds a fixture rather than replacing old evidence. Dynamic plugin MCP instances do not grow that catalog; their non-secret fingerprints live in receipts.

### Test strategy

The feature extends the existing deterministic integration harness; it does not wait for or require the separate agent-interaction test redesign.

Unit and property tests cover:

- schema evolution, unknown versions, corrupt and truncated state;
- path normalization across macOS aliases, Windows verbatim prefixes and case behavior;
- traversal, symlink, junction, and manifest attacks;
- receipt lifecycle and crash points;
- exact current and historical signatures;
- dynamic fingerprints with secret fields excluded; and
- assessment and exit-code mapping.

Adapter contract fixtures cover every supported global and project representation, both Copilot shell forms, exact one-line host serialization, absent binaries, stripped `PATH`, apostrophes and shell metacharacters in paths, launch failures, real error propagation, and payload preservation.

Integration tests use isolated fake homes, Cargo homes, Git repositories, and workspaces. They cover:

- global and project init, sync, dry-run, uninstall, rerun, and repair;
- empty or unavailable stores that leave global hooks live, plus global retirement tombstones that disable them;
- clone, move, delete, multiple clones, unrelated nested adapter configuration, nested hostile checkouts, new container semantics, non-matching roots, and refusal of home or filesystem-root permits;
- one-time inactive SessionStart hints without plugin execution;
- tracked, untracked, read-only, externally modified, and concurrently rewritten settings;
- projects without a `.git` ancestor when Git is not installed, and repositories whose tracking query is unavailable;
- Goose marker-block removal with preserved surrounding comments and formatting;
- missing receipts, missing permits, corrupt stores, lost private state, and legacy signatures;
- managed-only, pre-receipt, and unknown coverage origins;
- interrupted cleanup at every lifecycle boundary;
- target-lock contention, shared dry-run snapshots, blocker exit code 3, and hook auto-sync try-lock behavior;
- status snapshots before, during, and after an exclusive uninstall;
- acknowledgement, finalization, structural collision on reinstall, and `--include-tracked`;
- locked telemetry and finalization failures; and
- the original stale-global-hook regression after binary removal.

Tests assert filesystem and parsed configuration state, retained recovery evidence, stdout, stderr, JSON schema, and exit status. Failure-injection runs prove that discovery state survives every non-final result.

### Documentation changes

The implementation updates:

- the command reference with the quit-clean-remove-restart workflow;
- init and sync output to explain that a cloned, moved, or containerized project needs local `cargo agents sync`;
- status documentation for inactive, retiring, corrupt, and unavailable permit states; and
- hook, state, module-structure, important-flow, and telemetry design chapters.

The proposed command reference is `[cargo agents uninstall](./proposed-cargo-agents-uninstall.md)`. The proposed ownership and activation model is [managed integrations](./proposed-managed-integrations.md).

## Frequently asked questions

### Why can Cargo not perform this cleanup?

Cargo tracks installed package binaries. Symposium's external effects live in agent configuration and workspace paths that Cargo neither owns nor understands. Symposium cleans its domain while its binary exists; Cargo then removes the package it owns.

### Why must users quit agents first?

Some agents cache settings and write them on exit. Cleaning while one is running creates a race in which the agent can resurrect a verified-absent entry after its receipt has been finalized. Quitting first removes that writer; starting only after Cargo removal reloads the final state.

### Does a copied managed ID activate a hostile clone?

Not for a project registration. Preflight finds the nearest adapter configuration that owns the invoked registration and requires its normalized root to equal the permit root exactly. A nested checkout therefore does not inherit its parent's permit. The payload's ID is never authority by itself. A global registration remains global, so this RFD makes no hostile-repository claim for global-hook users.

### What if the managed-state directory is deleted?

Project hooks become inactive because their positive permits are gone. Global hooks continue to run because only a positive retirement tombstone disables them; this avoids silently breaking the recommended global workflow after an empty store is recreated. Global startup records degraded health when possible. The next explicit sync can reconstruct static state from exact released signatures; a dynamic entry whose receipt was lost remains preserved because resemblance is not proof.

### Why may an inactive SessionStart say anything?

If the whole hook returned silently, the very SessionStart that once auto-synced a fresh checkout could never explain how to activate it. The inactive branch emits only static context naming `cargo agents sync`; it cannot load workspace plugins or execute their code. A per-root notice record suppresses the hint after it has been shown once.

### Why do legacy hooks run unguarded?

They run unguarded today. Verifying their on-disk project registration on every event would require locating the project and add a new failure mode. Exact historical signatures are instead used during bounded migration and cleanup.

### What if receipts are lost?

Released static signatures still identify current and historical static hook forms at known locations. Dynamic plugin MCP entries are preserved without their receipt because Symposium cannot reconstruct arbitrary instance identity safely. Deleting private state before uninstall therefore reduces discovery, but it does not authorize guesses.

### Why are both receipts and signatures needed?

Receipts make discovery bounded, especially for projects that no longer exist. Signatures or dynamic fingerprints prove that the current structure is still the artifact Symposium wrote. Neither role substitutes safely for the other.

### What happens after a project moves?

The old permit does not match the new root, so plugin dispatch is inactive. SessionStart explains the one-time `cargo agents sync`. Sync records the new normalized root and permit; stale roots remain cheap receipt entries until reconciled or successfully finalized.

### Why are containers separate permit environments?

The container can have a different user, configuration home, executable, and path view. Treating a host path as equivalent to a container path would make scope matching ambiguous. Local sync is explicit and cheap.

### Can a partial uninstall disable a working installation?

Only the artifact currently being removed is retired. A project permit is retired or a global tombstone is created immediately before that artifact's mutation. If mutation fails, its matching receipt remains repairable and `cargo agents sync` restores it. Other registrations remain active. Status names the repair command.

### Why is there no `--force`?

A force that bypasses identity checks would permit deletion of another program's state. `--acknowledge` instead gives every resolvable blocker a terminating path: preserve it, transfer ownership explicitly, and show the exact manual edit. Live unguarded binary references still block removal because preserving them would reproduce the bug this command exists to prevent.

### Why preserve tracked project files by default?

A developer may not intend to change configuration committed for the whole team. Default preservation makes that repository-level effect visible. `--include-tracked` is the explicit authorization to remove only the proven Symposium structure.

### Why preserve shared tools?

A tool in Cargo's binary directory may be used independently or by another program. Symposium removes its integrations and reports the tool, but only private copies below Symposium's own cache are exclusively owned.

### What happens to arbitrary installation scripts?

Legacy `install_commands` may create effects outside declared boundaries. Uninstall does not replay guessed inverse commands or execute content from a receipt. Known effects are reported as preserved; a future design may add declarative, receipt-backed actions for managed links or copies.

### Are receipts a security risk?

They add a parser and local state store, so they are validated as untrusted data. Receipts are versioned, minimal, non-executable, secret-free, atomically written, privately permissioned, and constrained by allowlisted roots and artifact-specific proof. A forged receipt alone cannot authorize deletion or project execution.

### Will every future hook, skill, or MCP feature need cleanup code?

Not when it uses an existing managed artifact type. The central mutation layer injects IDs, receipts, signatures or fingerprints, and lifecycle behavior. A new kind of external side effect needs an adapter because its deletion proof is genuinely new.

### What assessment should automation trust?

Automation should inspect `binary_removal_assessment` and the exit status. `ready` covers recorded and inspectable scopes, `ready-for-known-scopes` preserves the pre-receipt limitation, and `blocked` means a live reference or unverifiable operation remains. None claims knowledge of an undiscoverable checkout.

## Implementation plan

1. **Identity and path primitives.** Define normalized paths, managed IDs, trusted scope classification, exact registration-owning roots, stable blocker-ID derivation, static signatures, dynamic fingerprints, and assessment types. Test platform aliases, case behavior, links, nested checkouts, forbidden roots, acknowledgement invalidation, and every current and historical static registration.
2. **Durable state and lock hierarchy.** Add versioned receipt, project-permit, global-tombstone, notice, coverage-origin, health, and acknowledgement schemas; the read-only managed-health snapshot API; lifecycle recovery; atomic storage; the shared/exclusive installation barrier; managed-state and target locks; and crash/concurrency tests.
3. **Route managed writers.** Refactor hook, MCP, skill, generated-file, cache, and workspace-state writes through the central layer without changing behavior. Implement Goose's marker-delimited YAML block editor. Add structural adapter collisions, post-acknowledgement reinstall collisions, tracked-file classification, pending/applied recovery, formatting preservation, and secret-redaction tests.
4. **Guards and preflight.** Publish exact one-line serialized shell fixtures, record machine-local executable paths, implement positive project permits, positive global retirement tombstones, and bounded signature-based degraded classification, resolve exact registration-owning roots, add one-time inactive SessionStart context, migrate exact legacy signatures on sync, and enforce the numeric latency budget.
5. **Planner, command, and reporting.** Add bounded discovery, shared-lock dry-run, `--include-tracked`, stable acknowledgement, human grouping, versioned JSON through the existing global `--json`, decidable coverage assessments, distinct preview/apply exit codes, and minimal startup.
6. **Ordered cleanup and finalization.** Implement per-artifact project retirement or global tombstone creation, type-specific structural or Goose block mutation, two bounded retries, verification, repair through sync, blocker evidence retention, telemetry coordination, and private-state finalization last.
7. **Status, adapter, platform, and documentation completion.** Connect the shared health snapshot to the existing status command without duplicating its CLI or presentation layer. Exercise status/uninstall concurrency and global and project scope for every supported adapter on Linux, macOS, and Windows, including stripped `PATH`, tracked repositories, interruption, concurrent agents, and the stale-hook regression. For every adapter that supports project-scoped registrations, verify that hooks launched from both the checkout root and nested directories receive a working directory inside that checkout; an adapter that cannot establish this contract must not offer project-scoped guarded registrations. Update the user and design documentation named above.

Each step is independently reviewable and includes tests. The work extends the current deterministic integration harness and does not require rewriting it.

## Implementation status

This RFD describes proposed behavior. Implementation has not begun.
