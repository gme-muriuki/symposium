# Skill-effectiveness framework spike

Status: handoff implementation complete; funded smoke and measured evidence pending (2026-08-28)

This is a handoff specification for a disposable experiment. It is not an RFD and does not propose a stable Symposium interface.

## Purpose

Determine whether Inspect AI and Inspect SWE can provide most of the machinery needed to measure whether a Symposium-provided skill improves a coding agent.

The experiment compares equivalent agent runs with and without one skill. It measures task completion, token and time usage, and whether the agent invoked the Symposium capability described by that skill. The result should tell the team whether to adopt Inspect behind a Symposium-specific wrapper or build a smaller native runner.

This work is separate from the accepted [agent interaction testing RFD](../rfds/agent-interaction-testing/README.md). That RFD tests whether Symposium interactions and capability delivery work. This spike tests whether an available capability changes an agent's outcome.

## Research question

Can stock Inspect plus Inspect SWE run a controlled baseline/treatment comparison while leaving only thin Symposium-specific glue for:

- preparing the two skill configurations;
- recording Symposium capability use;
- pairing and labelling runs; and
- exporting a compact comparison report?

The answer is **yes** only if the integration remains a wrapper around public APIs. A fork of Inspect or Inspect SWE, a custom sandbox backend, or an agent-specific patch counts as evidence to build a smaller native harness instead.

## Scope

The spike uses:

- one coding agent: Claude Code;
- one model pin: `anthropic/claude-sonnet-5`;
- one skill: `find-crate-source`;
- one small source-inspection task involving `cargo-platform` 0.3.3;
- one deterministic exact-content grader that executes after the agent finishes;
- one smoke pair followed, if sound, by three measured pairs; and
- JSON output suitable for later analysis.

The initial case does not compile or test Rust code. It is a Markdown-editing task chosen because locating facts in a pinned crate directly exercises `find-crate-source`. The harness design must not assume that future tasks are Rust projects or that all graders execute programs.

## Non-goals

This spike does not:

- add a production command to `cargo agents` or `cargo xtask`;
- replace the agent interaction test harness;
- prove that Symposium installs skills correctly;
- compare multiple agents or models;
- use an LLM judge;
- establish statistical significance from three pairs;
- run automatically in CI; or
- weaken Symposium telemetry or credential-handling rules.

## Experimental unit

Each run starts from a fresh sandbox containing the same task files, dependency cache, toolchain, agent version, prompt, model, permissions, and limits.

The only intended difference is skill availability:

| Condition | Available capability |
|---|---|
| `baseline` | The `cargo agents` command exists, but no `find-crate-source` skill is supplied to Claude Code. |
| `symposium` | The same command exists and the repository's `find-crate-source` skill is supplied to Claude Code. |

The spike uses Inspect SWE's `skills` parameter to make the treatment skill available. This isolates skill effectiveness from installation correctness. A result from this spike must therefore say “skill available through Inspect SWE,” not “installed by Symposium.”

Run order is shuffled within each pair from a recorded seed. Every attempt receives a fresh sandbox. Failed or inconclusive runs are retained and are not silently retried as another sample.

## Task and grading

The agent receives `Cargo.toml` and an `API_NOTES.md` file with three placeholders. It must inspect the pinned `cargo-platform` 0.3.3 source and record:

- the `Platform` variants, in declaration order and with field types;
- the `Cfg` variants, in declaration order and with field types; and
- the parameters after `self` in `Platform::matches`, in declaration order and with complete name/type pairs.

The required output format is deliberately exact: the heading and labels remain unchanged, and each answer is a comma-separated list of inline-code items. The agent must not change `Cargo.toml` or create additional files.

The prompt does not mention the skill, the comparison, hidden checks, or the expected command. The task is intentionally narrow so that the first experiment evaluates framework integration rather than long-horizon agent performance.

After the agent exits, the deterministic scorer compares the completed file with a grader-owned known-good answer. The answer is not present while the agent is working. The main success result is the exact-content score, not the agent's prose response.

The scorer also reads a fixture-owned invocation log. The `cargo-agents` fixture shim records exact invocations before resolving the requested crate source. This is instrumentation for the evaluation; it is not a test double for Symposium product behavior.

## Evidence

Every run should retain these fields in Inspect's native log and export the normalized subset:

- condition, pair, phase, and run identifier;
- fixture, prompt, skill, model, agent, and framework versions;
- deterministic task score and the observed file used by the scorer;
- total time and working time;
- input, cache-read, cache-write, and output tokens when the provider reports them;
- total cost when Inspect can report it;
- whether `cargo agents crate-info cargo-platform` was invoked;
- all recorded `cargo agents` invocations; and
- terminal status: `passed`, `failed`, `infrastructure_error`, or `unavailable`.

Capability evidence has three levels:

1. **Available**: the treatment configuration supplied the skill.
2. **Invoked**: the exact command described by the skill appears in the fixture log.
3. **Observed by agent telemetry**: a structured skill-load or tool event exists.

The spike requires the first two. The third is recorded when Inspect or Claude exposes it reliably, but its absence does not invalidate the initial experiment.

## Safety and limits

Planning is the default command. A provider call requires an API key and an explicit `--confirm-paid-run` flag.

The provisional ceilings are:

- one user turn per run;
- at most four provider requests;
- a target of at most three tool calls;
- 26,000 total metered tokens;
- 1,000 output tokens;
- ten minutes per run;
- $0.35 per run; and
- $3.00 across the complete eight-run smoke and measured sequence.

Inspect enforces per-sample token, output-token, time, and cost limits. A small generation filter enforces provider-request count. With the pinned APIs, Claude Code built-in tool calls can be counted from events but not stopped at a hard count before execution; the spike records this as a framework gap. The wrapper must refuse a phase whose declared maximum would exceed the experiment-wide ceiling. Paid failures are never retried automatically. A terminal error in one condition stops the phase before the other condition launches. Credential and billing preconditions retain terminal `status: unavailable` and a more specific `error_kind`; framework and agent runtime failures use `status: infrastructure_error`.

Secrets and complete agent homes must not enter the normalized JSON result. Inspect's full logs remain local and should be treated as potentially sensitive transcripts.

## Prototype layout

The disposable implementation lives under `prototypes/skill-effectiveness-eval/`:

```text
experiment.toml       pinned conditions, phases, paths, and budgets
run.py                stable executable shim
skill_eval/           typed planning, preparation, execution, results, and report package
eval_task.py          compatibility imports for Inspect task builders
fixture/              files visible to the coding agent
grader/known-good.md   grader-owned exact answer
bin/cargo              minimal command dispatcher used by the fixture
bin/cargo-agents      capability-instrumentation shim
Dockerfile            reproducible execution image
compose.yaml          Inspect Docker sandbox configuration
scripts/              pinned, resumable Claude Code downloader
tests/                offline orchestration and result regressions
README.md             linear takeover procedure
NOTES.md               observations and framework-fit verdict
```

The default command must be safe and free:

```console
uv run --project prototypes/skill-effectiveness-eval python prototypes/skill-effectiveness-eval/run.py plan
```

The idempotent preparation command is free and must pass before a provider run:

```console
uv run --project prototypes/skill-effectiveness-eval python prototypes/skill-effectiveness-eval/run.py prepare
```

It verifies or downloads the pinned agent binary, then runs the untouched and
known-good files through the same scorer in separate Docker sandboxes. Expected
results are `I` and `C`. Paid commands require current fingerprinted evidence of
those results.

Paid phases are explicit:

```console
uv run --project prototypes/skill-effectiveness-eval python prototypes/skill-effectiveness-eval/run.py smoke --confirm-paid-run
uv run --project prototypes/skill-effectiveness-eval python prototypes/skill-effectiveness-eval/run.py measured --confirm-paid-run
```

## Handoff-completion design

The prototype now provides a checkout-to-smoke path with no undocumented setup:

1. A free, idempotent `prepare` command verifies Docker, builds a minimal
   downloader image, populate Inspect SWE's user cache with the pinned Claude
   Code binary when necessary, verify its size and SHA-256, and run both grader
   controls. It will never read a provider key or contact a model API.
2. The existing `plan` command remains the non-mutating readiness view. Its
   output will distinguish assets, local executables, credentials, and the
   unobservable funded-account requirement.
3. Offline pytest regressions cover typed configuration, deterministic pair
   ordering, prerequisite-independent planning, scoped process state, cumulative
   budget transitions, billing/authentication/provider failure classification,
   terminal phase stopping, portable result normalization, and report deltas.
   These tests do not require Docker or provider credentials.
4. A free `report` command turns normalized results into a Markdown evidence
   report containing run status, scores, usage, timing, capability invocation,
   and pair deltas. It will state which smoke gates are supported by evidence but
   will not choose the framework verdict automatically.
5. The README reduces takeover to `prepare`, setting a funded API key,
   `smoke --confirm-paid-run`, reviewing the generated report, and—only after the
   smoke gates pass—running `measured --confirm-paid-run`.

The downloader cache and all Inspect logs remain outside version control. The
wrapper does not print secrets, and the normalized result and report omit
messages, transcripts, tracebacks, and authentication material. The handoff
commit includes only the research chapter, prototype source, fixtures, tests,
and lockfile; unrelated working-tree files are excluded.

Completion of this local work does not manufacture experimental evidence. A
funded smoke pair, the conditional measured pairs, and the final adoption verdict
remain empirical steps for the person holding funded provider access.

## Work packages

### 1. Offline skeleton

- Define the pinned experiment configuration.
- Construct baseline and treatment plans without importing credentials.
- Refuse paid execution without explicit confirmation.
- Validate that task, skill, grader, and sandbox assets exist.
- Export a machine-readable plan.

Acceptance: `run.py plan` succeeds without Docker or a provider key and makes every planned difference visible.

### 2. Sandbox and scorer

- Build the fixture image with the pinned crate source and required agent tools.
- Verify that every sample gets a fresh writable workspace.
- Keep the grader-owned answer unavailable until scoring.
- Verify exact capability invocation recording.

Acceptance: the grader-owned known-good notes pass, untouched notes fail, and repeated sandboxes do not share changes.

### 3. Inspect SWE integration

- Launch pinned Claude Code through the public `claude_code()` agent API.
- Supply the skill only in the treatment condition.
- Confirm that Inspect captures provider usage, task timing, and tool events.
- Classify missing Docker, credentials, usage accounting, or agent support as `unavailable` or `infrastructure_error`, not task failure.

Acceptance: one explicitly confirmed smoke pair completes without changing any non-condition input.

### 4. Measured comparison

- Run three fresh pairs with recorded randomized order.
- Export normalized JSON.
- Compare success, tokens, duration, and capability use per pair.
- Inspect outliers and environmental errors before interpreting averages.

Acceptance: all six measured attempts are present, including failures, and can be traced back to their Inspect logs.

### 5. Framework verdict

Fill in this scorecard with implementation evidence:

| Need | Inspect provides | Thin glue | Missing or unsuitable |
|---|---|---|---|
| External coding-agent execution |  |  |  |
| Fresh isolated workspace |  |  |  |
| Deterministic post-run scorer |  |  |  |
| Token, cost, and duration accounting |  |  |  |
| Paired baseline/treatment scheduling |  |  |  |
| Skill and plugin-use evidence |  |  |  |
| Repetition and failure retention |  |  |  |
| Portable result export |  |  |  |
| Local developer ergonomics |  |  |  |

Recommend one outcome:

- **Adopt**: keep Inspect behind a small Symposium-owned interface.
- **Do not adopt**: build a smaller native harness and reuse only ideas or result formats.
- **Run one more bounded spike**: only when a named uncertainty cannot be answered by this case.

The verdict must include approximate adapter code size, setup steps, cold and warm runtime, observed spend, known sources of contamination, and which claims remain untested.

## Current implementation evidence and blocker

On Windows with Docker Desktop 4.84.0 and Engine 29.6.2, the lightweight sandbox image built successfully. The CLI was installed outside `PATH`, so the wrapper now discovers standard Windows Docker Desktop locations. Inspect then ran the untouched and known-good controls in separate Compose sandboxes. The exact-content scorer returned `I` for untouched notes and `C` for the known-good answer. Inspect warned that its optional control server could not use `AF_UNIX` on Windows and continued without that surface; this did not prevent either evaluation.

Cold setup was material. The current pinned Python environment contains 88 packages. An initial Rust-toolchain image was intentionally abandoned because compilation was outside the task and its 280 MB base layer downloaded too slowly. The replacement Debian image downloaded a 28 MB base layer and 24 MB of packages, then reused cached layers. Its base digest and crate archive checksum are pinned. The first two trivial control samples took approximately 1 minute 26 seconds and 2 minutes 17 seconds according to Inspect; a later cached run took 38 seconds and 1 minute 11 seconds and produced the same `I` and `C` scores.

Inspect SWE's default five-second download timed out against the 339 MB Claude Code artifact. The prototype therefore caches a checksum-pinned Claude Code 2.1.238 binary and copies it into each Linux sandbox. With that workaround, attempt `smoke-20260825T130119Z` launched Claude Code and Inspect's provider bridge without patching either framework. Anthropic rejected both forwarded baseline requests with HTTP 400 because the API account had insufficient credit. Claude Code reported zero tokens and $0.00; the treatment was stopped before making a request. The exporter records this as `status: unavailable` with `error_kind: billing_error`.

On 2026-08-28, the completed `prepare` path verified the cached binary and reran
both controls end to end: untouched returned `I` and known-good returned `C`.
The final pre-refactor fingerprinted run took 25 and 22 seconds. The refactored
suite has 24 offline regressions covering typed configuration, planning, binary
verification and download orchestration, scoped process state, cumulative budget
accounting, failure classification, phase stopping, control fingerprints,
secret-minimized normalization, report gates, and pair deltas. The generated
report correctly marks the retained billing-only attempt as not smoke-ready.

The remaining blocker is funded Anthropic API access, not key discovery. Until a funded smoke pair completes, successful generation, nonzero usage accounting, treatment-skill delivery, and capability invocation remain unverified; no adoption verdict is justified.

## References

- [Agent Skills: Evaluate skills](https://agentskills.io/skill-creation/evaluating-skills)
- [Inspect tutorial: coding agents](https://inspect.aisi.org.uk/tutorial.html#coding-agents)
- [Inspect datasets and per-sample files](https://inspect.aisi.org.uk/datasets.html#sample-files)
- [Inspect sandboxing](https://inspect.aisi.org.uk/sandboxing.html)
- [Inspect scorers with sandbox access](https://inspect.aisi.org.uk/multiple-scorers.html#sandbox-access)
- [Inspect evaluation logs](https://inspect.aisi.org.uk/eval-logs.html)
- [Inspect SWE Claude Code reference](https://meridianlabs-ai.github.io/inspect_swe/reference/#inspect_swe.claude_code)
