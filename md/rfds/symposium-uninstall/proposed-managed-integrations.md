# Proposed: managed integrations

Symposium writes derived state into coding-agent configuration and project directories when it initializes or synchronizes a workspace. Managed integrations make those writes identifiable, locally activatable, and removable without claiming ownership of the surrounding user files.

## Ownership

Every managed integration receives a stable, non-secret ID. Symposium keeps a small ownership receipt in its configuration directory describing the artifact type, scope, location, and evidence required to recognize that integration again.

Receipts do not contain project source, complete agent configuration, plugin source contents, environment variables, tokens, or command output. They remain until the managed artifact is removed or confirmed absent; they do not expire merely because a workspace has not been opened recently.

The receipt allows Symposium to remove its own nested hook or MCP entry while preserving the shared configuration file and adjacent entries from the user or another program. If the current state no longer matches the ownership evidence, Symposium reports a conflict instead of deleting it.

## Generated files and directories

Generated skills and other dedicated output carry a marker and manifest tied to their receipt. Symposium removes only accounted-for content within known generated boundaries.

If a generated directory contains an unknown file, or a managed path has been replaced by a symlink or junction, cleanup preserves it and reports the conflict. User-authored skills and custom plugin sources are not generated output and are preserved.

## Hook activation

Hook registrations carry their managed ID in the `cargo-agents` invocation. A small local activation permit lets the binary decide whether that ID may run in the current scope before loading plugins or inspecting the Cargo workspace.

Global hooks have a local global permit. Project hooks have a permit for each locally synchronized checkout root.

The generated command is also guarded by the shell form supported by that agent. If the `cargo-agents` binary is missing, the command exits successfully without output. If the binary exists but no matching local permit exists, the hook also exits successfully without output. Genuine Symposium hook failures retain their output and exit status.

## After cloning, copying, or moving a project

A managed ID in a project file is not itself permission to execute. Run sync once from the new checkout:

```console
$ cargo agents sync
```

Sync verifies the registration, records the local root, and activates it. This prevents a copied or committed hook from becoming active merely because an agent opened the project.

Until then, `cargo agents status` reports that the hook is present but inactive and recommends sync. The hook stays silent so stale configuration does not interrupt the agent workflow.

Multiple local clones may share the same managed ID. Each root is activated separately.

## Moving or deleting an old checkout

Syncing after a move records the new root. The old record remains small and inert until cleanup confirms its old path is absent. `cargo agents uninstall` then retires it.

Symposium does not scan the filesystem to locate a project that moved without being synchronized again. A remaining managed registration is still harmless after removal of the binary because it contains the outer guard.

An unrecorded project hook from a version that predates managed IDs is the transition exception: Symposium cannot guard a file it cannot locate. Active legacy hooks migrate automatically while the binary exists, historical workspace state recovers known roots, and users upgrading from an older version should sync any dormant project-scoped checkouts they still use before uninstalling.

## Removing Symposium

Run `cargo agents uninstall` while the binary still exists. It uses receipts and exact legacy signatures to remove known managed integrations, private state, and generated data. It preserves user configuration and anything it cannot prove it owns.

After successful cleanup, restart running coding agents and run `cargo uninstall symposium`.
