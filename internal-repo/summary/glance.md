# glance — Internal security scan summary

**Source:** https://github.com/openstack/glance (OpenStack image service)
**Analyzed:** 2026-08-04, shallow clone, container image `internal-analyzers:latest`
**Raw artifacts:** `artifacts/glance/{osv-scanner,syft,trivy,gitleaks,trufflehog,opengrep,clamav}/`

| Metric | Value |
|---|---|
| SBOM packages (syft) | 1 |
| osv-scanner advisories | 48 (6 package sets) |
| trivy vulnerabilities | 0 |
| trivy secrets (in-tree) | 0 |
| gitleaks findings | 19 |
| trufflehog findings | 72 |
| opengrep findings | 10 |
| clamav infected | 0 |

## Tool results

- **syft** — SBOM (1 packages) in `syft/syft.sbom.json`, table in `syft/syft.table.txt`.
- **osv-scanner** — 48 known-vulnerability advisories across 6 dependency sets.
- **trivy** — 0 vulnerabilities (—); 0 in-tree secrets.
- **gitleaks / trufflehog** — 19 / 72 secret findings; most are test/dev fixtures in large or sample-heavy repos.
- **opengrep** — 10 static-analysis findings.
- **clamav** — 0 infected files.

## Notes

osv-scanner 48 advisories over 6 packages; gitleaks 19 (generic-api-key/private-key), mostly fixture data.

ggshield (needs `GITGUARDIAN_API_KEY`) and codeql (no arm64 bundle from GitHub) were not run on this host.
