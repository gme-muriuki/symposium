# Proposed: managed integrations

Symposium writes derived state into coding-agent configuration and project directories during init and sync. Managed integrations make those writes discoverable, identifiable, locally activatable, and removable without claiming ownership of surrounding user files.

## Three separate questions

Managed state deliberately separates:

1. **Discovery:** where should Symposium look? Ownership receipts and known adapter locations answer this.
2. **Identity:** is the current artifact one Symposium manages? Released static signatures, dynamic fingerprints, markers, and manifests answer this.
3. **Execution:** may this project hook run here? A root-bound activation permit answers this.

A managed ID connects records across those questions. It is non-secret, may appear in committed configuration, and grants neither deletion authority nor permission to execute by itself.

## Ownership receipts

Every managed mutation receives a stable ID and a small receipt in Symposium's private configuration directory. The receipt records:

- artifact type and adapter;
- global or project scope;
- normalized target and structural location;
- the non-secret identity evidence needed later; and
- lifecycle state: pending, applied, retiring, or acknowledged.

Receipts never contain project source, plugin source contents, environment values, HTTP headers, tokens, or command output. They do not expire because a workspace has been idle. Old or missing paths use a small amount of storage and are removed only when cleanup can safely finalize.

Receipts make discovery bounded; they do not authorize deletion. A malformed or forged receipt still has to pass path containment, target-shape, link, and artifact-specific identity checks.

## Identity evidence

Static registrations emitted by released Symposium versions have versioned structural signatures. The catalog includes current and historical hook forms, dedicated generated files, and static built-in MCP entries. Receipts say where to inspect; signatures prove the current structure still matches a released form.

Plugin-provided MCP entries are dynamic. At write time Symposium records a secret-free fingerprint containing the adapter, target, structural container, name, transport, and command-plus-arguments or URL. Environment and header values are excluded. If the non-secret identity changes or the receipt is lost, cleanup preserves the entry.

Generated skills and other dedicated output use markers and manifests. Unknown contents, or a generated path replaced by a symlink or junction, prevent automatic deletion.

Goose MCP entries use managed-ID comment markers because its YAML file cannot be reserialized without losing comments and formatting. Cleanup verifies the one marked block and removes its exact byte range; any marker, indentation, or fingerprint mismatch preserves it.

All managed writers use one central mutation layer, so new hooks, skills, and MCP instances receive the appropriate evidence automatically. Only a new kind of external side effect needs a new ownership adapter.

Init and sync inspect the current structural slot before writing. An occupied slot without matching pending or applied ownership evidence is a collision, even when its value resembles a released Symposium form. Explicit legacy migration is classified separately.

## Project hook activation

A project activation permit binds one managed ID to one normalized registration-owning root. Generated hooks carry the managed ID, but scope comes from trusted local state rather than command text. Before normal project hook startup, Symposium:

1. obtains the process working directory without invoking Cargo;
2. walks its ancestors to a fixed depth for the nearest adapter project configuration containing an exact released registration for this managed ID;
3. normalizes that registration-owning root with the same function used by sync; and
4. continues only when the permit root equals that root exactly.

Finding a permit for the ID, or finding only an ancestor match, is never sufficient. An unrelated nested adapter configuration is ignored; a nested checkout containing the copied registration resolves to its own root and cannot inherit a parent's permit. Sync refuses to permit the user's home or a filesystem root.

If the project is inactive, SessionStart may emit static `additionalContext` telling the user to run `cargo agents sync`. It does not load workspace plugins, auto-sync, refresh registries, or execute project-provided code. A per-root notice record suppresses the hint after it has been shown once. Other inactive events exit successfully and silently.

Global hooks have no positive activation permit. They run unless uninstall has written a positive retirement tombstone for that managed ID. An empty, deleted, or unavailable managed store therefore does not silently disable the recommended global workflow. A global hook still runs in every project, so tombstones do not make Symposium's global workflow a defense against hostile workspace configuration.

## Binary guards and failure visibility

Generated shell commands try the executable path resolved during machine-local registration, then fall back to `PATH`. Portable committed project forms try the conventional Cargo home first. If the binary is absent, the command exits with status 0 and no output.

That outer guard handles only an absent executable. Its generated command is one line, carries the managed ID, and shell-escapes absolute paths including apostrophes. The binary then checks trusted local state before ordinary startup. If state is missing, it classifies scope only by finding one exact released registration signature at the nearest project or known global adapter target. Project failures deny dispatch; an exactly proven global registration continues and reports degraded health where possible; ambiguous invocations do not run plugins.

`cargo agents status` consumes a read-only managed-health snapshot and reports inactive, retiring, corrupt, unavailable, degraded-global, and cleanup-in-progress states. It does not repair state while reading it. An explicit sync recreates corrupt derived permits from valid receipts and restores a matching registration interrupted during uninstall.

## After cloning, copying, or moving a project

Run once from the new checkout:

```console
cargo agents sync
```

Sync verifies the registration, records the normalized local root, and publishes its permit. Multiple clones may share a managed ID, but every root is activated separately.

Moving a project does not rewrite an old permit implicitly. The moved checkout remains inactive until sync records its new root. A container, WSL environment, and Windows host are separate permit environments even when they expose the same repository.

The old record remains small and inert until cleanup confirms that path is absent. Symposium never searches the filesystem for a moved project.

## Tracked project configuration

Some project hook files are intentionally committed for a team. Uninstall checks Git outside the hook path:

- when no ancestor has a `.git` file or directory, no Git executable is required;
- tracked configuration is preserved by default;
- `cargo agents uninstall --include-tracked` authorizes removal of only the verified Symposium entry; and
- unavailable or indeterminate Git tracking preserves the file as a blocker.

`--acknowledge <BLOCKER-ID>` may transfer a preserved artifact to user ownership without deleting it. It cannot make an unguarded hook or direct MCP reference to `cargo-agents` safe for binary removal.

## Legacy registrations

Legacy hooks keep their existing runtime behavior. Symposium does not add on-event disk verification that would require locating a Cargo workspace. Exact historical signatures allow known registrations to migrate during init or sync and to be removed during uninstall.

Historical workspace state recovers some old roots, but previous manual syncs did not always record `workspace_root`. An otherwise unknown pre-receipt project remains undiscoverable without a filesystem scan. The uninstall assessment states that limitation rather than claiming universal coverage.

## Removing Symposium

First quit all agents that may rewrite cached settings. Then run:

```console
cargo agents uninstall
```

Cleanup retires one artifact immediately before removing it: it retires a project permit or creates a global tombstone. It verifies each removal and keeps its receipt until the entire run can finalize. If any blocker remains, discovery state and private caches stay available for a rerun or repair.

After the command reports no live integrations in its stated scope, run:

```console
cargo uninstall symposium
```

Then start the agents again. If cleanup was interrupted and Symposium should remain installed, `cargo agents sync` restores registrations whose receipts still match.
