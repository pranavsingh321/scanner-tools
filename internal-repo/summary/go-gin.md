# go-gin — Internal security scan summary

**Source:** https://github.com/gin-gonic/gin (Go web framework)
**Analyzed:** 2026-08-04, shallow clone, container image `internal-analyzers:latest`
**Raw artifacts:** `artifacts/go-gin/{osv-scanner,syft,trivy,gitleaks,trufflehog,opengrep,clamav}/`

| Metric | Value |
|---|---|
| SBOM packages (syft) | 50 |
| osv-scanner advisories | 42 (4 package sets) |
| trivy vulnerabilities | 3 (1 high, 2 unknown) |
| trivy secrets (in-tree) | 0 |
| gitleaks findings | 4 |
| trufflehog findings | 1 |
| opengrep findings | 40 |
| clamav infected | 0 |

## Tool results

- **syft** — SBOM (50 packages) in `syft/syft.sbom.json`, table in `syft/syft.table.txt`.
- **osv-scanner** — 42 known-vulnerability advisories across 4 dependency sets.
- **trivy** — 3 vulnerabilities (1 high, 2 unknown); 0 in-tree secrets.
- **gitleaks / trufflehog** — 4 / 1 secret findings; most are test/dev fixtures in large or sample-heavy repos.
- **opengrep** — 40 static-analysis findings.
- **clamav** — 0 infected files.

## Notes

Same source as gin (duplicate entry in the default list). osv-scanner reports a high count from old transitive go.mod deps; gitleaks hits are in testdata/sample fixtures.

ggshield (needs `GITGUARDIAN_API_KEY`) and codeql (no arm64 bundle from GitHub) were not run on this host.
