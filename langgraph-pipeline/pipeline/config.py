"""Central configuration: runtime detection, image names, dirs, repo parsing, env."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Default repo lists (mirrors transit-repo/run-tools.sh:107 and
# internal-repo/run-tools.sh:204). Each entry is (artifact name, clone URL).
# ---------------------------------------------------------------------------
DEFAULT_REPOS = [
    ("go-gin", "https://github.com/gin-gonic/gin"),
    ("java-springboot", "https://github.com/spring-projects/spring-boot"),
    ("os-nova", "https://github.com/openstack/nova"),
]

TRANSIT_IMAGE = "analyzers:latest"
QUALITY_IMAGE = "quality:latest"
INTERNAL_IMAGE = "internal-analyzers:latest"


def detect_runtime() -> str:
    """Pick podman or docker, whichever is installed and has a running daemon."""
    for candidate in ("podman", "docker"):
        if shutil.which(candidate):
            if subprocess.run([candidate, "info"], capture_output=True).returncode == 0:
                return candidate
    raise SystemExit("error: neither podman nor docker with a running daemon found")


def env_bool(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


@dataclass
class RunConfig:
    """Runtime settings shared by every graph node."""

    out_dir: Path = field(default_factory=lambda: SCRIPT_DIR / "artifacts")
    work_dir: Path = field(default_factory=lambda: SCRIPT_DIR / ".multi-work")
    summary_dir: Path = field(default_factory=lambda: SCRIPT_DIR / "summary")
    runtime: str = field(default_factory=detect_runtime)
    rebuild: bool = False
    keep: bool = False
    force: bool = False
    min_code: int = 50
    remediate: bool = True
    no_merge: bool = False

    @classmethod
    def from_cli(cls, args, *, image: str, quality_dir: Path | None = None) -> "RunConfig":
        cfg = cls(
            out_dir=Path(args.out),
            runtime=args.runtime or os.environ.get("RUNTIME") or detect_runtime(),
            rebuild=args.rebuild,
            keep=args.keep,
            force=args.force,
            min_code=int(os.environ.get("MIN_CODE", "50")),
            remediate=not args.no_remediate,
            no_merge=args.no_merge,
        )
        if quality_dir is not None:
            cfg.quality_dir = quality_dir
        cfg.image = image
        return cfg


# ---------------------------------------------------------------------------
# Repo entry parsing
# ---------------------------------------------------------------------------

def parse_entries(entries: list[str]) -> list["RepoEntry"]:
    """Turn CLI args into RepoEntry objects.

    Accepted forms (transit):
      name:https://...      artifact name + remote URL
      https://...           bare URL (name derived from URL)
      /path/to/repo         local directory
      name                  bare name resolved against DEFAULT_REPOS
    Internal graph additionally accepts:
      target:HOST           network target (runs nuclei/naabu/httpx only)
      name:target:HOST      network target with explicit artifact name
    """
    from .state import RepoEntry  # local import to avoid a cycle

    parsed: list[RepoEntry] = []
    for entry in entries:
        # Network target forms (internal graph).
        if entry.startswith("target:"):
            target = entry.removeprefix("target:")
            parsed.append(RepoEntry(target=target, name=_target_name(target)))
            continue
        if ":target:" in entry:
            name, _, target = entry.partition(":target:")
            parsed.append(RepoEntry(name=name, target=target))
            continue

        if ":" in entry and not entry.startswith(("http://", "https://")):
            name, url = entry.split(":", 1)
            parsed.append(RepoEntry(name=name, url=url))
            continue
        if entry.startswith(("http://", "https://")):
            url = entry.rstrip("/")
            parsed.append(RepoEntry(name=_url_name(url), url=url))
            continue
        path = Path(entry).expanduser()
        if path.is_dir():
            parsed.append(RepoEntry(name=path.name, localdir=str(path.resolve())))
            continue
        # Bare name: look it up in DEFAULT_REPOS for the clone URL.
        for name, url in DEFAULT_REPOS:
            if name == entry:
                parsed.append(RepoEntry(name=name, url=url))
                break
        else:
            print(f"!! [{entry}] not a directory and no known URL", file=sys.stderr)
    return parsed


def _target_name(target: str) -> str:
    name = target.removeprefix("https://").removeprefix("http://")
    return name.split("/")[0].split(":")[0]


def _url_name(url: str) -> str:
    return url.rstrip("/").split("/")[-1].removesuffix(".git")


def gh_account() -> str:
    """Account that owns forks (used for fork/PR flows)."""
    cached = getattr(gh_account, "_cached", None)
    if cached:
        return cached
    try:
        out = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True
        ).stdout.strip()
    except FileNotFoundError:
        out = ""
    gh_account._cached = out or os.environ.get("GITHUB_ACTOR", "github-actions")
    return gh_account._cached
