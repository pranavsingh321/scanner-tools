# go-mux — Internal security scan summary

**Source:** https://github.com/gorilla/mux (Go HTTP router)
**Analyzed:** 2026-08-04, shallow clone, container image `internal-analyzers:latest`
**Raw artifacts:** `artifacts/go-mux/{osv-scanner,syft,trivy,gitleaks,trufflehog,opengrep,clamav}/`

| Metric | Value |
|---|---|
| SBOM packages (syft) | 12 |
| osv-scanner advisories | 60 (1 package sets) |
| trivy vulnerabilities | 0 |
| trivy secrets (in-tree) | 0 |
| gitleaks findings | 0 |
| trufflehog findings | 0 |
| opengrep findings | 11 |
| clamav infected | 0 |

## Tool results

- **syft** — SBOM (12 packages) in `syft/syft.sbom.json`, table in `syft/syft.table.txt`.
- **osv-scanner** — 60 known-vulnerability advisories across 1 dependency sets.
- **trivy** — 0 vulnerabilities (—); 0 in-tree secrets.
- **gitleaks / trufflehog** — 0 / 0 secret findings; most are test/dev fixtures in large or sample-heavy repos.
- **opengrep** — 11 static-analysis findings.
- **clamav** — 0 infected files.

## Notes

Small Go module; osv-scanner flags many advisories for the single pinned dependency set in go.sum. No secrets, no malware.

ggshield (needs `GITGUARDIAN_API_KEY`) and codeql (no arm64 bundle from GitHub) were not run on this host.
