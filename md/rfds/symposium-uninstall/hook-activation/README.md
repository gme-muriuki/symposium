# Hook activation

## TL;DR

- Every new hook command makes an absent `cargo-agents` binary a successful no-op.
- Project hooks run only with a local permit for the exact registration-owning root.
- Global hooks run unless uninstall has written a retirement tombstone.
- Missing or damaged state is either correctly inactive or visible through managed-health reporting.
- Legacy hooks retain their current runtime behavior until an exact signature is migrated.

## Motivation

Hook cleanup needs runtime coordination for two reasons.

First, an agent may invoke a registration after Cargo has removed `cargo-agents`. The generated command must treat that expected absence as success rather than reproducing the original hook error.

Second, a project registration may be committed and copied. Its managed ID is therefore public and cannot authorize execution in another checkout. Project activation needs local state bound to the exact checkout that owns the registration.

These controls do not establish general workspace trust. A global hook is intentionally valid in every working directory and may discover workspace plugin configuration. Protecting global-hook users from hostile repositories would require a separate design that gates workspace plugin activation itself.

## Runtime flow

```text
agent invokes hook
        ↓
outer guard locates cargo-agents
        ↓
preflight classifies project or global scope
        ↓
permit or tombstone decision
        ↓
ordinary hook startup and plugin dispatch
```

The outer guard handles binary absence. The in-process preflight handles scope and retirement before ordinary startup loads plugins, refreshes registries, or auto-syncs.

## Scope classification

Every new invocation carries `--managed-id <UUID>`, but does not carry an authoritative scope. Preflight classifies scope from a directly addressed receipt, project permit, or global tombstone. Text in the invocation is never sufficient.

When state for the ID is missing or unavailable, preflight performs a bounded degraded classification. It checks the registration-owning-root walk and the adapter's known global target for an exact released signature containing that ID:

- one project match remains inactive and may show the sync hint;
- one global match runs and reports degraded health; and
- zero or multiple matches deny plugin dispatch and report ambiguity.

The fallback opens only known adapter configuration files and does not invoke Cargo.

## Project activation

A project permit binds:

```text
managed ID + normalized registration-owning root
```

Preflight starts at the process working directory and walks a bounded number of ancestors. The registration-owning root is the nearest ancestor whose adapter project configuration contains an exact released registration for this managed ID. A nearer configuration without that registration is ignored.

Execution requires:

1. trusted state or exact degraded classification identifies project scope;
2. a registration-owning root exists;
3. the permit carries the same managed ID; and
4. the normalized permit root equals the normalized owning root.

The permit root being merely an ancestor of the working directory is not enough. A nested checkout containing the copied registration resolves to its own root and is denied. Sync refuses to permit the filesystem root or the user's home directory.

Adapters must invoke project hooks with a working directory inside the checkout. An adapter that cannot provide this contract cannot offer project-scoped guarded registrations. Adapter tests cover launches from the checkout root and nested directories.

A moved checkout, a new clone, a dev container, WSL, and the Windows host are separate permit environments when they expose different normalized roots. Each needs `cargo agents sync`.

## Global activation

Project and global registrations deliberately fail in opposite directions:

| Scope | Active when |
| --- | --- |
| Project | A positive permit matches the ID and owning root |
| Global | No valid retirement tombstone exists for the ID |

Losing a project permit makes a copied registration inactive. Losing the managed-state directory must not silently disable the recommended global installation, so missing global state is not an activation denial. A global registration runs after receipt proof or one exact degraded signature match and records degraded health where possible.

Uninstall writes a global tombstone immediately before mutating that registration. A valid tombstone makes the hook exit successfully and quietly. A corrupt tombstone denies dispatch and surfaces a repair warning.

## Preflight outcomes

| Classification and state | Behavior |
| --- | --- |
| Project permit matches ID and owning root | Continue to ordinary hook startup |
| Project permit missing or non-matching in a readable store | Remain inactive; SessionStart may give one sync hint |
| Project state corrupt or unavailable | Deny plugin dispatch and surface repair guidance |
| Valid global tombstone present | Exit successfully and quietly |
| Corrupt global tombstone present | Deny plugin dispatch and surface repair guidance |
| Global registration proven, no tombstone | Continue; report degraded health when state was missing |
| Missing state with zero or multiple exact matches | Deny plugin dispatch and report ambiguity |

Correctly inactive project events are quiet except for the bounded SessionStart guidance described below. An inability to determine state is not silently treated as correct inactivity.

## Inactive SessionStart

An inactive project SessionStart may perform preflight and emit static `additionalContext` naming `cargo agents sync`. It may not read workspace plugin configuration, refresh a registry, run plugin code, or auto-sync.

A per-root notice record suppresses repeated guidance. Records are capped at 64 roots per managed ID; beyond the cap, new roots receive no stored or repeated hint and status reports the suppressed count. Other inactive events return success without output.

If a writable managed store contains corrupt state, preflight records a health flag and one best-effort log line. Corrupt records are quarantined and recreated by the next explicit sync. When the store itself is unavailable, status detects that condition on demand and SessionStart provides the only guaranteed warning; Symposium does not invent a second fallback state directory.

## Status and repair

The managed-state layer exposes one read-only, versioned health snapshot for the existing or concurrently developed `cargo agents status` command. It reports inactive, retiring, corrupt, unavailable, and cleanup-in-progress states with stable reason codes and recommended commands.

Status does not repair state as a side effect. It reads under the installation barrier in shared mode. While uninstall owns the exclusive barrier, status reports cleanup in progress rather than inspecting half-mutated targets. Corrupt or unreadable state produces a diagnostic snapshot rather than a panic.

`cargo agents sync` is the explicit repair path. If a retiring receipt still matches an applied registration, sync restores it to `applied`, republishes its project permit, or removes its global tombstone.

## Generated outer guards

The outer guard has one job: an absent binary exits with status 0 and no output. Scope-aware preflight stays inside the binary.

Machine-local global registrations record and try the resolved absolute `cargo-agents` path first, then fall back to `PATH`. A committed project registration cannot contain another user's absolute path, so its portable form tries the Cargo home convention before `PATH`.

The following are the versioned single-line command values before host serialization.

POSIX machine-local global:

```sh
if [ -x <ABSOLUTE_PATH_POSIX_LITERAL> ]; then exec <ABSOLUTE_PATH_POSIX_LITERAL> hook <AGENT> <EVENT> --managed-id <UUID>; elif command -v cargo-agents >/dev/null 2>&1; then exec cargo-agents hook <AGENT> <EVENT> --managed-id <UUID>; else exit 0; fi
```

POSIX portable project:

```sh
if [ -x ${CARGO_HOME:-$HOME/.cargo}/bin/cargo-agents ]; then exec ${CARGO_HOME:-$HOME/.cargo}/bin/cargo-agents hook <AGENT> <EVENT> --managed-id <UUID>; elif command -v cargo-agents >/dev/null 2>&1; then exec cargo-agents hook <AGENT> <EVENT> --managed-id <UUID>; else exit 0; fi
```

PowerShell machine-local global:

```powershell
$symposiumBin = <ABSOLUTE_PATH_POWERSHELL_LITERAL>; if (-not (Test-Path -LiteralPath $symposiumBin -PathType Leaf)) { $symposiumCommand = Get-Command cargo-agents -CommandType Application -ErrorAction SilentlyContinue; if ($null -eq $symposiumCommand) { exit 0 }; $symposiumBin = $symposiumCommand.Source }; $global:LASTEXITCODE = $null; & $symposiumBin hook <AGENT> <EVENT> --managed-id <UUID>; if ($null -eq $LASTEXITCODE) { exit 1 }; exit $LASTEXITCODE
```

PowerShell portable project:

```powershell
$cargoHome = $env:CARGO_HOME; if ([string]::IsNullOrWhiteSpace($cargoHome)) { $cargoHome = Join-Path $HOME '.cargo' }; $symposiumBin = Join-Path $cargoHome 'bin/cargo-agents.exe'; if (-not (Test-Path -LiteralPath $symposiumBin -PathType Leaf)) { $symposiumCommand = Get-Command cargo-agents -CommandType Application -ErrorAction SilentlyContinue; if ($null -eq $symposiumCommand) { exit 0 }; $symposiumBin = $symposiumCommand.Source }; $global:LASTEXITCODE = $null; & $symposiumBin hook <AGENT> <EVENT> --managed-id <UUID>; if ($null -eq $LASTEXITCODE) { exit 1 }; exit $LASTEXITCODE
```

The POSIX literal encoder single-quotes the path and escapes embedded apostrophes as `'\''`. The PowerShell encoder single-quotes the path and doubles embedded apostrophes. Placeholders above are already encoded literals, never raw paths.

Copilot publishes both shell forms. Versioned adapter fixtures assert the decoded command and exact JSON, TOML, or YAML serialization. They also cover absent binaries, stripped `PATH`, spaces and shell metacharacters, launch failures, status propagation, payload preservation, and an unchanged working directory.

## Legacy registrations

A hook invocation without a managed ID follows legacy behavior. Legacy hooks already run unguarded; adding on-disk verification to their hot path would introduce a new failure mode. Exact historical signatures are instead used during bounded migration and cleanup. The next `init` or `sync` may rewrite one into the guarded form.

## Agent plugin boundary

Project permits govern Symposium-dispatched hooks. A native agent-plugin directory is loaded by the agent and does not pass through hook preflight. Its scope must be enforced by project-scoped placement, a workspace-scoped agent registration, or a project-safe fallback.

## Performance

Preflight performs no directory-wide scan, network access, registry refresh, plugin loading, Cargo metadata query, or subprocess. It reads directly addressed state, normalizes the working directory, and performs bounded adapter-configuration signature checks.

Guarded hooks may become the default only while p95 added preflight latency is no more than:

```text
max(2 ms, 5% of baseline hook-dispatch latency)
```

The baseline uses the same outer guard without managed-state preflight. CI records p50 and p95 for active, inactive, missing-store, and nested-checkout cases on Linux, macOS, and Windows. Receipt-store size must not change the number of hot-path reads or path probes.

## Acceptance tests

Tests cover:

- positive project permits and global retirement tombstones;
- clones, moves, monorepos, unrelated nested configuration, and nested checkouts;
- missing, corrupt, unavailable, and ambiguous state;
- one-time and dismissed SessionStart guidance without plugin execution;
- status snapshots before, during, and after cleanup;
- exact POSIX and PowerShell fixtures for every supported adapter;
- adapter working-directory contracts from root and nested directories;
- legacy runtime behavior and migration; and
- the numeric latency budget.
