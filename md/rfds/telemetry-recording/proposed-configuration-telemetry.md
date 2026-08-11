# Telemetry configuration

Telemetry consent is a per-user setting in `~/.symposium/config.toml`. Symposium reads it only from the user configuration file; project configuration cannot enable, disable, or grant consent for telemetry.

```toml
[telemetry]
enabled = true
consent-version = 1
```


| Key               | Type             | Default | Meaning                                             |
| ----------------- | ---------------- | ------- | --------------------------------------------------- |
| `enabled`         | boolean          | `false` | The user's stored choice to permit local recording. |
| `consent-version` | positive integer | absent  | Disclosure version the user acknowledged.           |


Both values must permit collection. For a binary whose current disclosure is
version 1:


| Configuration                                | Effective state                  |
| -------------------------------------------- | -------------------------------- |
| absent section or `enabled = false`          | Disabled                         |
| `enabled = true` with absent/non-`1` version | Consent required; record nothing |
| `enabled = true` and `consent-version = 1`   | Enabled                          |


The current version is owned by the binary, not accepted as an arbitrary configuration value. The [consent version 1 disclosure in the proposed telemetry command reference](./proposed-reference-telemetry.md#enable) is authoritative; interactive `init` presents the same text.

A future release may require a higher version after a change to collected categories, linkability, timestamp precision, public-name eligibility, retention, or a normative exclusion. It records nothing under an older acknowledgement until you consent again.

Adding an agent enum value creates a new schema version for each affected event kind so typed readers do not reinterpret old schemas. It does not by itself require renewed consent when the recorded fields, categories, timestamp precision, and correlation boundaries remain unchanged. New fields, hook surfaces, or linkage for that agent do require a higher consent version.

Accepting a newer consent version rotates the telemetry identity key and starts a new D0-D30 return cohort. Existing event and aggregate-metric files are neither rewritten nor deleted, but their scoped identifiers cannot link to later rows.

`cargo agents telemetry enable` presents the disclosure for the current version before writing these values. Interactive `cargo agents init` presents the same disclosure for new users and existing unversioned opt-ins, defaulting to no. Non-interactive `init` does not grant or upgrade consent.

`cargo agents telemetry disable` sets `enabled = false` without deleting existing telemetry data files. Consent configuration is separate from the random identity key in `~/.symposium/telemetry/state.toml`. The state file is not configuration, and Symposium never reads it from project configuration.

Symposium-managed project skills may also have a generated `<agent-skills-parent>/.symposium/index-v1.json` installation index. It associates the agent-facing skill identifier with the installation Discovery selected. This file is gitignored installation state, not project configuration or telemetry; changing it cannot grant consent, and telemetry commands do not inspect or delete it.
