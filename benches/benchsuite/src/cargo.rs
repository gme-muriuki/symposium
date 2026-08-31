//! Cargo process guards used by benchmark preflights.

use std::{
    fs,
    path::{Path, PathBuf},
};

use anyhow::{Context, Result};
#[cfg(not(windows))]
use indoc::indoc;

#[cfg(not(windows))]
const METADATA_REJECTING_SCRIPT: &str = indoc! {r#"
    #!/bin/sh
    if [ "$1" = "metadata" ]; then
        exit 1
    fi
    exec cargo "$@"
"#};

#[cfg(windows)]
const METADATA_REJECTING_SCRIPT: &str =
    "@echo off\r\nif \"%~1\"==\"metadata\" exit /b 1\r\ncargo %*\r\n";

/// A Cargo executable that forwards commands except `metadata`.
///
/// Benchmark preflights use this to prove that a prepared disk cache is read
/// without changing the executable used by timed samples.
#[derive(Debug)]
pub struct MetadataRejectingCargo {
    executable: PathBuf,
}

impl MetadataRejectingCargo {
    /// Create the guard under `parent`, which must not already contain one.
    pub fn create_in(parent: &Path) -> Result<Self> {
        let directory = parent.join("metadata-rejecting-cargo");
        fs::create_dir(&directory).with_context(|| {
            format!(
                "creating metadata-rejecting Cargo directory `{}`",
                directory.display()
            )
        })?;
        let executable = write_executable(&directory)?;

        Ok(Self { executable })
    }

    pub fn executable(&self) -> &Path {
        &self.executable
    }
}

#[cfg(not(windows))]
fn write_executable(directory: &Path) -> Result<PathBuf> {
    use std::os::unix::fs::PermissionsExt;

    let executable = directory.join("cargo");
    fs::write(&executable, METADATA_REJECTING_SCRIPT)
        .with_context(|| format!("writing Cargo guard `{}`", executable.display()))?;
    fs::set_permissions(&executable, fs::Permissions::from_mode(0o755))
        .with_context(|| format!("making Cargo guard executable `{}`", executable.display()))?;

    Ok(executable)
}

#[cfg(windows)]
fn write_executable(directory: &Path) -> Result<PathBuf> {
    let executable = directory.join("cargo.cmd");
    fs::write(&executable, METADATA_REJECTING_SCRIPT)
        .with_context(|| format!("writing Cargo guard shim `{}`", executable.display()))?;

    Ok(executable)
}

#[cfg(test)]
mod tests {
    use std::process::Command;

    use super::*;
    use anyhow::ensure;
    use tempfile::tempdir;

    #[test]
    fn forwards_other_commands_and_rejects_metadata() -> Result<()> {
        let temporary_directory = tempdir()?;
        let cargo = MetadataRejectingCargo::create_in(temporary_directory.path())?;

        let forwarded = Command::new(cargo.executable())
            .arg("--version")
            .output()
            .context("running a forwarded Cargo command")?;
        ensure!(
            forwarded.status.success(),
            "Cargo guard did not forward `--version`: {}",
            String::from_utf8_lossy(&forwarded.stderr)
        );

        let rejected = Command::new(cargo.executable())
            .arg("metadata")
            .status()
            .context("running rejected Cargo metadata")?;
        ensure!(
            !rejected.success(),
            "Cargo guard unexpectedly allowed `metadata`"
        );

        Ok(())
    }
}
