//! Shared fixture and sandbox support for Symposium benchmarks.

use anyhow::{Context, Result, bail, ensure};
use std::{
    fs,
    path::{Path, PathBuf},
};
use tempfile::{Builder, TempDir};

#[derive(Debug)]
pub enum Fixture {
    ReferenceProject,
    LocalRegistry,
}

impl Fixture {
    pub fn source_dir(&self) -> Result<PathBuf> {
        let directory = self.directory_name();
        let path = fixtures_root().join(directory);

        ensure!(
            path.is_dir(),
            "benchmark fixture `{directory}` is missing: {}",
            path.display()
        );

        Ok(path)
    }

    pub fn copy_to(&self, destination: impl AsRef<Path>) -> Result<()> {
        let source = self.source_dir()?;
        copy_directory(&source, destination.as_ref())
    }

    fn directory_name(&self) -> &'static str {
        match self {
            Self::ReferenceProject => "reference-project",
            Self::LocalRegistry => "local-registry",
        }
    }
}

/// Isolated filesystem state for a benchmark workload.
#[derive(Debug)]
pub struct Sandbox {
    root: TempDir,
    config_dir: PathBuf,
    cache_dir: PathBuf,
}

impl Sandbox {
    pub fn new() -> Result<Self> {
        let root = Builder::new()
            .prefix("symposium-benchmark-")
            .tempdir()
            .context("creating benchmark sandbox")?;
        let config_dir = root.path().join("symposium-home");
        let cache_dir = config_dir.join("cache");

        fs::create_dir_all(&cache_dir).with_context(|| {
            format!(
                "creating benchmark sandbox directories under `{}`",
                root.path().display()
            )
        })?;

        Ok(Self {
            root,
            config_dir,
            cache_dir,
        })
    }

    pub fn stage_fixture(&self, fixture: &Fixture) -> Result<PathBuf> {
        let destination = self.root().join(fixture.directory_name());
        fixture.copy_to(&destination)?;
        Ok(destination)
    }

    /// Remove the sandbox's workspace dependency caches.
    pub fn clear_workspace_cache(&self) -> Result<()> {
        let workspace_cache = self.cache_dir.join("workspaces");

        match fs::remove_dir_all(&workspace_cache) {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(error) => Err(error).with_context(|| {
                format!(
                    "removing benchmark workspace cache `{}`",
                    workspace_cache.display()
                )
            }),
        }
    }

    pub fn root(&self) -> &Path {
        self.root.path()
    }

    pub fn config_dir(&self) -> &Path {
        &self.config_dir
    }

    pub fn cache_dir(&self) -> &Path {
        &self.cache_dir
    }
}

fn copy_directory(source: &Path, destination: &Path) -> Result<()> {
    fs::create_dir(destination).with_context(|| {
        format!(
            "creating fixture destination directory `{}`",
            destination.display()
        )
    })?;

    for entry in source
        .read_dir()
        .with_context(|| format!("reading fixture directory `{}`", source.display()))?
    {
        let entry = entry.with_context(|| format!("reading an entry in `{}`", source.display()))?;
        copy_entry(&entry, destination)?;
    }

    Ok(())
}

fn copy_entry(entry: &fs::DirEntry, destination_directory: &Path) -> Result<()> {
    let source = entry.path();
    let destination = destination_directory.join(entry.file_name());
    let file_type = entry
        .file_type()
        .with_context(|| format!("reading file type for `{}`", source.display()))?;

    if file_type.is_dir() {
        copy_directory(&source, &destination)
    } else if file_type.is_file() {
        fs::copy(&source, &destination).with_context(|| {
            format!(
                "copying fixture file `{}` to `{}`",
                source.display(),
                destination.display()
            )
        })?;
        Ok(())
    } else {
        bail!(
            "fixture contains an unsupported filesystem entry: {}",
            source.display()
        )
    }
}

fn fixtures_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("benchsuite must be inside the benches directory")
        .join("fixtures")
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn finds_reference_project_fixture() -> Result<()> {
        let source_dir = Fixture::ReferenceProject.source_dir()?;
        let manifest = source_dir.join("Cargo.toml");

        assert!(
            manifest.is_file(),
            "reference project manifest is missing: {}",
            manifest.display()
        );

        Ok(())
    }

    #[test]
    fn finds_local_registry_fixture() -> Result<()> {
        let source_dir = Fixture::LocalRegistry.source_dir()?;
        let manifest = source_dir.join("always-active").join("SYMPOSIUM.toml");

        assert!(
            manifest.is_file(),
            "local registry anchor manifest is missing: {}",
            manifest.display()
        );

        Ok(())
    }

    #[test]
    fn copies_reference_project_fixture() -> Result<()> {
        let temporary_directory = tempdir()?;
        let destination = temporary_directory.path().join("reference-project");

        Fixture::ReferenceProject.copy_to(&destination)?;

        assert!(destination.join("Cargo.toml").is_file());
        assert!(destination.join("domain/src/lib.rs").is_file());

        Ok(())
    }

    #[test]
    fn refuses_to_merge_into_an_existing_destination() -> Result<()> {
        let temporary_directory = tempdir()?;
        let destination = temporary_directory.path().join("reference-project");
        let sentinel = destination.join("sentinel");

        fs::create_dir(&destination)?;
        fs::write(&sentinel, "leave me untouched")?;

        let error = Fixture::ReferenceProject
            .copy_to(&destination)
            .expect_err("copying into an existing destination must fail");
        let message = error.to_string();

        assert!(
            message.contains(&destination.display().to_string()),
            "error does not name destination `{}`: {error:#}",
            destination.display()
        );
        assert_eq!(fs::read_to_string(sentinel)?, "leave me untouched");
        assert!(!destination.join("Cargo.toml").try_exists()?);

        Ok(())
    }

    #[test]
    fn creates_isolated_sandbox_directories() -> Result<()> {
        let sandbox = Sandbox::new()?;

        assert!(sandbox.root().is_dir());
        assert!(sandbox.config_dir().is_dir());
        assert!(sandbox.cache_dir().is_dir());
        assert_eq!(sandbox.config_dir().parent(), Some(sandbox.root()));
        assert_eq!(sandbox.cache_dir().parent(), Some(sandbox.config_dir()));

        Ok(())
    }

    #[test]
    fn stages_only_the_requested_fixture() -> Result<()> {
        let sandbox = Sandbox::new()?;

        let project = sandbox.stage_fixture(&Fixture::ReferenceProject)?;

        assert_eq!(project, sandbox.root().join("reference-project"));
        assert!(project.join("Cargo.toml").is_file());
        assert!(!sandbox.root().join("local-registry").try_exists()?);

        Ok(())
    }

    #[test]
    fn refuses_to_stage_the_same_fixture_twice() -> Result<()> {
        let sandbox = Sandbox::new()?;

        sandbox.stage_fixture(&Fixture::LocalRegistry)?;
        sandbox
            .stage_fixture(&Fixture::LocalRegistry)
            .expect_err("staging the same fixture twice must fail");

        Ok(())
    }

    #[test]
    fn clears_only_the_workspace_cache() -> Result<()> {
        let sandbox = Sandbox::new()?;
        let project = sandbox.stage_fixture(&Fixture::ReferenceProject)?;
        let config_file = sandbox.config_dir().join("config.toml");
        let workspace_cache = sandbox
            .cache_dir()
            .join("workspaces")
            .join("reference-project");
        let binary_cache = sandbox
            .cache_dir()
            .join("binaries")
            .join("example")
            .join("1.0.0");

        fs::write(&config_file, "benchmark configuration")?;
        fs::create_dir_all(&workspace_cache)?;
        fs::write(workspace_cache.join("workspace-deps.json"), "cached data")?;
        fs::create_dir_all(&binary_cache)?;
        fs::write(binary_cache.join("example"), "cached binary")?;

        sandbox.clear_workspace_cache()?;
        sandbox.clear_workspace_cache()?;

        assert!(sandbox.cache_dir().is_dir());
        assert!(!workspace_cache.try_exists()?);
        assert_eq!(
            fs::read_to_string(binary_cache.join("example"))?,
            "cached binary"
        );
        assert!(project.join("Cargo.toml").is_file());
        assert_eq!(fs::read_to_string(config_file)?, "benchmark configuration");

        Ok(())
    }
}
