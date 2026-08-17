# Proposed: `cargo agents uninstall`

Remove the agent integrations and local data managed by Symposium before uninstalling the Symposium package.

## Usage

```console
cargo agents uninstall [--dry-run]
```

The global `--quiet` and `--json` options are also supported.

The command cleans all known global and project scopes. It can run inside or outside a Cargo workspace and does not prompt.

## Recommended removal workflow

```console
$ cargo agents uninstall
# Restart any running coding agents.
$ cargo uninstall symposium
```

Do not remove the package when `cargo agents uninstall` reports an incomplete cleanup. Resolve the listed blockers and rerun it.

Restarting matters because a running agent may have cached its hook configuration. Symposium cannot safely restart the agent process that launched or contains the current terminal.

## What it removes

When ownership can be verified, the command removes:

- Symposium hook registrations from supported agent configurations;
- Symposium MCP server registrations;
- generated and mirrored skill copies;
- generated files and directories;
- private plugin and installation caches;
- logs, telemetry events and identifiers, and other private runtime state;
- workspace state and hook activation permits; and
- ownership receipts after their artifacts are absent.

The command checks the active global configuration locations, the current workspace, previously recorded workspaces, and exact locations used by older Symposium versions. It does not search the entire filesystem.

## What it preserves

The command preserves:

- Symposium's `config.toml`, including plugin declarations and telemetry preference;
- user-authored custom plugin sources;
- agent configuration that is not owned by Symposium;
- entries another program has replaced or whose ownership is ambiguous;
- shared tools installed into locations such as Cargo's binary directory; and
- side effects from arbitrary legacy installation scripts that cannot be identified safely.

Preserved external tools and known untracked setup are shown in the report. For upgrades from a pre-receipt version, the report also identifies the possibility of an unknown legacy project checkout when detectable. An ownership conflict is a blocker; a deliberately preserved shared tool or legacy-coverage notice is not.

## Output

A successful cleanup lists concrete actions and ends with the next steps:

```text
Removed
  Global
    Claude hooks
      ~/.claude/settings.json: Symposium hook entries
  Workspaces
    /work/example
      Codex skills
        .agents/skills/example-skill
  Symposium state
    telemetry events
    plugin cache

Preserved
  ~/.symposium/config.toml: user configuration
  cargo-binstall: shared Cargo tool

Cleanup complete. It is safe to remove the Symposium binary.
Next: restart running coding agents, then run `cargo uninstall symposium`.
```

If cleanup is incomplete, a `Not removed` section identifies every blocker. Successful removals are retained; rerunning the command safely skips artifacts that are already absent.

`--quiet` hides successful detail but retains blockers and the final verdict.

## Dry run

`--dry-run` performs discovery, reads current state, and applies the same ownership checks as cleanup without making persistent changes. Its report uses `Would remove`:

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

Dry run is a preflight, not an alternative to uninstall. It exits unsuccessfully if the real cleanup would have a known blocker. Apply mode rechecks files before changing them because another program may modify configuration after the preview.

## JSON output

`--json` writes one versioned document to stdout with:

- mode and outcome;
- whether it is safe to remove the binary;
- exact removed, would-remove, or already-absent actions;
- preserved items;
- blockers; and
- the next required step.

Paths and ownership reasons are included where safe. Secrets, configuration values, plugin source contents, and command output are not included.

## Exit status

The command exits successfully only when apply mode has no cleanup blockers. In dry-run mode it exits successfully only when the preview finds no blocker.

Missing artifacts are treated as already absent. Invalid receipts, unsafe paths, ownership conflicts, persistent file locks, unsupported configuration schemas, and failed removals produce a nonzero exit.

## Copied and moved workspaces

Project hook registrations are locally inactive until their checkout has been synchronized. After cloning, copying, or moving a workspace that contains Symposium-generated project configuration, run:

```console
$ cargo agents sync
```

This records the local workspace and activates its hooks. `cargo agents status` reports a present but inactive hook and recommends sync. A stale project hook remains quiet when it has no local activation record or when the Symposium binary is absent.

Registrations created before managed IDs and guards existed are a transition case. Uninstall finds the current workspace and roots retained in historical workspace state, and active legacy hooks migrate when they run. It cannot discover an old project hook in an otherwise unknown checkout without scanning the filesystem. Before removing a pre-receipt installation, sync any known project-scoped checkouts that have not been used recently; the uninstall report identifies limited legacy coverage when detectable.
