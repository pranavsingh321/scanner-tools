# py-flask — Internal security scan summary

**Source:** https://github.com/pallets/flask (Python web framework)
**Analyzed:** 2026-08-04, shallow clone, container image `internal-analyzers:latest`
**Raw artifacts:** `artifacts/py-flask/{osv-scanner,syft,trivy,gitleaks,trufflehog,opengrep,clamav}/`

| Metric | Value |
|---|---|
| SBOM packages (syft) | 123 |
| osv-scanner advisories | 27 (4 package sets) |
| trivy vulnerabilities | 13 (1 high, 11 medium, 1 low) |
| trivy secrets (in-tree) | 0 |
| gitleaks findings | 6 |
| trufflehog findings | 7 |
| opengrep findings | 16 |
| clamav infected | 0 |

## Tool results

- **syft** — SBOM (123 packages) in `syft/syft.sbom.json`, table in `syft/syft.table.txt`.
- **osv-scanner** — 27 known-vulnerability advisories across 4 dependency sets.
- **trivy** — 13 vulnerabilities (1 high, 11 medium, 1 low); 0 in-tree secrets.
- **gitleaks / trufflehog** — 6 / 7 secret findings; most are test/dev fixtures in large or sample-heavy repos.
- **opengrep** — 16 static-analysis findings.
- **clamav** — 0 infected files.

## Notes

trivy: 13 vulns across flask deps (11 medium). gitleaks 6 generic-api-key hits in tests; no malware.

ggshield (needs `GITGUARDIAN_API_KEY`) and codeql (no arm64 bundle from GitHub) were not run on this host.
