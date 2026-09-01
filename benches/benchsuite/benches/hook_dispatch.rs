//! Unchanged-workspace hook dispatch benchmarks.
//!
//! `PreToolUse` fires once per agent tool call, so its latency is the cost a
//! user feels most often. Preparation asserts every property a measurement
//! depends on, so
//! `cargo test -p symposium-benchsuite --bench hook_dispatch` is a correctness
//! preflight for the dispatch path.

use std::path::{Path, PathBuf};

use anyhow::{Context, Result, ensure};
use criterion::{Criterion, criterion_group, criterion_main};
use indoc::indoc;
use serde_json::{Value, json};
use tokio::runtime::{Builder, Runtime};

use symposium::{
    config::Symposium,
    hook::{self, HookAgent, HookEvent},
    plugins,
    workspace_state::WorkspaceState,
};
use symposium_benchsuite::{Fixture, MetadataRejectingCargo, Sandbox, StagedFixture};

/// Both builtin registries default to enabled, so the minimal case has to
/// switch them off rather than omit them.
const MINIMAL_CONFIG: &str = indoc! {r#"
    [defaults]
    symposium-recommendations = false
    user-plugins = false
"#};

/// Construction checks every property a measurement depends on, so a broken
/// setup fails the run rather than shortening a sample.
struct HookDispatchWorkload {
    sandbox: Sandbox,
    symposium: Symposium,
    runtime: Runtime,
    input: String,
}

impl HookDispatchWorkload {
    fn prepare_minimal() -> Result<Self> {
        let sandbox = Sandbox::new()?;
        let project = sandbox.stage(Fixture::ReferenceProject)?;
        sandbox.write_config(MINIMAL_CONFIG)?;

        // `from_dir` reads `config.toml` eagerly, so it has to exist by now.
        let symposium = Symposium::from_dir(sandbox.config_dir());
        // The pipeline awaits subprocesses; a worker pool would only add noise.
        let runtime = Builder::new_current_thread()
            .enable_all()
            .build()
            .context("building the benchmark Tokio runtime")?;

        let workspace_root = warm_workspace_cache(&symposium, &project)?;
        mark_workspace_synced(&symposium, &workspace_root)?;

        let input = pre_tool_use_payload(project.path())?;
        let workload = Self {
            sandbox,
            symposium,
            runtime,
            input,
        };

        workload.verify_minimal_configuration(&project)?;
        workload.verify_dispatch()?;

        Ok(workload)
    }

    /// The operation a timed case measures. `symposium` is a parameter so a
    /// preflight can substitute a guarded Cargo.
    fn dispatch_with(&self, symposium: &Symposium) -> Result<Vec<u8>> {
        self.runtime.block_on(async {
            hook::execute_hook(
                symposium,
                HookAgent::Claude,
                HookEvent::PreToolUse,
                &self.input,
            )
            .await
            .context("dispatching the PreToolUse hook")
        })
    }

    /// Prove the configuration this case describes is the one in effect.
    ///
    /// Each check covers a way the workload looks fine while measuring less:
    /// auto-sync off returns before the workspace lookup, a misplaced config
    /// leaves the builtin registries enabled but empty, and an unresolved
    /// workspace skips plugin discovery. The last two both end in zero plugins.
    fn verify_minimal_configuration(&self, project: &StagedFixture) -> Result<()> {
        ensure!(
            self.symposium.config.auto_sync,
            "the minimal workload requires auto-sync to be enabled"
        );

        let registries = self.symposium.registry_instances();
        ensure!(
            registries.is_empty(),
            "the minimal configuration resolved {} registry instance(s); expected none",
            registries.len()
        );

        let resolver = self.symposium.workspace_deps(project.path());
        let workspace = resolver
            .load()
            .context("loading the prepared workspace disk cache")?;
        let registry = self.runtime.block_on(plugins::load_registry_with_workspace(
            &self.symposium,
            Some(workspace),
        ));

        let names: Vec<_> = registry
            .plugins
            .iter()
            .map(|parsed| parsed.plugin.name.as_str())
            .collect();
        ensure!(
            names.is_empty(),
            "the minimal configuration loaded plugins: [{}]",
            names.join(", ")
        );
        ensure!(
            registry.warnings.is_empty(),
            "the minimal configuration produced {} plugin load warning(s)",
            registry.warnings.len()
        );

        Ok(())
    }

    /// Dispatch once through a Cargo that refuses `metadata`.
    ///
    /// Refusal alone proves nothing: a failed `metadata` becomes "no workspace",
    /// which dispatch accepts and still returns `{}` for. The marker is what
    /// separates reading the disk cache from re-resolving and discarding.
    fn verify_dispatch(&self) -> Result<()> {
        let guard = MetadataRejectingCargo::create_in(self.sandbox.root())?;
        let mut guarded = Symposium::from_dir(self.sandbox.config_dir());
        guarded.set_cargo_override(guard.executable().to_path_buf());

        let output = self.dispatch_with(&guarded)?;

        ensure!(
            !guard.saw_metadata()?,
            "the unchanged path ran `cargo metadata` instead of reading the \
             workspace disk cache"
        );

        let output: Value =
            serde_json::from_slice(&output).context("parsing the hook output as JSON")?;
        ensure!(
            output == json!({}),
            "expected a no-op hook output, found `{output}`"
        );

        Ok(())
    }
}

/// Validate the resolved graph and leave a warm disk cache behind.
fn warm_workspace_cache(symposium: &Symposium, project: &StagedFixture) -> Result<PathBuf> {
    let resolver = symposium.workspace_deps(project.path());
    let workspace = resolver.load().with_context(|| {
        format!(
            "resolving the staged benchmark workspace `{}`",
            project.path().display()
        )
    })?;

    project.check_workspace(workspace)?;

    Ok(workspace.root.clone())
}

/// `run_auto_sync` skips its work only when recorded state says the workspace
/// is unchanged; without this the dispatch measures a full sync instead. The
/// recorded root mirrors what a real sync writes.
fn mark_workspace_synced(symposium: &Symposium, workspace_root: &Path) -> Result<()> {
    let mut state = WorkspaceState::load(symposium, workspace_root);
    state.record_sync(workspace_root);
    state.workspace_root = Some(workspace_root.to_path_buf());
    state.save(symposium, workspace_root);

    ensure!(
        WorkspaceState::load(symposium, workspace_root).sync_is_fresh(workspace_root),
        "recorded workspace state did not reload as fresh for `{}`",
        workspace_root.display()
    );

    Ok(())
}

/// `cwd` is load-bearing: `execute_hook` falls back to the working directory of
/// the process, which for a bench binary is the Symposium workspace itself.
fn pre_tool_use_payload(project: &Path) -> Result<String> {
    let project = project
        .to_str()
        .with_context(|| format!("staged project path is not UTF-8: {}", project.display()))?;
    let payload = json!({
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "cwd": project,
        "session_id": "benchmark",
        "tool_input": { "command": "true" },
    });

    serde_json::to_string(&payload).context("serializing the PreToolUse payload")
}

fn benchmark_hook_dispatch(_criterion: &mut Criterion) {
    let _workload = HookDispatchWorkload::prepare_minimal()
        .expect("preparing the minimal hook dispatch workload");
}

criterion_group!(benches, benchmark_hook_dispatch);
criterion_main!(benches);
