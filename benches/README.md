# Symposium benchmarks

This directory contains Symposium's focused performance benchmarks, checked-in workloads, and shared benchmark support. The suite is developed incrementally: every target should be independently runnable and have a clearly documented interpretation.

See the [benchmarking design](../md/design/benchmarking.md) for the suite architecture, measurement policy, CI strategy, and lifecycle criteria.

## Layout

- `benchsuite/` is the non-publishable workspace package containing benchmark targets and shared support code.
- `fixtures/` contains the composable deterministic workloads described in its own [README](fixtures/README.md).

Shared support code handles fixtures and sandbox mechanics. Each benchmark target is responsible for defining its own scenarios and timed operations.

## Current targets

No benchmark targets have been implemented yet. Each target will be added here when it becomes independently runnable.

## Commands

Run commands from the repository root:

```text
cargo check -p symposium-benchsuite --all-targets
cargo test -p symposium-benchsuite --lib
```

## Benchmark contracts

Every benchmark target documents its measurement contract in the crate-level doc comment next to the implementation. This README acts as an index and does not duplicate those contracts.

## Lifecycle

New benchmarks begin as `experimental`. Measurements remain informational until sufficient history demonstrates that a benchmark is stable enough to become `observed` or `gated`.
