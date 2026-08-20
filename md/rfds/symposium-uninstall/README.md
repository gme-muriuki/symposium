# Managed Symposium uninstall

## TL;DR

- Add `cargo agents uninstall` to remove Symposium-managed integrations before `cargo uninstall symposium` removes the package.
- Ask users to quit running agents before cleanup and restart them after Cargo removes the binary.
- Record managed writes in durable receipts, then verify current identity before deleting anything.
- Make generated hooks harmless when `cargo-agents` is absent and coordinate hook retirement during cleanup.
- Preserve user-authored, shared, tracked, and ambiguous state by default.
- Report what was removed or preserved and qualify the final removal assessment.

## Motivation

`cargo uninstall symposium` removes the package binaries Cargo owns. It does not know that Symposium also wrote agent hooks, MCP entries, generated skills or plugin packages, caches, and workspace state.

An unguarded hook can therefore survive the binary:

```text
/usr/bin/bash: line 1: cargo-agents: command not found
PostToolUse:Bash hook error
```

A stale global hook produces this error in every project. Project-scoped cleanup has a different problem: Symposium cannot scan arbitrary disks to rediscover every workspace, and it must not delete a similar-looking entry that another program or the user owns.

The command needs bounded discovery, current ownership proof, safe hook retirement, and recovery from interrupted cleanup.

## As a user

The recommended workflow is:

1. Quit every agent process that may have loaded Symposium-managed configuration.
2. Run `cargo agents uninstall` from an ordinary terminal.
3. Resolve or acknowledge reported blockers and rerun until no live integration remains in the applicable scopes.
4. Run `cargo uninstall symposium`.
5. Restart the agents.

```console
$ cargo agents uninstall
Removed
  claude global hook
  codex project skills in /work/reporter

No remaining Symposium integrations in known scopes.
Next: cargo uninstall symposium
```

When cleanup cannot prove that an entry is still Symposium's, it preserves the entry:

```console
$ cargo agents uninstall --dry-run
Blocked
  .claude/settings.json
    hook differs from the released Symposium registration

No files changed.
```

Quitting agents first prevents one from rewriting an old in-memory settings file after cleanup. `cargo agents uninstall` does not remove its own package: a running process cannot do that portably, and Cargo already owns package removal.

See the proposed [command reference](./cargo-agents-uninstall/README.md) for flags, output, and recovery instructions.

## Change in a nutshell

All externally visible Symposium writes go through one managed-mutation layer.

1. Before a write, the layer records a receipt describing the artifact and target.
2. After writing, it records the adapter-specific signature, fingerprint, marker, or manifest needed to recognize the artifact later.
3. Uninstall uses the receipt to find the target and current identity evidence to decide whether it may remove it.
4. It retires and removes one external artifact at a time, retaining recovery evidence until all external work succeeds.
5. It removes Symposium-private state last and reports a qualified result.

Generated hook commands add a small outer guard so an absent binary exits successfully without output. Project hooks also require a local permit for the exact registration-owning root. Global hooks instead run unless uninstall has written a retirement tombstone for that registration.

## Safety contract

The design has these invariants:

- Symposium deletes external state only when bounded discovery evidence and current artifact-specific identity evidence agree.
- A managed ID correlates state; it is neither ownership proof nor permission by itself.
- User-authored configuration, custom plugin sources, shared tools, tracked project configuration, and ambiguous artifacts are preserved by default.
- Project-hook activation requires the managed ID and normalized registration-owning root to match one local permit exactly.
- Global tombstones coordinate cleanup; they do not protect global-hook users from hostile workspace configuration.
- Only the artifact being mutated is retired. Other integrations remain active.
- Discovery and repair state survives every blocked or interrupted run.
- Private caches, logs, telemetry, workspace state, and completed receipts are finalized only after external integrations are absent or explicitly transferred to the user.

This RFD does not scan the filesystem for unknown historical projects, reverse arbitrary plugin installation scripts, uninstall shared packages, delete custom plugin sources, or restart agent processes.

## Cleanup boundary

The boundary is based on ownership rather than names such as `symposium` or `cargo-agents`.

| Artifact family | Default behavior |
| --- | --- |
| Verified hook and MCP registrations | Remove only the owned structural entry or dedicated file |
| Verified generated skills, plugin packages, mirrors, and files | Remove managed content; remove a directory only when its manifest accounts for every entry |
| Symposium-private state | Remove during successful finalization |
| `config.toml` and custom or external plugin sources | Preserve |
| Tracked project configuration | Preserve unless `--include-tracked` authorizes removal of the verified structure |
| Shared tools and arbitrary installation-script effects | Preserve and report |
| Modified, unsupported, or ambiguous artifacts | Preserve and report a blocker when a live integration remains |
| Unknown pre-receipt project | Not automatically discoverable |

Reading an external plugin package never gives Symposium ownership of its source. A compiled or copied package, generated mirror, or registered path written by Symposium is a managed artifact and uses the same receipt-backed rules.

## Results and recovery

The command reports removed, already absent, preserved, acknowledged, and blocked items. Its final assessment is:

| Assessment | Meaning |
| --- | --- |
| `ready` | No live integration remains in recorded and inspectable scopes, and no historical-discovery limitation applies |
| `ready-for-known-scopes` | Known scopes are clean, but a pre-receipt project may be unrecorded |
| `blocked` | A live binary reference, ownership conflict, or operational verification failure remains |

The command does not say that binary removal is universally safe when it cannot know about an old unrecorded checkout.

Interrupted cleanup is resumable. Rerunning uninstall continues removal; `cargo agents sync` restores a still-applied integration left in a repairable retiring state. The existing `cargo agents status` command consumes the managed-state health snapshot and reports inactive, retiring, corrupt, unavailable, and cleanup-in-progress states.

## Detailed design

The technical contracts are split by responsibility:

- [Ownership and managed state](./ownership/README.md) explains receipts, signatures, fingerprints, lifecycle, collision handling, path safety, legacy evidence, and generated plugin packages.
- [Hook activation](./hook-activation/README.md) explains outer guards, project permits, global tombstones, root matching, degraded state, status integration, and the hook-path performance budget.
- [Cleanup engine](./cleanup-engine/README.md) explains command modes, bounded discovery, planning, mutation ordering, locks, retries, acknowledgements, finalization, reporting, and exit codes.

The proposed user documentation is:

- [`cargo agents uninstall`](./cargo-agents-uninstall/README.md)
- [Managed integrations](./managed-integrations/README.md)

## Frequently asked questions

### Why does Cargo not perform this cleanup?

Cargo tracks installed package binaries. Symposium's effects also live in agent configuration and workspace paths that Cargo neither owns nor understands. Symposium cleans its domain while the binary exists; Cargo then removes the package it owns.

### Why is there no `--force`?

A force that bypasses identity checks could delete another program's state. `--acknowledge` instead preserves the artifact, transfers responsibility to the user, and shows the exact manual action. A preserved unguarded reference to `cargo-agents` remains a blocker until it is removed.

## Implementation plan

### Step 1: Add ownership primitives

Add normalized paths, managed IDs, versioned receipts, signatures, fingerprints, lifecycle recovery, coverage origin, and artifact-specific identity adapters.

- [ ] PR: ownership and managed-state primitives, with schema, path, collision, legacy, and failure-injection tests

### Step 2: Route managed writers

Route hook, MCP, skill, generated-file, generated-plugin-package, cache, and workspace-state writes through the managed-mutation layer without changing their behavior.

- [ ] PR: central managed writers, Goose block editing, and formatting- and secret-preservation tests

### Step 3: Guard and activate hooks

Publish the exact shell fixtures, implement project permits and global tombstones, resolve registration-owning roots, add bounded degraded classification and SessionStart guidance, and connect the shared health snapshot to status.

- [ ] PR: guarded hooks, activation state, adapter working-directory contracts, migration, and latency tests

### Step 4: Add the planner and cleanup engine

Add bounded discovery, dry-run, tracked-file policy, acknowledgements, ordered mutation, retries, recovery, locks, telemetry coordination, finalization, human output, JSON, and exit codes.

- [ ] PR: uninstall command and deterministic end-to-end failure and concurrency tests

### Step 5: Complete adapters, platforms, and documentation

Exercise global and project scope for every supported adapter on Linux, macOS, and Windows, including stripped `PATH`, tracked repositories, interruptions, concurrent agents, and the original stale-hook regression. Update the command, hook, state, module-structure, important-flow, and telemetry documentation.

- [ ] PR: adapter and platform completion, documentation, and compatibility with the existing status command

Each step leaves the codebase working and extends the existing deterministic integration harness. It does not depend on rewriting that harness.

## Implementation status

This RFD describes proposed behavior. Implementation has not begun.
