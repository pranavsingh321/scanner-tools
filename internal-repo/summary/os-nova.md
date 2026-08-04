# os-nova — Internal security scan summary

**Source:** https://github.com/openstack/nova (OpenStack compute)
**Analyzed:** 2026-08-04, shallow clone, container image `internal-analyzers:latest`
**Raw artifacts:** `artifacts/os-nova/{osv-scanner,syft,trivy,gitleaks,trufflehog,opengrep,clamav}/`

| Metric | Value |
|---|---|
| SBOM packages (syft) | 2 |
| osv-scanner advisories | 80 (11 package sets) |
| trivy vulnerabilities | 0 |
| trivy secrets (in-tree) | 5 |
| gitleaks findings | 48 |
| trufflehog findings | 224 |
| opengrep findings | 25 |
| clamav infected | 0 |

## Tool results

- **syft** — SBOM (2 packages) in `syft/syft.sbom.json`, table in `syft/syft.table.txt`.
- **osv-scanner** — 80 known-vulnerability advisories across 11 dependency sets.
- **trivy** — 0 vulnerabilities (—); 5 in-tree secrets.
- **gitleaks / trufflehog** — 48 / 224 secret findings; most are test/dev fixtures in large or sample-heavy repos.
- **opengrep** — 25 static-analysis findings.
- **clamav** — 0 infected files.

## Notes

Large Python codebase; trivy secret scan found 5 in-tree secrets, gitleaks 48 and trufflehog 224 — most from historical test/dev fixtures.

ggshield (needs `GITGUARDIAN_API_KEY`) and codeql (no arm64 bundle from GitHub) were not run on this host.
