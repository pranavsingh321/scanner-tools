# internal-repo

Independent security-analysis repo. Batch analysis using the security tooling below, each run in a container against one or more repositories (or live network targets), producing raw artifacts and per-repo markdown summaries. Structure mirrors `transit-repo/`; nothing here is shared with it.

## Layout

| Path | What it is |
|---|---|
| `run-tools.sh` | Driver script: clones/loads repos, runs each tool in a container, saves output |
| `Dockerfile` | Builds the `internal-analyzers:latest` image containing all the CLIs |
| `artifacts/<repo>/<tool>/` | Raw output files, one directory per tool and repo |
| `summary/<repo>.md` | Hand-written analysis summary per repo (metrics + notes) |

## Tool → output file mapping

Each repo tool runs inside the container with the repo mounted read-only at `/repo` and its output directory mounted at `/out`. Per `run_repo_tool()` in `run-tools.sh`:

| Category | Tool | Output file(s) | What it produces |
|---|---|---|---|
| SBOM | `syft` | `syft/syft.sbom.json`, `syft/syft.table.txt` | Software bill of materials (SPDX JSON) + component table |
| Dependency scanning | `osv-scanner` | `osv-scanner/osv-scanner.json` | Known vulnerabilities from the OSV database for lockfiles |
| Dependency scanning | `trivy` | `trivy/trivy.json`, `trivy/trivy.log` | Vulnerabilities, secrets, and misconfigurations in the filesystem (JSON) |
| Secrets detection | `gitleaks` | `gitleaks/gitleaks.json`, `gitleaks/gitleaks.log` | Hardcoded secrets in the current tree (JSON) |
| Secrets detection | `trufflehog` | `trufflehog/trufflehog.json` | Secrets via local filesystem scan (JSON lines) |
| Secrets detection | `ggshield` | `ggshield/ggshield.json` | GitGuardian secret scan; requires `GITGUARDIAN_API_KEY` (skipped otherwise) |
| Source code analysis | `opengrep` | `opengrep/opengrep.json` | Static analysis findings using registry rules (`--config auto`, needs network) |
| Advanced code analysis | `codeql` | `codeql/codeql.sarif`, `codeql/codeql-db/`, `codeql/codeql.log` | SARIF findings; language auto-detected from the repo |
| Malware scanning | `clamav` | `clamav/clamav.log` | `clamscan` report (signatures via `freshclam` on first run) |

Target tools run only against a `target:URL/HOST` entry and use the image directly:

| Category | Tool | Output file(s) | What it produces |
|---|---|---|---|
| Web app security | `nuclei` | `nuclei/nuclei.jsonl`, `nuclei/nuclei.log` | Vulnerability template matches (JSON lines) |
| Network discovery | `naabu` | `naabu/naabu.json`, `naabu/naabu.log` | Open port scan (JSON) |
| Network discovery | `httpx` | `httpx/httpx.json`, `httpx/httpx.log` | HTTP probing / fingerprinting (JSON) |

A `*.log` beside a tool's primary output is the tool's own console output.

### Tools used as external services (not in the image)

These are heavyweight server products; they are documented here, not installed in the image.

| Category | Tool | How to run against a target |
|---|---|---|
| Source code analysis | SonarQube | Run the SonarQube server + scanner, e.g. `docker run -d -p 9000:9000 sonarqube` then `sonar-scanner -Dsonar.host.url=http://localhost:9000 -Dsonar.token=$TOKEN -Dsonar.projectKey=proj` |
| Web app security | OWASP ZAP | `docker run -t ghcr.io/zaproxy/zaproxy zap-baseline.py -t https://example.com -r /zap/wrk/report.html` |
| Runtime threat detection | Falco | Runs on the host/containers (kernel + eBPF hooks), not against a repo: `docker run --privileged -v /var/run/docker.sock:/var/run/docker.sock falcosecurity/falco` |
| Infra vulnerability scanning | OpenVAS / GVM | Full scanner daemon + web UI (e.g. `greenbone` images); drives authenticated network scans, not CLI per-repo scans |

## Tool comparison

### Redundancy
| Group | Tools | Notes |
|---|---|---|
| Secrets | `gitleaks` ↔ `trufflehog` | Overlapping; gitleaks = fast regex-based tree scan, trufflehog = entropy + verification, `--only-verified` for fewer false positives. `ggshield` is the only API-backed one (needs GitGuardian). |
| Dependency vulns | `osv-scanner` ↔ `trivy` | Overlapping lockfile databases; trivy adds image/fs/misconfig scanning, osv-scanner is lighter and fully offline. |

### Offline behavior
| Tool | Offline? | Notes |
|---|---|---|
| `syft`, `gitleaks`, `trufflehog`, `clamav` (after first `freshclam`) | Yes | No network needed at scan time |
| `osv-scanner` | Yes (with cached DB) | Uses local OSV cache if present |
| `trivy` | Partial | First run downloads the vulnerability DB; add `--skip-db-update` for cached runs |
| `opengrep` | No | `--config auto` fetches rules from the registry |
| `codeql` | Yes | Bundle ships precompiled queries; no runtime download |

### CodeQL language detection
`detect_language()` in `run-tools.sh` picks a language from common manifest files (`go.mod` → go, `pom.xml`/`build.gradle` → java, `package.json` → javascript, `requirements.txt`/`pyproject.toml` → python, `Gemfile` → ruby, `Cargo.toml` → rust, `.csproj`/`.sln` → csharp, `CMakeLists.txt`/`Makefile` → cpp), defaulting to `javascript`. Override per run by editing the function or passing a repo where the manifest is unambiguous.

## Usage

```bash
./run-tools.sh                            # analyze the 3 default repos (largest per language)
./run-tools.sh /path/to/local/repo        # analyze a local directory
./run-tools.sh https://github.com/user/repo     # shallow-clone a remote repo
./run-tools.sh myname:https://github.com/user/repo   # remote with explicit artifact name
./run-tools.sh target:https://app.example.com      # run nuclei/naabu/httpx against a live target
GITGUARDIAN_API_KEY=... ./run-tools.sh ...         # enable the ggshield scan
```

Options: `-o/--out DIR`, `-r/--rebuild` (force image rebuild), `-R/--runtime podman|docker`, `-k/--keep` (keep temp clones), `-f/--force` (re-run even if output exists), `-h/--help`.

Behavior: requires `podman` or `docker`. Builds `internal-analyzers:latest` on first run, then reuses it. Remote repos are shallow-cloned to `.multi-work/` (cleaned up on exit unless `-k`). Existing outputs are skipped by default (`-f` to override).

## Build note

The image is built in two stages (`Dockerfile`): a `golang:bookworm` stage compiles the Go tools (`osv-scanner`, `gitleaks`, `trufflehog`, `nuclei`, `naabu`, `httpx`), then a `debian:bookworm-slim` runtime stage adds `syft`, `trivy`, `ggshield`, `opengrep`, `codeql` (bundle, ~780 MB download), and `clamav`. Debian (glibc) is required because CodeQL is incompatible with musl/Alpine.

## Current results (2026-08-04 run)

Default repos = largest repo per language family (go-gin / Go, java-springboot / Java, os-nova / Python). Per-repo notes in `summary/<repo>.md`.

| Repo | SBOM pkgs (syft) | osv-scanner | trivy | gitleaks | trufflehog | opengrep |
|---|---|---|---|---|---|---|
| go-gin | 50 | 42 | 3 (1 high) | 4 | 1 | 40 |
| java-springboot | 513 | 11 | 25 (1 crit, 17 high) | 198 | 94 | 167 |
| os-nova | 2 | 80 | 0 (5 secrets) | 48 | 224 | 25 |

Notes:
- `ggshield` and `codeql` were not run on this host: ggshield needs `GITGUARDIAN_API_KEY`; GitHub ships only an x86_64 CodeQL bundle, which won't run on the arm64 podman VM (rebuild on amd64 to enable).
- `trivy` for java-springboot was produced with the `trivy sbom` fallback against the syft SBOM, because the default `trivy fs` scan hit Maven Central rate limiting (HTTP 429) and unresolvable `@project.version@` poms. See `trivy/trivy.log` for the 429 errors.
- No malware found by ClamAV in any repo (0 infected).
- Most gitleaks/trufflehog hits are test/dev fixtures in sample-heavy repos; verify before triaging as real secrets.
