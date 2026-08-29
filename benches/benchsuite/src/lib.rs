//! Shared fixture and sandbox support for Symposium benchmarks.

use anyhow::{Result, ensure};
use std::path::{Path, PathBuf};

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

    fn directory_name(&self) -> &'static str {
        match self {
            Self::ReferenceProject => "reference-project",
            Self::LocalRegistry => "local-registry",
        }
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
}
