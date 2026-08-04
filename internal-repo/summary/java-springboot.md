# java-springboot — Internal security scan summary

**Source:** https://github.com/spring-projects/spring-boot (Java application framework)
**Analyzed:** 2026-08-04, shallow clone, container image `internal-analyzers:latest`
**Raw artifacts:** `artifacts/java-springboot/{osv-scanner,syft,trivy,gitleaks,trufflehog,opengrep,clamav}/`

| Metric | Value |
|---|---|
| SBOM packages (syft) | 513 |
| osv-scanner advisories | 11 (5 package sets) |
| trivy vulnerabilities | 25 (1 critical, 17 high, 5 medium, 2 low) |
| trivy secrets (in-tree) | 0 |
| gitleaks findings | 198 |
| trufflehog findings | 94 |
| opengrep findings | 167 |
| clamav infected | 0 |

## Tool results

- **syft** — SBOM (513 packages) in `syft/syft.sbom.json`, table in `syft/syft.table.txt`.
- **osv-scanner** — 11 known-vulnerability advisories across 5 dependency sets.
- **trivy** — 25 vulnerabilities (1 critical, 17 high, 5 medium, 2 low); 0 in-tree secrets.
- **gitleaks / trufflehog** — 198 / 94 secret findings; most are test/dev fixtures in large or sample-heavy repos.
- **opengrep** — 167 static-analysis findings.
- **clamav** — 0 infected files.

## Notes

Largest repo here (4M LOC). trivy fs failed on Maven Central 429 + unresolved @project.version@ poms; trivy.json produced via `trivy sbom` fallback (1 critical, 17 high). gitleaks/opengrep counts are inflated by sample configs and test fixtures.

ggshield (needs `GITGUARDIAN_API_KEY`) and codeql (no arm64 bundle from GitHub) were not run on this host.
