use anyhow::{Context, Result};
use std::fs;
use symposium_testlib::{TestMode, with_fixture};

const CARGO_CALL_LOG: &str = ".symposium-cargo-calls";
const RECORDING_CARGO: &str = r#"#!/bin/sh
printf '%s\n' "$1" >> .symposium-cargo-calls
exec cargo "$@"
"#;

#[tokio::test]
async fn cache_miss_runs_cargo_once_and_is_memoized() -> Result<()> {
    with_fixture(
        TestMode::SimulationOnly,
        &["workspace-cache0"],
        async |mut context| {
            context.set_mock_cargo(RECORDING_CARGO);
            let workspace = context
                .workspace_root
                .as_deref()
                .context("workspace-cache0 must provide a workspace root")?;
            let resolver = context.sym.workspace_deps(workspace);
            let call_log = workspace.join(CARGO_CALL_LOG);

            assert!(
                resolver.load().is_some(),
                "initial workspace dependency load failed; Cargo calls:\n{}",
                fs::read_to_string(&call_log).unwrap_or_else(|error| format!("<{error}>"))
            );
            assert!(
                resolver.load().is_some(),
                "memoized workspace dependency load failed"
            );

            let calls = fs::read_to_string(&call_log)
                .with_context(|| format!("reading Cargo call log `{}`", call_log.display()))?;
            assert_eq!(calls, "locate-project\nmetadata\n");

            Ok(())
        },
    )
    .await
}
