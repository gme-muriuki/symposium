# Skill-effectiveness evaluation prototype

> **PROTOTYPE:** this directory is disposable. It exists to decide whether Inspect AI is a suitable execution engine; it is not a supported Symposium command.

This prototype compares the same Claude Code source-inspection task with and
without the repository's `find-crate-source` skill. The task edits Markdown; it
does not compile or test Rust code. Inspect owns agent execution, sandbox
lifecycle, limits, native logs, and scoring. `run.py` supplies paired scheduling,
guarded execution, normalized results, and an evidence report.

The full handoff specification is in [the mdbook research chapter](../../md/research/skill-effectiveness-framework-spike.md).

## Takeover sequence

The person taking this over needs `uv`, a running Docker Desktop or Docker Engine,
and a funded Anthropic API account. They do not need a Rust toolchain.

From the repository root, run the free preparation command:

```console
uv run --project prototypes/skill-effectiveness-eval python prototypes/skill-effectiveness-eval/run.py prepare
```

`prepare` is idempotent. It builds a small downloader image only when the pinned
Claude Code 2.1.238 binary is absent, downloads the 339 MB artifact in resumable
parallel ranges, verifies its complete size and SHA-256, and runs the untouched
and known-good grader controls. It writes fingerprinted control evidence under
the ignored `artifacts/` directory. A paid run is refused when that evidence is
missing, failed, or stale because a graded input changed.

Inspect readiness without making a provider request:

```console
uv run --project prototypes/skill-effectiveness-eval python prototypes/skill-effectiveness-eval/run.py plan
```

Planning prints both conditions, validates local assets and controls, and reports
Docker, binary, and key availability. It deliberately reports API account funding
as unverified because Anthropic exposes insufficient credit only in a provider
response.

Set `ANTHROPIC_API_KEY` in the shell from a funded Claude Platform workspace, then
run only the smoke pair:

```console
uv run --project prototypes/skill-effectiveness-eval python prototypes/skill-effectiveness-eval/run.py smoke --confirm-paid-run
```

The declared maximum is $0.70: two conditions at $0.35 each. The wrapper disables
automatic paid retries and stops the phase after a terminal credential, billing,
provider, framework, or agent failure.

Render the portable evidence report:

```console
uv run --project prototypes/skill-effectiveness-eval python prototypes/skill-effectiveness-eval/run.py report
```

Do not run the measured phase unless the report says `Smoke readiness: PASS`.
This gate means the comparison is interpretable; it does not require both task
scores to pass and does not choose the framework verdict. If the gate passes:

```console
uv run --project prototypes/skill-effectiveness-eval python prototypes/skill-effectiveness-eval/run.py measured --confirm-paid-run
uv run --project prototypes/skill-effectiveness-eval python prototypes/skill-effectiveness-eval/run.py report
```

The measured phase declares a separate maximum of $2.10. Use its pair table to
finish the framework-fit scorecard and choose `Adopt`, `Do not adopt`, or one
narrowly named follow-up spike in `NOTES.md`.

## Supporting commands

Run the controls without downloading the binary again:

```console
uv run --project prototypes/skill-effectiveness-eval python prototypes/skill-effectiveness-eval/run.py controls
```

Regenerate `artifacts/results.json` from retained Inspect logs, then regenerate
the report:

```console
uv run --project prototypes/skill-effectiveness-eval python prototypes/skill-effectiveness-eval/run.py summarize
uv run --project prototypes/skill-effectiveness-eval python prototypes/skill-effectiveness-eval/run.py report
```

Run the offline regression suite:

```console
uv run --project prototypes/skill-effectiveness-eval python -m unittest discover -s prototypes/skill-effectiveness-eval/tests -v
```

## Safety and artifacts

No paid command is intended for CI. Do not raise limits merely to produce a
passing result; reduce the task and agent context first. A Claude subscription
and an API key do not themselves provide API credits.

If a run ends because credentials or billing are unavailable, the wrapper stops
the phase before launching the other condition. `summarize` records the run as
`status: unavailable` and distinguishes `billing_error` from
`authentication_error` in `error_kind`.

Inspect's `.eval` logs may contain full transcripts and should remain local.
`artifacts/`, `.venv/`, and caches are ignored. The normalized JSON retains only
an error summary—not tracebacks—and the Markdown report selects known evidence
fields rather than copying arbitrary log content.

The grader-owned `grader/known-good.md` is unavailable to the agent. It proves
that the exact-match scorer fails the untouched fixture and passes a known-correct
answer before any provider run.
