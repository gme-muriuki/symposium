//! Shared fixture and sandbox support for Symposium benchmarks.

use anyhow::{Context, Result, bail, ensure};
use std::{
    fs,
    path::{Path, PathBuf},
};

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

        Fixture::ReferenceProject
            .copy_to(&destination)
            .expect_err("copying into an existing destination must fail");

        assert_eq!(fs::read_to_string(sentinel)?, "leave me untouched");
        assert!(!destination.join("Cargo.toml").try_exists()?);

        Ok(())
    }
}
