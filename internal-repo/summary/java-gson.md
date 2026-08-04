# java-gson — Internal security scan summary

**Source:** https://github.com/google/gson (Java JSON library)
**Analyzed:** 2026-08-04, shallow clone, container image `internal-analyzers:latest`
**Raw artifacts:** `artifacts/java-gson/{osv-scanner,syft,trivy,gitleaks,trufflehog,opengrep,clamav}/`

| Metric | Value |
|---|---|
| SBOM packages (syft) | 43 |
| osv-scanner advisories | 0 (0 package sets) |
| trivy vulnerabilities | 0 |
| trivy secrets (in-tree) | 0 |
| gitleaks findings | 0 |
| trufflehog findings | 46 |
| opengrep findings | 2 |
| clamav infected | 0 |

## Tool results

- **syft** — SBOM (43 packages) in `syft/syft.sbom.json`, table in `syft/syft.table.txt`.
- **osv-scanner** — 0 known-vulnerability advisories across 0 dependency sets.
- **trivy** — 0 vulnerabilities (—); 0 in-tree secrets.
- **gitleaks / trufflehog** — 0 / 46 secret findings; most are test/dev fixtures in large or sample-heavy repos.
- **opengrep** — 2 static-analysis findings.
- **clamav** — 0 infected files.

## Notes

trivy fs scan was blocked by Maven Central rate limiting (HTTP 429); trivy.json produced via `trivy sbom` against the syft SBOM instead. trufflehog hits are in test fixtures.

ggshield (needs `GITGUARDIAN_API_KEY`) and codeql (no arm64 bundle from GitHub) were not run on this host.
