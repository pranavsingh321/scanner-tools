# os-neutron — Internal security scan summary

**Source:** https://github.com/openstack/neutron (OpenStack networking)
**Analyzed:** 2026-08-04, shallow clone, container image `internal-analyzers:latest`
**Raw artifacts:** `artifacts/os-neutron/{osv-scanner,syft,trivy,gitleaks,trufflehog,opengrep,clamav}/`

| Metric | Value |
|---|---|
| SBOM packages (syft) | 1 |
| osv-scanner advisories | 45 (10 package sets) |
| trivy vulnerabilities | 0 |
| trivy secrets (in-tree) | 1 |
| gitleaks findings | 7 |
| trufflehog findings | 162 |
| opengrep findings | 18 |
| clamav infected | 0 |

## Tool results

- **syft** — SBOM (1 packages) in `syft/syft.sbom.json`, table in `syft/syft.table.txt`.
- **osv-scanner** — 45 known-vulnerability advisories across 10 dependency sets.
- **trivy** — 0 vulnerabilities (—); 1 in-tree secrets.
- **gitleaks / trufflehog** — 7 / 162 secret findings; most are test/dev fixtures in large or sample-heavy repos.
- **opengrep** — 18 static-analysis findings.
- **clamav** — 0 infected files.

## Notes

trivy found 1 in-tree secret; trufflehog 162 hits, mostly fixtures. osv-scanner 45 advisories across pinned deps.

ggshield (needs `GITGUARDIAN_API_KEY`) and codeql (no arm64 bundle from GitHub) were not run on this host.
