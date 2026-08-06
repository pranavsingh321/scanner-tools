"""Container image management and tool dispatch (podman/docker)."""
from __future__ import annotations

import subprocess
from pathlib import Path


def image_present(runtime: str, image: str) -> bool:
    return (
        subprocess.run([runtime, "image", "exists", image], capture_output=True).returncode
        == 0
    )


def _build_log_path(image: str) -> Path:
    return Path("/tmp") / f"{image.replace(':', '_')}.build.log"


def ensure_image(runtime: str, image: str, build_dir: Path, dockerfile: str | None = None) -> None:
    """Build `image`, retrying once on transient failure.

    Build output is also captured to a log under /tmp so the debug loop and the
    final error message can point at the failing step.
    """
    cmd = [runtime, "build", "-t", image]
    if dockerfile:
        cmd += ["-f", str(Path(dockerfile))]
    cmd.append(str(build_dir))
    log_path = _build_log_path(image)

    for attempt in (1, 2):
        print(f"==> Building {image}" + (" (retry)" if attempt == 2 else ""))
        with open(log_path, "w") as log:
            proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
        if proc.returncode == 0:
            print(f"==> Built {image}")
            return
    raise RuntimeError(
        f"build of {image} failed twice; log: {log_path} "
        f"(last lines: {_tail(log_path)})"
    )


def _tail(path: Path, n: int = 5) -> str:
    try:
        return " | ".join(path.read_text(errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def ensure_images(
    runtime: str,
    images: list[tuple[str, Path, str | None]],
    rebuild: bool = False,
) -> None:
    """Ensure several images exist, building any that are missing unless --rebuild."""
    for image, build_dir, dockerfile in images:
        if rebuild or not image_present(runtime, image):
            ensure_image(runtime, image, build_dir, dockerfile)
        else:
            print(f"==> Image {image} already present (use -r/--rebuild to force)")


def run_tool(
    runtime: str,
    image: str,
    tool: str,
    repo_dir: str,
    out_dir: Path,
    env: dict[str, str] | None = None,
    extra_volume: tuple[str, str] | None = None,
) -> tuple[int, str]:
    """Run one tool inside the container.

    Mounts the repo read-only at /repo and the output dir at /out. Returns
    (container_exit_code, shell_command). The tool's own exit code is left in
    out_dir/.exit when the caller uses the *tool_cmd helpers.
    """
    cmd = [runtime, "run", "--rm"]
    if env:
        for key, value in env.items():
            cmd += ["-e", f"{key}={value}"]
    cmd += ["-v", f"{repo_dir}:/repo:ro", "-v", f"{out_dir}:/out", image]
    return subprocess.run(cmd + ["sh", "-c", tool]).returncode, " ".join(cmd + ["sh", "-c", tool])
