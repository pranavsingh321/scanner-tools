"""Repo resolution and (writable) shallow cloning."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .config import RunConfig
from .state import RepoEntry


def resolve_repo(cfg: RunConfig, entry: RepoEntry) -> str:
    """Make the repo source available on disk and return its path.

    Local dirs are used as-is. Remote URLs are shallow-cloned into work_dir
    (writable, so the remediation stage can edit and commit). Remote clones are
    cleaned up on exit unless --keep is given.
    """
    if entry.is_target:
        raise ValueError(f"{entry.name} is a network target, not a filesystem repo")
    if entry.url:
        clone_dir = cfg.work_dir / entry.name
        if not (clone_dir / ".git").is_dir():
            if clone_dir.exists():
                shutil.rmtree(clone_dir)
            print(f"==> Cloning {entry.name} (shallow)")
            subprocess.run(
                ["git", "clone", "--depth", "1", "--quiet", entry.url, str(clone_dir)],
                check=True,
            )
        return str(clone_dir)
    return entry.localdir


def prepare_work_dir(cfg: RunConfig) -> None:
    cfg.work_dir.mkdir(parents=True, exist_ok=True)


def cleanup_work_dir(cfg: RunConfig) -> None:
    if not cfg.keep and cfg.work_dir.is_dir():
        print("==> Cleaning up temp clones")
        shutil.rmtree(cfg.work_dir, ignore_errors=True)
