# `cargo agents uninstall`

> Proposed user documentation for the [Managed Symposium uninstall RFD](../README.md). It does not describe released behavior yet.

Remove agent integrations and private local data managed by Symposium before removing the Symposium package.

## Usage

```console
cargo agents uninstall [--dry-run] [--include-tracked]
                       [--acknowledge <BLOCKER-ID>]...
                       [--quiet] [--json]
```

The command examines all known global and recorded project scopes. It may run inside or outside a Cargo workspace and never scans the entire filesystem.

## Recommended removal workflow

1. Quit all running coding agents that may have loaded Symposium configuration.
2. From an ordinary terminal, run:

   ```console
   cargo agents uninstall
   ```

3. Resolve or acknowledge reported blockers and rerun as directed.
4. Run:

   ```console
   cargo uninstall symposium
   ```

5. Start the coding agents again.

Quitting first prevents an agent from writing a cached settings file after cleanup removes its entry. Starting after package removal makes agents reload the cleaned configuration.

## What it removes

When ownership can be verified, the command removes:

- Symposium hook registrations;
- Symposium-managed MCP server entries;
- generated or mirrored skills;
- dedicated generated files and directories;
- private plugin and installation caches;
- telemetry, logs, and private runtime state; and
- receipts, project permits, global retirement tombstones, and notice records after external cleanup succeeds.

The command uses known global locations, ownership receipts, project permits, tombstones, the current project when available, and recorded historical roots. It removes only the managed entry from a shared configuration file. Goose YAML uses verified marker-delimited block removal so surrounding comments and formatting remain unchanged.

## What it preserves

The command preserves:

- `config.toml`, including plugin declarations and telemetry preferences;
- custom plugin sources and user-authored skills;
- entries changed or replaced by another program;
- shared tools installed through Cargo or another package manager;
- effects of arbitrary legacy installation scripts that cannot be identified safely;
- tracked project configuration unless `--include-tracked` is supplied; and
- every artifact whose ownership or target safety is ambiguous.

Private caches and discovery state are retained when cleanup has blockers so a rerun or `cargo agents sync` can repair the installation.

## Dry run

`--dry-run` takes a consistent shared-lock snapshot and performs the same bounded discovery, path validation, Git classification, and ownership verification as cleanup without writing or deleting anything. It reports `Would remove`, `Preserved`, and `Blocked` items. Blockers return status 3; an unreliable preview returns status 1.

```console
$ cargo agents uninstall --dry-run
Would remove
  Global
    Claude hooks
      ~/.claude/settings.json: Symposium hook entries

Preserved
  ~/.symposium/config.toml: user configuration

Preview complete. Apply with `cargo agents uninstall`.
```

Apply mode rechecks every target because an agent or another program may change configuration after the preview.

## Tracked files and acknowledgements

A hook inside a Git-tracked project file is preserved by default and reported as “committed by your project.” Use `--include-tracked` to authorize removal of the verified Symposium entry. The surrounding file and unrelated entries remain untouched.

When no ancestor contains a `.git` file or directory, uninstall treats the project as outside Git and does not require a Git executable.

`--acknowledge <BLOCKER-ID>` keeps an artifact but transfers responsibility for it to you. The ID is stable for the same artifact kind, adapter, normalized target, and structural location. The acknowledgement also records current identity, so changing the artifact invalidates it. The report prints its location and a redacted fragment for manual removal. This is not a force option and does not weaken ownership checks.

An unguarded hook or MCP server that still launches `cargo-agents` cannot be acknowledged into a ready result. Remove that live reference before uninstalling the package.

## Output

A completed run reports what was actually removed:

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

No remaining live Symposium integrations in recorded scopes.
Next: run `cargo uninstall symposium`, then start your coding agents.
```

For an installation upgraded from a version that may have unrecorded projects, the final assessment instead says:

```text
No remaining Symposium integrations in known scopes.
Older unrecorded project integrations may still exist; see the preserved items above.
```

The command never claims knowledge of a project it cannot discover.

If cleanup is incomplete, `Blocked` identifies every live reference or operational failure and `Next steps` gives the exact rerun, sync, flag, acknowledgement, or manual edit. Completed removals remain complete.

## JSON output

The existing global `--json` option emits one versioned document containing:

- `mode`;
- `binary_removal_assessment`: `ready`, `ready-for-known-scopes`, or `blocked`;
- exact actions and already-absent artifacts;
- preserved and acknowledged items;
- blockers; and
- next steps.

Items include stable reason codes and whether they remain a live binary reference. Paths are included where useful; secret values and plugin source contents are not.

## Exit status

| Status | Meaning |
|---|---|
| 0 | Preview or cleanup completed with no live blockers in its assessment boundary |
| 1 | An operational failure prevented reliable planning or verification |
| 2 | Command-line usage error |
| 3 | Preview or cleanup completed, but live blockers remain |

Missing artifacts are already absent. Invalid receipts, unsafe paths, ownership conflicts, indeterminate tracked state, persistent locks, unsupported schemas, and failed verification are not silently treated as success.

## Copied, moved, and containerized projects

Project registrations are inactive until their exact registration-owning root has been synchronized locally. A nested checkout cannot inherit a parent checkout's permit. After cloning, copying, moving, or opening a project in a new container, run:

```console
cargo agents sync
```

An inactive SessionStart may tell you to run that command once per root, but it does not load plugins or execute project-provided code. Other inactive hook events exit successfully without output. Global hook registrations remain global and do not gain an untrusted-project boundary from this mechanism. Deleting the managed store does not disable an exact verifiable global registration; only an uninstall retirement tombstone does. An ambiguous invocation does not run plugins.

Registrations created before managed receipts and guards are a transition case. Uninstall can inspect the current project and roots retained in historical state, but older manual syncs did not always record a root. Before removing a pre-receipt installation, sync any known dormant project-scoped checkouts.

## Interrupted cleanup

If cleanup is interrupted, rerun `cargo agents uninstall` to resume. If you decide to keep using Symposium instead, run `cargo agents sync`; it repairs matching registrations left in a retiring state. `cargo agents status` reports corrupt, unavailable, degraded-global, inactive, or repairable state and names the next command.
