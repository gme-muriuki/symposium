# Ownership and managed state

## TL;DR

- Every externally visible Symposium write records durable discovery evidence.
- Cleanup verifies the current artifact independently before modifying it.
- Receipts are versioned, private, non-executable, and secret-free.
- Changed or ambiguous artifacts are preserved.
- New instances of an existing managed artifact type inherit cleanup behavior automatically.

## Motivation

A receipt proves that Symposium previously wrote or intended to write something at a location. It does not prove that the current occupant is still Symposium's artifact.

For example, Symposium may record a Claude hook in `~/.claude/settings.json`. If the user later replaces that hook, the receipt still finds the slot, but deleting the replacement would erase user state.

Cleanup therefore separates two questions:

| Evidence | Question |
| --- | --- |
| Receipt or bounded legacy record | Where should Symposium look? |
| Signature, fingerprint, marker, or manifest | Is the current artifact still the one Symposium manages? |

Both must agree before external state is removed.

## Ownership model

- A **managed ID** is a stable UUID for one logical registration. All event entries belonging to one agent-and-scope hook registration share it.
- An **ownership receipt** records one intended managed mutation, including its target, adapter, scope, artifact type, identity evidence, and lifecycle.
- A **static signature** is a versioned structural description of a registration form emitted by a released Symposium version.
- A **dynamic fingerprint** records the non-secret identity of an instance derived from plugin configuration.

A managed ID is a correlation key. It is not proof of ownership, permission to execute, or an authoritative scope declaration.

## Path identity

Receipt targets, project roots, and runtime comparisons use one normalization function:

1. make the path absolute;
2. canonicalize the existing portion;
3. strip the Windows verbatim-path prefix when present;
4. apply Windows filesystem case rules; and
5. compare components rather than string prefixes.

Resolved paths, not inode or file IDs, identify targets. Re-cloning a dotfile repository therefore does not create an unrecoverable inode conflict. Paths are validated again immediately before every mutation.

## Managed writes

All code that changes externally visible agent state goes through one managed-mutation layer. Callers declare an artifact type and desired value; the layer supplies receipts, lifecycle, identity evidence, collision checks, safe target validation, atomic replacement, and cleanup behavior.

A normal write is:

```text
record pending intent
        ↓
write external artifact
        ↓
verify current structure
        ↓
record applied state
```

The receipt is durable before the external mutation. Recovery inspects the target instead of assuming that an interrupted write succeeded.

Adding a hook, skill, MCP server, or generated plugin package through an existing artifact type needs no uninstall-specific code. A genuinely new side-effect type needs an ownership adapter because its identity and safe deletion rules differ.

## Receipt lifecycle

A receipt has four states:

| State | Meaning |
| --- | --- |
| `pending` | Intent is durable, but the external write is not confirmed |
| `applied` | The external artifact matches its recorded identity |
| `retiring` | Removal started or was interrupted |
| `acknowledged` | The user accepted responsibility for the preserved artifact |

Project permits are published only after the corresponding write is `applied`. Completed receipts remain until the whole uninstall reaches finalization, so a crash or blocker cannot erase the only discovery evidence.

`cargo agents sync` can restore a still-applied registration left in `retiring`. Acknowledgement transfers ownership without deleting the artifact; a later change to that artifact invalidates the acknowledgement.

## Identity by artifact type

| Artifact | Identity evidence and mutation |
| --- | --- |
| Static hook or built-in MCP registration | Receipt plus exact released signature; remove only the owned structural entry or dedicated file |
| Dynamic MCP or registered plugin path | Receipt plus exact non-secret fingerprint; remove only the recorded structural entry |
| Goose MCP block | Receipt, unique marker pair, indentation, and fingerprint; remove the verified byte extent |
| Generated file | Receipt plus marker or released content signature |
| Generated skill, plugin package, or mirror | Receipt, marker, and manifest; remove the directory only when the manifest accounts for every entry |
| Symposium-private state | Containment below the fixed private root and successful external finalization |

`config.toml`, custom plugin sources, and externally authored plugin packages remain user-owned. Reading a `plugin.json` never authorizes deletion of its source. Compiled packages, copies, path registrations, and enablement entries written by Symposium are managed artifacts.

A `.symposium` marker helps identify a generated package, but it is never sufficient by itself for recursive deletion. The receipt finds the target, and the marker plus manifest must account for its current contents.

## Static signatures

Symposium keeps a versioned catalog of every released static form, including current and historical forms:

- generated hook commands and their containing structure;
- dedicated generated agent files;
- static built-in MCP registrations; and
- generated markers and manifests.

Signatures compare parsed structure, normalized executable identity, fixed arguments, and managed-ID placement. They do not match on a broad key name, event name, or the presence of `cargo-agents` alone.

Changing a released generated form adds a signature fixture rather than replacing old evidence. This is the compatibility cost that allows cleanup after receipts are lost or an older release is removed.

## Dynamic fingerprints

Plugin-provided MCP names, commands, arguments, transports, and URLs are not a finite catalog. Their identity is captured when written.

| Adapter | Structural container |
| --- | --- |
| Claude, Gemini, Kiro | `mcpServers.<name>` |
| GitHub Copilot | Top-level MCP server map entry |
| Codex | `mcp_servers.<name>` |
| Goose | `extensions.<name>` |
| OpenCode | `mcp.<name>` |

The fingerprint includes the adapter, normalized target, structural container, entry name, transport, and command plus arguments or URL. It excludes environment values, headers, tokens, and other secrets.

Removal requires every recorded non-secret identity field to match. A changed field transfers the entry out of automatic cleanup and produces a conflict. Without the receipt, a dynamic entry is preserved because name or command resemblance is not proof.

Goose is an editing exception. Its YAML is not round-tripped through a serializer that would discard comments and formatting. Symposium writes behavior-neutral managed-ID comment markers, verifies one unique marker pair and the enclosed mapping, then removes that exact byte extent. Missing, duplicate, malformed, or mismatched markers preserve the block.

## Collisions and user changes

Init and sync inspect the current adapter slot before writing. They do not adopt or overwrite an occupied location without matching `pending` or `applied` evidence. Migration from an exact released signature is a separate path.

Collision detection is structural and does not depend on a retained acknowledgement. Reinstallation therefore treats a preserved occupied location as a collision even after finalization removes old managed records.

An external change between read and replacement causes that target to be replanned. Symposium never overwrites the concurrent edit using stale identity evidence.

## Filesystem safety

Receipts are treated as untrusted input. Before mutation, Symposium validates:

- the schema version, artifact kind, UUIDs, and enums;
- containment below an allowlisted adapter or private root;
- the expected file or directory shape;
- component-wise ancestor relationships;
- the artifact's link policy; and
- current identity evidence.

Cleanup never follows a symlink or junction while deleting a generated tree. If a managed target has been replaced by a link, it is preserved. A directory is removed only when its manifest accounts for every remaining entry.

## Missing receipts and historical state

At known locations, exact released signatures can identify static current and legacy forms even when a receipt is missing. The next `init` or `sync` may migrate such a registration to the managed form; uninstall may remove it after the same exact identity check.

Dynamic entries without receipts remain preserved. Unknown pre-receipt project roots cannot be rediscovered by scanning the user's filesystem.

The first receipt-aware release records a durable coverage origin:

- `managed-only` when no earlier or unexplained integration exists;
- `pre-receipt` when an older release or exact legacy artifact is found; or
- `unknown` when provenance is missing or corrupt for existing state.

The origin is never promoted automatically. The cleanup engine uses it to qualify the final assessment.

## Storage and cost

Receipts live below a versioned directory in the resolved Symposium configuration home. They contain paths and identity metadata, never executable instructions, tokens, environment values, or headers. Atomic writes and private permissions protect the store.

Storage grows linearly with recorded integrations and checkouts. Completed records are removed during successful finalization. Recorded project paths are visible only to principals already able to read Symposium's private configuration and are never uploaded as telemetry.

## Acceptance tests

Tests cover:

- schema evolution, truncation, corruption, and every lifecycle crash point;
- path normalization, containment, symlinks, junctions, and manifests;
- current and historical static signatures;
- dynamic fingerprints with secret fields excluded;
- collisions, concurrent changes, and acknowledgement invalidation;
- Goose block editing with surrounding formatting preserved;
- generated skill and plugin-package directories; and
- missing receipts and historical coverage.
