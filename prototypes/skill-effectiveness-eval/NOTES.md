# Framework-fit notes

Status: handoff-ready but provisional. Local preparation, controls, regression tests, normalization, and reporting are complete. A live baseline reached the provider bridge, but funded smoke evidence is still unavailable.

## Evidence gathered

The free planning path was exercised on Windows on 2026-08-23. `uv` downloaded CPython 3.12.13 and the current environment contains 88 packages, including Inspect AI 0.3.252, Inspect SWE 0.2.67, and Anthropic 0.125.0. Baseline, treatment, and control tasks construct against those pinned APIs without a provider call.

Docker Desktop 4.84.0, Engine 29.6.2, and Compose 5.3.1 were available through Docker Desktop's installation directory even though `docker` was not initially on `PATH`. The wrapper now discovers standard Windows Docker Desktop locations and supplies that path. The direct image build and Inspect's Compose sandboxes both succeeded.

The initial image used a Rust toolchain for a compilation task. Its 280.2 MB base layer reached only 140.5 MB after roughly 22 minutes and was intentionally cancelled. The task was then reduced to deterministic source inspection because the evaluation question does not require compiling Rust. The replacement image downloaded a 28.2 MB Debian base layer and 24.3 MB of agent-tool packages. The first crates.io API archive request returned HTTP 403; the pinned static archive endpoint succeeded. Subsequent builds reused the layers.

The no-model controls used the same Inspect scorer and Docker sandbox definition as agent runs:

| Control | Inspect score | Expected | Inspect total time |
|---|---:|---:|---:|
| Untouched `API_NOTES.md` | `I` | `I` | 1 minute 26 seconds |
| Grader-owned known-good notes | `C` | `C` | 2 minutes 17 seconds |

The controls prove that an untouched task fails, the exact answer passes, and Inspect creates a fresh Compose project for each sample. Inspect emitted `module 'socket' has no attribute 'AF_UNIX'` on both controls and continued without its optional control surface. That warning did not prevent sandboxing or scoring, but it is Windows-specific framework friction worth retaining.

After the Claude Code binary was cached, a second control run returned the same
scores in 38 seconds and 1 minute 11 seconds. Inspect SWE's automatic download was
not viable on this host: its five-second request timeout failed against the 339 MB
Claude Code release. The prototype now pins version 2.1.238 by byte length and
SHA-256, verifies the complete cached artifact before a run, and copies it into
the Linux sandbox so it is executable despite Windows bind-mount permissions.

On 2026-08-28, the completed `prepare` command was exercised from the repository
root. It found and verified the cached binary, rebuilt both runtime images from
pinned cached layers, and returned `I` for the untouched notes and `C` for the
known-good notes. The first handoff run took 34 and 60 seconds; the final
fingerprinted rerun took 25 and 22 seconds. Both commands exited successfully. It
now
persists a fingerprint over the runner, scorer, configuration, fixture, grader,
sandbox, command shims, and lockfile; paid phases refuse missing, failed, or stale
control evidence.

Attempt `smoke-20260825T130119Z` proved that Inspect SWE launched the pinned Claude
Code process, started its model proxy, and forwarded two requests to
`anthropic/claude-sonnet-5`. Both requests received HTTP 400 with an insufficient
credit-balance error. Claude Code reported zero input/output tokens and $0.00
cost, then exited with its API-error status. The treatment condition was stopped
before it could contact the provider. The normalized exporter classifies this as
`status: unavailable` and `error_kind: billing_error`; the paired runner now stops
after any terminal infrastructure, credential, or billing failure.

The Python adapter currently contains 214 physical lines for task construction,
skill intervention, controls, and scorers, plus 907 lines for preparation,
planning, guarded execution, control evidence, failure classification, normalized
export, and Markdown reporting. Its 14 offline regression tests occupy 329 lines.
This is evidence that the project-specific wrapper is substantial, not an
optimized implementation-size claim.

| Need | Inspect provides | Symposium glue | Missing or unverified |
|---|---|---|---|
| External coding-agent execution | Inspect SWE exposes Claude Code as an Inspect agent. | Select, cache, verify, and pin the agent for each condition. | Process and provider bridge launch are verified; successful generation remains blocked on API credit. |
| Fresh isolated workspace | Inspect creates a Compose project per sample and copies sample files. | Define the fixture image and isolation controls. | Separate control projects were observed; mutation leakage still needs an explicit canary if this becomes production work. |
| Deterministic post-run scorer | A scorer can read files from the sample sandbox. | Supply and normalize the exact-answer check; fingerprint and require control evidence. | Untouched and known-good controls pass repeatedly; stale controls now block paid runs. |
| Token, cost, and duration accounting | Inspect logs sample usage and timing and supports limits. | Supply model prices, export the fields used by Symposium comparisons, and add a request-count filter. | Zero-usage billing rejection agrees between the bridge and Claude Code; nonzero accounting remains unverified. |
| Paired baseline/treatment scheduling | Tasks, samples, and logs are available. | Pair labels, deterministic order shuffling, and the skill intervention. | Inspect has no first-class paired-experiment abstraction. |
| Skill and plugin-use evidence | Inspect SWE accepts skills; sandbox artifacts are scorer-readable. | Instrument `cargo agents`, score exact invocations, and count tool events. | Structured skill-load telemetry is not established. Inspect SWE has no hard built-in-tool-call count limit. |
| Repetition and failure retention | Repeated evaluations and native logs are supported. | Preserve attempt and pair identity, prohibit paid automatic retries, classify failures, and stop a phase on terminal errors. | Retrying interrupted attempts within one cumulative budget is not implemented. |
| Portable result export | Inspect exposes a log-reading API. | Emit secret-minimized `results.json` and a Markdown gate/delta report. | A real billing failure normalized correctly; successful usage and capability evidence remain unverified. |
| Local developer ergonomics | Inspect installs through Python tooling and uses Docker Compose. | Provide one idempotent `prepare` command, readiness plan, guarded phases, and report. | Cold setup remains heavy; Docker Desktop must already be running. |

## Current interpretation

Inspect covers the expensive generic machinery: per-sample sandboxes, limits,
native logs, and sandbox-aware scoring. The controls are evidence that those
pieces work on this Windows/Docker setup. Preparation, paired scheduling, skill
intervention, capability evidence, failure policy, portable summaries, and report
gates remain project-specific code. The handoff automation makes the spike easy
to operate but strengthens the evidence that adopting Inspect would still require
a nontrivial Symposium-owned layer.

The request ceiling requires a small `GenerateFilter`, and separate total-token and output-token ceilings require wrapping the agent with another limit. Provider retries are disabled so a filtered generation is not multiplied into hidden retry requests. Tool calls can be counted after a run, but the pinned Inspect SWE API does not expose a guard that stops Claude Code before its fourth built-in tool call.

No adoption recommendation is justified yet. The pinned Claude Code process and provider bridge launch without an Inspect fork, but successful generation, nonzero usage accounting, and treatment-skill delivery remain unverified. One funded smoke pair answers those questions better than further framework comparison.

## Deviations and known limitations

- The treatment skill is supplied by Inspect SWE rather than installed through a real Symposium sync. This isolates effectiveness; it does not prove delivery.
- `bin/cargo-agents` is an instrumented interface fixture, not the production binary. The agent interaction RFD owns production-boundary coverage.
- The Debian base digest and crate archive SHA-256 are pinned. Debian package repositories are not snapshot-pinned, so rebuilding the tools layer can still change package versions.
- The container's external egress has not been reduced to an allowlisted provider bridge.
- The normalized exporter intentionally omits messages and complete transcripts.
- Normalized errors retain only their summary message; tracebacks and authentication material remain only in ignored native logs.
- Presence of `ANTHROPIC_API_KEY` is only a local readiness check. The provider account used on 2026-08-25 had insufficient API credit, which can only be detected from Anthropic's response.

## Next observation

Use a funded Anthropic API key, run `plan`, and explicitly authorize only
`smoke --confirm-paid-run`. Then run `report` and proceed to the measured phase
only if it says `Smoke readiness: PASS`. The failed attempt consumed no tokens and
reported $0.00, so the original declared smoke maximum of $0.70 remains untouched.
