"""Local prerequisites, integrity evidence, and scoped process state."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import cast

from skill_eval.config import ExperimentConfig
from skill_eval.models import CommandRunner, ControlEvidence, JsonObject, JsonValue


def framework_versions() -> dict[str, str]:
    """Return installed versions of the two execution frameworks."""
    versions: dict[str, str] = {}
    for package in ("inspect-ai", "inspect-swe"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = "unavailable"
    return versions


def asset_status(config: ExperimentConfig) -> dict[str, bool]:
    """Report whether every version-controlled experiment asset exists."""
    experiment = config.experiment
    assets = {
        "fixture": config.resolve(experiment.fixture_path),
        "grader": config.resolve(experiment.grader_path),
        "skill": config.resolve(experiment.skill_path),
        "sandbox_config": config.resolve(experiment.sandbox_config),
        "dockerfile": config.root / "Dockerfile",
        "dockerignore": config.root / ".dockerignore",
        "binary_downloader": config.root / "scripts" / "cache-claude-code.sh",
        "cargo_shim": config.root / "bin" / "cargo",
        "cargo_agents_shim": config.root / "bin" / "cargo-agents",
    }
    return {name: path.exists() for name, path in assets.items()}


def file_fingerprint(files: Sequence[tuple[str, Path]]) -> str:
    """Hash labelled files without ambiguity from duplicate basenames."""
    digest = hashlib.sha256()
    for label, path in files:
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def control_fingerprint(config: ExperimentConfig) -> str:
    """Fingerprint every input that can change control behavior."""
    fixture = config.resolve(config.experiment.fixture_path)
    paths = [
        fixture / "Cargo.toml",
        fixture / "API_NOTES.md",
        config.resolve(config.experiment.grader_path),
        config.root / "run.py",
        config.root / "experiment.toml",
        config.root / "Dockerfile",
        config.root / ".dockerignore",
        config.resolve(config.experiment.sandbox_config),
        config.root / "bin" / "cargo",
        config.root / "bin" / "cargo-agents",
        config.root / "scripts" / "cache-claude-code.sh",
        config.root / "pyproject.toml",
        config.root / "uv.lock",
        *sorted((config.root / "skill_eval").glob("*.py")),
    ]
    labelled = [(path.relative_to(config.root).as_posix(), path) for path in paths]
    return file_fingerprint(labelled)


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return str(value)


def control_result(config: ExperimentConfig) -> ControlEvidence:
    """Load current, schema-checked grader-control evidence."""
    path = config.resolve(config.experiment.controls_path)
    if not path.exists():
        return ControlEvidence(passed=False, reason="missing")
    try:
        raw_document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ControlEvidence(passed=False, reason="unreadable")
    if not isinstance(raw_document, dict):
        return ControlEvidence(passed=False, reason="malformed")
    if raw_document.get("schema_version") != 1 or not isinstance(raw_document.get("passed"), bool):
        return ControlEvidence(passed=False, reason="malformed")
    fingerprint = raw_document.get("fingerprint")
    generated_at = raw_document.get("generated_at")
    if not isinstance(fingerprint, str) or not isinstance(generated_at, str):
        return ControlEvidence(passed=False, reason="malformed")
    try:
        current_fingerprint = control_fingerprint(config)
    except OSError:
        return ControlEvidence(passed=False, reason="missing inputs")
    if fingerprint != current_fingerprint:
        return ControlEvidence(passed=False, reason="stale")
    details = cast(JsonObject, _json_value(raw_document))
    details.pop("passed", None)
    details.pop("fingerprint", None)
    details.pop("generated_at", None)
    return ControlEvidence(
        passed=raw_document["passed"],
        fingerprint=fingerprint,
        generated_at=generated_at,
        details=details,
    )


def discover_docker() -> Path | None:
    """Find Docker on PATH or in standard Docker Desktop locations."""
    if executable := shutil.which("docker"):
        return Path(executable)

    candidates: list[Path] = []
    if local_app_data := os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(local_app_data) / "Programs" / "DockerDesktop" / "resources" / "bin" / "docker.exe")
    if program_files := os.environ.get("PROGRAMFILES"):
        candidates.append(Path(program_files) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe")
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def agent_binary_path(config: ExperimentConfig, *, cache_root: Path | None = None) -> Path:
    """Return the Inspect SWE cache location for the pinned agent binary."""
    if cache_root is None:
        from platformdirs import user_cache_path

        cache_root = user_cache_path("inspect_swe")
    return cache_root / "claude-code-downloads" / config.agent_binary.cache_file


def verified_agent_binary(config: ExperimentConfig, *, cache_root: Path | None = None) -> Path | None:
    """Return the binary path only when its full size and digest match the pin."""
    path = agent_binary_path(config, cache_root=cache_root)
    try:
        if path.stat().st_size != config.agent_binary.size:
            return None
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError:
        return None
    return path if digest == config.agent_binary.sha256 else None


def _run_command(command: Sequence[str], *, cwd: Path, check: bool) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, cwd=cwd, check=check)


def cache_agent_binary(
    config: ExperimentConfig,
    *,
    docker: Path,
    cache_root: Path | None = None,
    command_runner: CommandRunner = _run_command,
) -> Path:
    """Populate and verify the pinned agent binary through the downloader image."""
    if verified := verified_agent_binary(config, cache_root=cache_root):
        return verified

    path = agent_binary_path(config, cache_root=cache_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    image = f"symposium-skill-effectiveness-downloader:{config.experiment.agent_version}"
    command_runner(
        [
            str(docker),
            "build",
            "--target",
            "downloader",
            "--tag",
            image,
            "--file",
            str(config.root / "Dockerfile"),
            str(config.root),
        ],
        cwd=config.root,
        check=True,
    )
    command_runner(
        [
            str(docker),
            "run",
            "--rm",
            "--mount",
            f"type=bind,source={path.parent},target=/cache",
            image,
            config.experiment.agent_version,
            config.agent_binary.cache_file,
            str(config.agent_binary.size),
            config.agent_binary.sha256,
        ],
        cwd=config.root,
        check=True,
    )
    verified = verified_agent_binary(config, cache_root=cache_root)
    if verified is None:
        raise RuntimeError("downloaded Claude Code binary failed size or SHA-256 check")
    return verified


@contextmanager
def temporary_environment(updates: Mapping[str, str]) -> Iterator[None]:
    """Apply environment changes and restore the caller's exact state."""
    previous = {name: os.environ.get(name) for name in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@contextmanager
def working_directory(path: Path) -> Iterator[None]:
    """Temporarily change directory and always restore the caller's directory."""
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


@contextmanager
def runtime_environment(docker: Path, agent_binary: Path | None = None) -> Iterator[None]:
    """Expose Docker and the optional agent pin only while Inspect is running."""
    updates = {"PATH": f"{docker.parent}{os.pathsep}{os.environ.get('PATH', '')}"}
    if os.name == "nt":
        updates["COMPOSE_BAKE"] = "false"
    if agent_binary is not None:
        updates["CLAUDE_CODE_BINARY_PATH"] = str(agent_binary)
    with temporary_environment(updates):
        yield


def prerequisites(config: ExperimentConfig) -> dict[str, bool]:
    """Report paid-run readiness without changing process-wide state."""
    return {
        "docker": discover_docker() is not None,
        "agent_binary": verified_agent_binary(config) is not None,
        "anthropic_api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "grader_controls": control_result(config).passed,
    }
