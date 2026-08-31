//! Unchanged-workspace hook dispatch benchmarks.

use criterion::{Criterion, criterion_group, criterion_main};

fn benchmark_hook_dispatch(_: &mut Criterion) {}

criterion_group!(benches, benchmark_hook_dispatch);
criterion_main!(benches);
