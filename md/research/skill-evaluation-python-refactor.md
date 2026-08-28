# Skill-evaluation prototype Python refactor

Status: approved design; implementation pending (2026-08-28)

This document describes a focused maintainability and correctness refactor of
the disposable skill-effectiveness evaluation prototype. It does not change the
experiment, add a production Symposium command, or authorize provider calls.

## Motivation

The prototype proved that Inspect can launch the agent bridge, isolate task
workspaces, run deterministic controls, retain native logs, and export portable
evidence. Its Python wrapper is nevertheless difficult to hand off:

- `run.py` owns configuration, preparation, planning, execution, normalization,
  reporting, and command dispatch in one 907-line module;
- configuration and result records are mostly `dict[str, Any]`, so malformed
  inputs fail late and obscurely;
- execution changes the process working directory and environment without
  scoped restoration;
- the experiment ceiling is checked against one command's declared maximum,
  not earlier paid attempts; and
- tests cover helpers more thoroughly than orchestration behavior.

The refactor should make the wrapper understandable to a Python maintainer while
preserving its existing operator-facing commands and experiment semantics.

## Goals

1. Keep `run.py plan`, `prepare`, `controls`, `smoke`, `measured`, `summarize`,
   and `report` compatible with the documented takeover sequence.
2. Give each module one cohesive responsibility and keep the package shallow.
3. Validate TOML and retained JSON at their boundaries and use typed records
   internally.
4. Restore process-wide state after temporary working-directory or environment
   changes.
5. enforce the experiment cost ceiling across repeated attempts, including a
   conservative reservation for an interrupted command.
6. Make important orchestration behavior testable without Docker, Inspect, or a
   provider key.
7. Establish repeatable formatting, linting, and static-type checks.

## Non-goals

- Generalizing the prototype to multiple agents, models, or task formats.
- Replacing Inspect or changing the experimental treatment.
- Introducing a framework such as Pydantic solely for configuration parsing.
- Hiding Inspect behind a production-quality Symposium abstraction.
- Running a funded smoke or measured phase as part of this refactor.
- Rewriting every test only to change its test framework.

## Package structure

`run.py` remains a tiny executable shim that calls `skill_eval.cli.main`. The
implementation moves into a shallow `skill_eval` package:

```text
skill_eval/
  __init__.py       package marker; no eager framework imports
  cli.py            argument parsing and command dispatch
  config.py         TOML parsing, validation, paths, and immutable settings
  models.py         shared enums, dataclasses, protocols, and JSON types
  planning.py       paired run order and experiment-wide budget accounting
  environment.py    Docker discovery and verified agent-binary preparation
  tasks.py          Inspect tasks, solvers, request filter, and scorers
  execution.py      controls and paid-phase orchestration
  results.py        Inspect-log normalization and failure classification
  reporting.py      evidence gates, pair comparisons, and Markdown rendering
```

Modules may depend on `config` and `models`. Higher-level orchestration may
depend on lower-level modules, but configuration, models, planning, results, and
reporting must not import the CLI. Inspect imports remain close to the task,
execution, and log-reading boundaries so that `plan --help` and pure tests do not
need to initialize the framework.

`eval_task.py` becomes a compatibility shim during the refactor or is removed
after all internal imports and documentation point to `skill_eval.tasks`. No
external API is promised for either Python module.

## Typed boundaries

`config.load_config()` converts the TOML document into frozen dataclasses. It
validates required tables, supported phases and conditions, positive limits,
the SHA-256 shape, and paths before returning an `ExperimentConfig`. Validation
errors name the offending field and terminate the CLI without a traceback.

The code uses dataclasses for planned runs, prerequisites, controls, budget
entries, and normalized runs. `TypedDict` is reserved for JSON documents whose
dictionary representation is itself the interface. Protocols describe injected
subprocess and evaluation callables. `Any` remains only at explicitly dynamic
Inspect serialization boundaries.

Retained control and budget JSON must decode to an object with the expected
schema version and field types. Missing, malformed, or stale evidence fails
closed; it never becomes an attribute error or an implicit pass.

## Process and subprocess boundaries

Temporary process state is managed with context managers. A working-directory
context always restores the caller's directory in `finally`. Environment
changes needed by Docker discovery and Inspect SWE are applied for the smallest
possible scope and restored afterward. Subprocesses continue to receive argument
lists and never use `shell=True`.

The agent binary version, filename, size, and checksum remain authoritative in
`experiment.toml`. The downloader script accepts those values as arguments from
the Python wrapper instead of duplicating them. Both the downloader and Python
verification still check the complete size and SHA-256.

## Cumulative budget accounting

The ignored artifact `artifacts/budget.json` is a conservative local ledger. A
paid phase performs these steps before the first provider request:

1. Load and validate the ledger and reconcile completed entries with retained
   normalized Inspect usage where possible.
2. Compute committed spend as observed completed cost plus unresolved
   reservations.
3. Reserve the full per-run ceiling for every planned run in the new attempt.
4. Refuse the attempt when committed spend plus its reservation exceeds the
   experiment ceiling.

After each Inspect evaluation returns, the current run's reservation is replaced
with its observed cost. Unlaunched runs are cancelled when the wrapper handles a
terminal failure. An unexpected interruption deliberately leaves an unresolved
reservation, making the next paid command fail closed instead of silently
assuming that the interrupted provider call was free. The ledger contains no
credentials, prompts, messages, or transcripts.

Planning reports observed cost, active reservations, and the remaining declared
budget. Free commands never create a reservation. Offline tests use an isolated
ledger and do not contact a provider.

## Result and report correctness

Failure classification uses Inspect event types at the framework boundary rather
than dynamically fabricated class-name strings. The normalized result remains a
secret-minimized JSON document and does not add messages or tracebacks.

A task delta is rendered only when both runs have a recognized deterministic
score (`C` or `I`). Missing or invalid scores render `-`; they are not converted
to an incorrect task result. Markdown table cells derived from retained data are
escaped before rendering.

## Test strategy

The suite keeps a small number of subprocess-level CLI tests and moves most
coverage to public module behavior. Tests use temporary paths and scoped
environment changes. Required regressions include:

- deterministic paired planning;
- clear rejection of malformed TOML and control JSON;
- restoration of working directory and environment after success and failure;
- downloader arguments coming from the parsed binary pin;
- cumulative reservations blocking an over-budget retry;
- completed and cancelled reservations updating the remaining budget;
- paid orchestration stopping before the next condition after a terminal error;
- typed failure classification at the Inspect adapter boundary;
- normalization excluding transcripts, tracebacks, and authentication material;
- report gates and deltas refusing incomplete score evidence; and
- existing free CLI commands retaining their documented behavior.

Docker controls remain the integration check for the sandbox and scorer. The
refactor does not run paid phases. Because changing the runner invalidates the
control fingerprint, `prepare` must regenerate free control evidence before the
prototype is handed off again.

## Tooling and quality gate

The prototype adds development dependencies for Ruff, mypy, and pytest. Ruff is
the formatter and linter; mypy runs in strict mode for the `skill_eval` package,
with narrow third-party overrides only where Inspect lacks usable annotations.
Tests may remain in `unittest` style where conversion adds no value, but new
behavioral tests use pytest fixtures and parametrization.

The implementation is complete when all of these succeed:

```console
uv run --project prototypes/skill-effectiveness-eval ruff format --check prototypes/skill-effectiveness-eval
uv run --project prototypes/skill-effectiveness-eval ruff check prototypes/skill-effectiveness-eval
uv run --project prototypes/skill-effectiveness-eval mypy prototypes/skill-effectiveness-eval/skill_eval
uv run --project prototypes/skill-effectiveness-eval pytest prototypes/skill-effectiveness-eval/tests
uv run --project prototypes/skill-effectiveness-eval python prototypes/skill-effectiveness-eval/run.py prepare
uv run --project prototypes/skill-effectiveness-eval python prototypes/skill-effectiveness-eval/run.py plan
mdbook build
```

The first four checks are offline after dependency synchronization. `prepare`
may use Docker and the already pinned downloader source, but it must not contact
a model provider. Existing mdbook warnings unrelated to this prototype are
recorded rather than hidden.

## Migration and handoff

The refactor is performed behind the existing CLI and ignored artifact paths.
Existing Inspect logs remain readable. Existing `controls.json` becomes stale by
design because the fingerprinted implementation changed; `prepare` regenerates
it. If an old checkout has no budget ledger, the first paid command creates one
after inspecting retained normalized costs and then reserves the new attempt.

The README and the main framework-spike chapter will describe the new package,
quality commands, budget behavior, and free control regeneration. The final
handoff should state both what was mechanically verified and what still requires
a funded Anthropic account.
