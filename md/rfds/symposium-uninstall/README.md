# Managed Symposium uninstall

## TL;DR

- Add `cargo agents uninstall` as a non-interactive, idempotent cleanup command that runs before `cargo uninstall symposium`.
- Remove every integration and private artifact that Symposium can prove it manages across known global and workspace scopes.
- Preserve user-authored configuration, custom plugin sources, shared tools, external integrations, and anything whose ownership is ambiguous.
- Record managed writes in durable, versioned ownership receipts and give hook registrations stable IDs.
- Make generated hook commands harmless when either their local activation permit or the `cargo-agents` binary is absent.
- Discover recorded workspaces instead of scanning the user's filesystem.
- Report every removed, preserved, and blocked item, and only declare it safe to remove the binary after cleanup has no blockers.

## Motivation

`cargo uninstall symposium` knows which package binaries Cargo installed. It does not know that Symposium also wrote hook registrations, MCP server entries, generated skills, cache data, or workspace state.

Today an unguarded hook registration can survive removal of the `cargo-agents` binary. Every later hook event then asks the shell to run a command that no longer exists. The user sees errors such as:

```text
/usr/bin/bash: line 1: cargo-agents: command not found
PostToolUse:Bash hook error
```

This can affect every project when the surviving registration is global. Project-scoped installation creates a second problem: cleanup cannot find every workspace by scanning an unknown number of directories, and it must not guess which similar-looking entries belong to Symposium.

The cleanup contract therefore needs more than a list of paths. Symposium needs durable evidence of what it created, a bounded way to find project scopes later, and hook registrations that fail closed when local ownership state or the binary disappears.

## Change in a nutshell

Introduce a central managed-mutation layer. Agent adapters and other subsystems use this layer whenever they add, update, or remove external state. The layer assigns a stable managed ID, validates that the target is safe to modify, performs the mutation atomically, and stores a durable ownership receipt.

Hook registrations also receive a small derived activation permit. The adapter-generated command performs two checks before ordinary hook startup:

1. an outer, adapter-specific guard exits successfully if `cargo-agents` is not installed; and
2. `cargo-agents hook --managed-id <UUID> ...` performs a direct permit lookup and quietly exits if this checkout is not locally activated.

`cargo agents uninstall` uses receipts, exact legacy signatures, and a bounded set of known locations to build a cleanup plan. It removes only artifacts for which the applicable ownership check succeeds. It preserves and reports anything external or ambiguous.

The intended user workflow is:

```console
$ cargo agents uninstall
# restart any running coding agents
$ cargo uninstall symposium
```

The command cannot safely restart the parent coding agent that may be hosting the terminal. It prints that step after successful cleanup instead of attempting to terminate or replace another process.

## Detailed plans

### Terminology

This RFD uses three related terms:

- A **managed ID** is a non-secret UUID assigned to one logical Symposium integration. It remains stable while that integration is updated.
- An **ownership receipt** is the authoritative durable record of the artifacts written for that managed ID and the evidence needed to verify them later.
- An **activation permit** is a tiny, derived hot-path record that says where a hook registration is locally allowed to run. It is the concrete record for the receipt-backed lease and is not sufficient evidence for deletion.

The receipt answers “may Symposium modify or remove this artifact?” The permit answers “may this hook run in this checkout?” Keeping those questions separate lets uninstall remain conservative without making every hook invocation parse the full ownership store.

### Command contract

`cargo agents uninstall` cleans all known scopes in one operation. It has no initial `--global`, `--project`, or `--force` mode. Selective cleanup would make a successful result too easy to misread as permission to remove the binary while active integrations remain elsewhere.

The command is:

- non-interactive by default;
- safe to rerun after success or partial failure;
- best-effort across independent artifacts;
- strict about its final result; and
- usable both inside and outside a Cargo workspace.

One failure does not prevent cleanup of unrelated artifacts. The command aggregates blockers and exits unsuccessfully if any managed item could not be removed or safely classified. A successful exit means all discovered managed artifacts are removed or already absent. The verdict cannot prove the absence of an unrecorded pre-receipt project file; when pre-receipt state is detected, the report includes that transition limitation and the sync guidance separately from the successful known-scope verdict.

The global `--quiet` and `--json` options apply. The subcommand adds `--dry-run`.

### Discovery boundaries

Cleanup examines a bounded set of locations:

1. the active resolved Symposium configuration directory;
2. every supported agent's known global configuration locations;
3. the current workspace, when the command is run inside one;
4. every workspace root named by a valid ownership receipt; and
5. exact historical Symposium cache, state, and registration locations needed for legacy cleanup.

It does not scan home directories, mounted volumes, Git repositories, or the full filesystem for strings resembling Symposium commands.

All supported global adapters are inspected, even when an agent is no longer present in `config.toml`. This is necessary because removing an agent from current configuration does not prove that an older registration disappeared.

A moved or renamed workspace becomes known again when the user runs `cargo agents sync` from its new root. If an old receipt points to a path that no longer exists, uninstall treats that artifact as absent and retires the stale receipt. A checkout whose registration was written or migrated under this design still has the outer binary guard when its recorded location becomes unreachable, so it remains quiet after binary removal.

Legacy workspace-state files already contain workspace roots and are another exact discovery source during the transition. One unavoidable gap remains: a pre-receipt project hook that is neither in the current workspace nor recoverable from historical workspace state cannot be found automatically. Active legacy hooks migrate when they next invoke the installed binary, and users upgrading from a pre-receipt version are told to run sync in known project-scoped checkouts before removal. Uninstall reports the limited legacy coverage when it detects pre-receipt state; it does not hide the limitation behind a filesystem scan.

One invocation operates on the currently resolved Symposium configuration home. Enumerating multiple historical homes selected by different environment overrides is outside this RFD.

### Removal and preservation rules

The cleanup boundary is based on ownership, not on whether a path or command contains the word `symposium`.

| Artifact | Cleanup behavior | Ownership evidence |
|---|---|---|
| Hook registration | Remove the owned structural entry or dedicated file | Managed ID plus adapter-specific command identity; exact historical signature for legacy entries |
| MCP registration | Remove the owned structural entry | Managed key/ID plus command identity where the host schema permits it |
| Generated skill or mirror | Remove only the generated directory or file | Marker and manifest tied to a receipt |
| Dedicated generated file | Remove the file | Marker or content identity tied to a receipt |
| Symposium-private cache, logs, telemetry data, and state | Remove within its fixed private boundary | Known root plus receipt or exact built-in layout |
| `config.toml` | Preserve | User-owned configuration |
| Custom plugin source | Preserve | User-authored or user-selected source |
| User or third-party entry near a managed entry | Preserve | No valid Symposium ownership evidence |
| Cargo-installed shared tool | Preserve and report as external | Shared package-manager location, not exclusive Symposium ownership |
| Side effect of an arbitrary `install_commands` script | Preserve and report when known | Effect cannot be reconstructed safely |
| Unknown pre-receipt project checkout | Cannot discover automatically; report the transition limitation | No stored workspace root to inspect |

Preserving `config.toml` also preserves the user's telemetry preference and plugin declarations. Removing their derived hook, MCP, and skill integrations ensures they no longer affect the user's agents. A later Symposium installation can reuse the preferences after an explicit sync.

If the user edits an artifact but its stable identity and adapter-specific invariants still establish Symposium ownership, cleanup removes it. If another program has replaced the entry, the key is occupied by different content, or the evidence is otherwise ambiguous, cleanup preserves it and reports a conflict.

### Managed mutation layer

Managed writes go through one internal interface rather than letting adapters edit external state independently. A mutation declares:

- artifact kind and adapter;
- global or workspace scope;
- logical configuration path and structural locator;
- stable managed ID;
- expected prior ownership state; and
- type-specific evidence for later verification.

The layer owns collision checks, receipt transitions, safe path handling, atomic writes, and reporting. Low-level config writers remain private to it or require an explicit managed/unmanaged classification. Tests enforce that adapter registration paths do not bypass this boundary.

This makes new skills, MCP registrations, hooks, and generated files participate automatically when they use an existing managed artifact type. A genuinely new side-effect type still needs one ownership adapter defining how it is created, verified, and removed. That definition is made once in the managed layer rather than reimplemented in init, sync, and uninstall.

Registration never overwrites an occupied external key. Updates mutate only an entry whose previous ownership can be verified. The system does not create arbitrary backups of user configuration as a substitute for proving ownership.

### Receipt storage and lifecycle

Receipts live outside disposable caches beneath the resolved configuration directory, for example:

```text
managed/
  receipts/<managed-id>.json
  permits/<managed-id>.json
```

The exact on-disk representation is an implementation detail, but it is versioned and independently readable. A receipt stores only the data needed for safe discovery and ownership verification:

- schema version and managed ID;
- artifact kind, adapter, and scope;
- logical configuration path and recorded target identity;
- structural locator or generated-file manifest;
- ownership evidence; and
- lifecycle state.

It does not store whole agent configuration files, plugin source contents, environment values, tokens, arbitrary commands, or command output.

Receipts have three lifecycle states:

- `pending`: published before an external write starts;
- `applied`: the managed artifact was successfully installed; and
- `retiring`: execution has been disabled and removal is in progress.

Installation writes `pending`, performs and verifies the external mutation, then transitions to `applied`. Cleanup transitions to `retiring`, disables any permit, removes and verifies the artifact, then deletes the receipt. A crash can therefore be resumed without assuming that the previous operation completed.

Receipts do not expire by age. Long-lived records are small, and age does not prove that an integration is abandoned. Sync refreshes current workspace information; uninstall retires receipts whose targets are confirmed absent.

### Stable hook IDs and activation permits

An adapter generates the managed ID when it creates a logical hook registration. All event entries belonging to that registration may share the ID. The ID is embedded only in the Symposium command arguments or in a host schema's supported metadata. It does not change the hook event or plugin payload seen by the agent.

The activation permit is indexed directly by managed ID. It contains the valid global state or a small set of locally activated workspace roots. It is written only after the corresponding receipt and hook registration are applied. Project sync adds the current root; uninstall retires the permit before touching the registration.

The hook path performs no directory scan, network access, registry refresh, plugin loading, or Cargo metadata query before permit validation. Its decision is:

- valid applied permit for this scope: continue with ordinary hook startup;
- missing, corrupt, or retiring permit: exit successfully without output; or
- structurally invalid managed ID or unsafe permit data: emit a bounded diagnostic and perform no writes.

Receipts remain authoritative. If the derived permit is lost or corrupt, `cargo agents sync` rebuilds it from verified local state.

### Adapter-specific guarded commands

The outer guard is generated by the agent adapter because host schemas represent shell commands differently.

| Adapter | Managed representation |
|---|---|
| Claude, Gemini, Codex | Owned command entries inside their nested configuration structures |
| GitHub Copilot | Separate Bash and PowerShell command forms in global config or the dedicated project hook file |
| Kiro | A dedicated Symposium agent definition file containing its hook commands |
| Goose, OpenCode | No shell-hook registration; their managed skills and MCP state still use the cleanup system |

Every generated form follows the same semantic contract:

1. check for `cargo-agents` using the adapter's actual shell;
2. return status zero with no output if it is absent;
3. invoke `cargo-agents hook --managed-id <UUID> ...` if present; and
4. preserve the real command's stdout, stderr, and exit status.

The guard must not turn an installed but failing Symposium hook into success. Command templates are static, managed IDs are validated UUIDs, and adapters apply platform-appropriate quoting. Receipt text is never interpolated into a shell command.

Some project hook formats are inherently platform-specific. A checked-in hook copied to an incompatible operating system after Symposium has already been removed may not be executable by that host. Cross-platform translation of an unreachable stale configuration is outside this RFD; newly synced checkouts receive the correct adapter form.

### Project checkout activation

Today a copied project registration can become active as soon as the agent trusts and opens the checkout. Under this RFD, a project hook is inactive unless its managed ID has a permit for that local workspace root.

After cloning, copying, or moving a project with a checked-in hook registration, the user runs:

```console
$ cargo agents sync
```

Sync verifies or adopts the managed registration, records the new root, and publishes its permit. Global hooks are already locally permitted and do not need per-project activation.

`cargo agents status` reports a present but inactive project hook and says to run `cargo agents sync`. The hook itself remains silent. Init, sync, installation, configuration, and per-agent documentation must explain the per-checkout activation rule.

A managed ID is non-secret and can safely travel in a committed project configuration. Copying it grants no authority because the receiving machine has neither a matching receipt nor a local activation permit. Multiple local clones may share an ID; each root has an independent permit entry.

### Legacy adoption and cleanup

Older installations have no managed IDs or receipts. The migration policy is conservative:

- ordinary init or sync adopts only an exact historical Symposium registration and rewrites it to the guarded, ID-bearing form;
- a legacy hook invocation without an ID may run only after verifying its exact on-disk historical registration;
- uninstall can remove an exact historical fragment directly, even if no migration occurred; and
- prefix matches, similar commands, malformed structures, and partially edited entries are preserved and reported.

Exact historical signatures are versioned test fixtures, not broad substring searches. This prevents a third-party hook that also invokes Cargo or uses a similar key from being mistaken for Symposium state.

### Cleanup algorithm

Apply mode performs these phases while holding the installation-wide mutation lock:

1. Load and validate receipts and the exact legacy signature catalog.
2. Discover known global and workspace locations.
3. Read each target and classify it as owned, already absent, external, or blocked.
4. Build and report a deterministic plan.
5. Mark owned hook receipts and permits as retiring so cached registrations become inert.
6. Remove owned structural fragments and generated artifacts, rechecking ownership immediately before each write.
7. Remove private caches, logs, telemetry events and identifiers, and obsolete workspace state.
8. Verify results, retire successful or absent receipts, and aggregate blockers.

Configuration entries are removed structurally. Shared JSON, JSONC, TOML, or other host configuration files are never deleted just because Symposium owned one nested entry.

`--dry-run` performs the same discovery, parsing, classification, and ownership verification under the same operation lock, but makes no persistent writes. It prints `Would remove` instead of `Removed`. It exits unsuccessfully when apply mode would encounter a blocker, so automation can use it as a preflight rather than treating it as an alternative cleanup operation.

### Concurrency, retries, and crash recovery

Init, sync, managed status repair, and uninstall share one OS-backed lock for installation-wide mutation. Uninstall holds it through planning, mutation, and verification. Ordinary permit lookup on the hook hot path is lock-free. A persistent hook-side repair, if required, acquires the same lock and revalidates before writing.

Agent configuration remains writable by external programs. Every shared-config mutation therefore uses a conservative read-modify-recheck-atomic-replace sequence. A changed file or transient filesystem error is retried with short exponential backoff: one initial attempt and at most two retries. Parse errors, unsupported schemas, invalid receipts, ownership conflicts, and unsafe paths are not transient and are not retried.

Successful changes are not rolled back when another target fails. Rerunning the command observes removed artifacts as absent and resumes receipts left in `retiring`. This is safer than attempting a broad rollback that could overwrite concurrent user or agent changes.

### Filesystem and receipt safety

Receipt data is untrusted input. Cleanup validates schema versions, artifact kinds, path boundaries, structural locators, and managed IDs before acting. It never executes a command from a receipt, follows a receipt-provided arbitrary path, logs secret-bearing values, or requests elevated privileges.

Managed state is created with user-private permissions where the platform supports them. Cleanup affects only the current user's Symposium and agent configuration locations.

Symlinks and junctions use artifact-specific rules:

- A shared configuration file may be edited through a symlink only when the logical path is a known agent configuration path and it still resolves to the same target identity recorded at registration.
- Atomic replacement updates the resolved configuration target without replacing the symlink itself.
- A changed target is preserved and reported as a conflict.
- Generated files and directories are never traversed through symlinks or junctions.
- A generated path that has been replaced by a link is preserved and reported.
- A generated directory is removed only when its manifest accounts for its contents; unknown contents prevent directory deletion.

### Minimal uninstall startup

The current binary initializes ordinary logging and state, refreshes registries, and may check for or install an update before dispatching most commands. `uninstall` must be selected before that startup path.

The uninstall path may parse the CLI, resolve the active configuration directory, acquire its operation lock, and initialize cleanup-specific reporting. It must not:

- stamp ordinary `state.toml`;
- fetch or refresh plugin registries;
- auto-update or re-execute the binary;
- initialize normal telemetry recording; or
- emit an uninstall telemetry event.

Cleanup removes telemetry event and metric files, pending sets, local identifiers or cohort state, and telemetry-private locks or state. It preserves the telemetry preference in `config.toml`. A telemetry lock that remains busy after the retry budget is a blocker rather than permission to leave data behind silently.

### Human and machine output

Human output is an action audit, not a count-only summary. It groups entries by scope, then agent, then artifact kind:

```text
Removed
  Global
    Claude hooks
      ~/.claude/settings.json: Symposium hook entries
  Workspaces
    /work/example
      Codex skills
        .agents/skills/example-skill

Preserved
  ~/.symposium/config.toml: user configuration
  cargo-binstall: shared Cargo tool

Cleanup complete. It is safe to remove the Symposium binary.
Next: restart running coding agents, then run `cargo uninstall symposium`.
```

Partial failure uses `Not removed` for blockers, prints the reason and a rerun instruction, and says not to remove the binary yet. `--quiet` suppresses successful detail but still prints blockers and the final verdict.

`--json` writes one versioned document to stdout. Catastrophic diagnostics that prevent creating the document go to stderr. Its top-level fields are:

```text
schema_version
mode
outcome
safe_to_remove_binary
actions
preserved
blockers
next_step
```

`mode` is `apply` or `dry-run`; `outcome` is `ready`, `incomplete`, or `preview`. Each action carries a disposition, scope, adapter when applicable, artifact kind, safe display path, managed ID when available, and reason. Non-blocking legacy-coverage notices appear in `preserved` with a machine-readable reason. Counts may be derived by consumers; a count-only summary does not replace the action list.

### Performance contract

The receipt system is not on most command hot paths. Hook permit validation is the exception and has an explicit budget: steady-state p95 added latency must be no more than the larger of 2 ms or 5% of the existing hook startup baseline on the same machine.

Benchmarks cover p50 and p95 across supported operating systems and varying receipt counts. The hot path opens the permit file by managed ID and checks the current scope; its work does not grow with the total number of receipts.

### Cost and operational impact

The design adds costs in five places:

| Area | Cost and bound |
|---|---|
| Storage | One small receipt per logical managed integration plus a derived permit per hook ID. Growth is linear in recorded integrations and checkouts; no project contents are copied. Retired and confirmed-absent records are removed. |
| Hook startup | One direct permit-file lookup and scope comparison before ordinary startup, bounded by the latency contract above. |
| Generated configuration | Hook command strings gain a static binary-existence guard and `--managed-id <UUID>`. This is visible in agent configuration but does not change the event or payload delivered to hooks. |
| User workflow | A copied, cloned, or moved project-scoped registration needs one explicit `cargo agents sync` on that machine before it becomes active. |
| Implementation and maintenance | The first implementation adds a state machine, safe atomic writers, platform locking, adapter ownership checks, legacy migration, and failure-injection tests. Later features reuse existing artifact types automatically; only a genuinely new side-effect type needs new ownership logic. |

Receipts disclose local workspace paths to anyone who can already read the user's private Symposium configuration directory. Those paths are not telemetry, are never uploaded, and receive the same restrictive permissions as the rest of managed state.

### Documentation changes

Implementation updates:

- the installation guide with the staged removal workflow;
- the `uninstall`, `sync`, `status`, configuration, and global command references;
- every relevant agent page with its generated guard and project activation behavior;
- hook, state, module-structure, important-flow, and telemetry design chapters; and
- init and sync output to state that a copied or moved project needs one local sync.

The proposed user-facing command reference is [Proposed: `cargo agents uninstall`](./proposed-cargo-agents-uninstall.md). The ownership and checkout behavior is described in [Proposed: managed integrations](./proposed-managed-integrations.md).

## Frequently asked questions

### Why can Cargo not perform this cleanup?

Cargo tracks installed package binaries and removes those binaries. Symposium's external effects live in agent-specific configuration and workspace paths that Cargo neither owns nor understands. The staged workflow lets Symposium clean its domain while its binary still exists, then lets Cargo remove the package it owns.

### Why not make `cargo agents implode` remove the binary too?

A running process cannot portably remove its installed package, restart its parent coding agent, and still provide reliable recovery and diagnostics. Package removal also belongs to Cargo. Keeping the operations separate provides a clear checkpoint: cleanup succeeds, the user restarts agents, then Cargo removes the binary.

### Why keep durable state for years?

Workspace paths may be needed years later to remove registrations safely. Receipts are small metadata records, contain no project contents or secrets, and do not affect a project's build. They are refreshed when a workspace syncs and removed when uninstall confirms their targets are gone. Expiring them by age would discard the only ownership evidence without proving that an integration disappeared.

### What if a project was moved or deleted?

Sync from the new location records that location. During uninstall, a missing recorded path counts as already absent and its stale receipt is retired. A moved managed checkout that was never synced again cannot be discovered without an unsafe filesystem scan, but its guarded hook quietly exits after the binary is removed. A legacy unguarded checkout that was never recorded is the transition exception described under discovery boundaries; it must first be rediscovered or handled manually.

### Does the first managed release remove every project hook created by older releases?

It removes legacy hooks in global locations, the current workspace, and roots recoverable from historical workspace state. It cannot prove that an unrecorded checkout elsewhere on disk does not contain an old project hook. The report calls out this limited legacy coverage, and the upgrade documentation tells project-scope users to sync dormant checkouts they still use before removing Symposium. This is a transition limitation; registrations created or migrated under this design are recorded and guarded.

### What does `--dry-run` prove?

It proves what the command can determine at that moment: the known locations were discovered, current contents were parsed, ownership checks were applied, and blockers were identified. It does not clean anything or guarantee that an external program will not change a file afterward. Apply mode repeats the checks immediately before mutation.

### How are hooks from another program distinguished?

New registrations carry a stable managed ID and type-specific command identity tied to a receipt. Legacy cleanup requires an exact historical Symposium structure and command. A matching event name, key prefix, or reference to Cargo is not enough. Ambiguity is preserved as a conflict.

### Will every future feature need uninstall-specific code?

Not when it uses an existing managed artifact type. The central writer injects identity and receipts automatically. A new kind of external side effect needs one ownership adapter because safe deletion rules differ between a nested config entry, a generated directory, and a package-manager installation.

### Are receipts a new security risk?

They create a small new parser and state store, so they require defensive handling. The design bounds that cost: versioned minimal data, private permissions, no stored secrets, no executable receipt content, fixed path boundaries, stable UUID validation, atomic writes, and tests for traversal and link attacks. A forged receipt cannot authorize arbitrary deletion because type-specific verification and allowlisted roots are also required.

### Why preserve globally installed tools?

Tools installed into shared locations such as Cargo's binary directory may be used independently of Symposium or by another program. Symposium removes its integrations and reports those tools, but ownership is not exclusive enough to uninstall them. Private copies acquired into Symposium's cache are removed with that cache.

### What happens to arbitrary installation scripts?

Legacy `install_commands` can perform effects outside any declared boundary. Symposium does not run guessed uninstall commands or replay commands from receipts. Known untracked setup is reported as preserved and does not block binary removal after all live Symposium integrations are gone. A future RFD can add declarative, receipt-backed actions such as managed links or copies.

### Why is there no `--force`?

Forcing deletion through failed ownership checks would erase the safety property this command exists to provide. The first version reports the exact conflict so the user can resolve it or remove it manually. A later override would need a narrower, evidence-based contract.

### Can a partial failure leave the system worse?

Before removing hook configuration, uninstall retires its permit, making a surviving guarded command a quiet no-op. Successful removals remain complete, failed receipts remain resumable, and the command gives a nonzero result with an explicit warning not to remove the binary yet.

## Implementation plan

1. **Introduce managed-state primitives without changing generated integrations.** Add versioned receipt and permit schemas, lifecycle transitions, the installation-wide lock, safe-path validation, and atomic storage. Cover schema evolution, corrupt state, permissions, symlinks/junctions, traversal attempts, crash injection, and concurrent writers with unit and property tests.
2. **Route existing managed writes through the ownership layer.** Refactor hook, MCP, skill, generated-file, cache, and workspace-state mutations to declare their artifact type. Add collision behavior, exact legacy signatures, pending/applied recovery, and adapter contract tests. This step must preserve current user-visible behavior while beginning to publish receipts.
3. **Add guarded hooks and local activation permits.** Generate stable IDs and adapter-specific guards, add the minimal pre-startup permit lookup, teach sync to activate a checkout, and teach status to report inactive copied hooks. Test missing binaries, missing/corrupt/retiring permits, clones, moved roots, multiple clones, shell quoting, legacy migration, real error propagation, and the p50/p95 latency budget.
4. **Build the cleanup planner and engine.** Implement bounded discovery, ownership classification, structural removal, retries, partial progress, dry-run, receipt retirement, private-state cleanup, and telemetry-specific coordination. Test every removal/preservation row, absent paths, unknown contents, external modifications, locked files, interrupted cleanup, and idempotent reruns.
5. **Expose `cargo agents uninstall` through minimal startup and reporting.** Add CLI parsing, human grouping, `--quiet`, the versioned JSON document, exit semantics, and safe/unsafe next steps. Integration tests use isolated fake homes and workspaces and assert exact state as well as output.
6. **Complete platform integration and documentation.** Exercise global and project scope across all supported adapters on Linux, macOS, and Windows, including the original stale-global-hook regression. Update the user and design documentation listed above. These tests extend the existing deterministic integration harness and do not depend on replacing it with the separate agent-interaction suite.

Each step is independently reviewable and includes its tests. No implementation step requires a rewrite of the existing integration-test infrastructure.

## Implementation status

This RFD describes proposed behavior. Implementation has not begun.
