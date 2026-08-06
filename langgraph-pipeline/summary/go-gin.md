# go-gin — analysis summary

**Source:** https://github.com/gin-gonic/gin

| Metric | Value |
|---|---|
| trivy | 3 |
| gitleaks | 4 |
| opengrep | 40 |
| clamav | 0 |

## Findings

### trivy (inventory, 3 findings)
- [unknown] GO-2026-5932 @ go.mod — golang.org/x/crypto v0.52.0 -> -: The golang.org/x/crypto/openpgp package is unmaintained, unsafe by design, and has known security issues
- [unknown] CVE-2026-46600 @ go.mod — golang.org/x/net v0.55.0 -> 0.56.0: Parsing an invalid SVCB or HTTPS RR can panic when the size of a param ...
- [high] CVE-2026-56852 @ go.mod — golang.org/x/text v0.37.0 -> 0.39.0: golang.org/x/text: golang.org/x/text: Denial of Service via invalid UTF-8 input
### gitleaks (inventory, 4 findings)
- [private-key] private-key @ testdata/certificate/key.pem:1 — Identified a Private Key, which may compromise cryptographic security and sensitive data encryption.
- [generic-api-key] generic-api-key @ context_test.go:654 — Detected a Generic API Key, potentially exposing access to various services and sensitive operations.
- [generic-api-key] generic-api-key @ context_test.go:662 — Detected a Generic API Key, potentially exposing access to various services and sensitive operations.
- [generic-api-key] generic-api-key @ context_test.go:3031 — Detected a Generic API Key, potentially exposing access to various services and sensitive operations.
### opengrep (inventory, 40 findings)
- [medium] package_managers.dependabot.dependabot-missing-cooldown.dependabot-missing-cooldown @ .github/dependabot.yml:3 — This Dependabot configuration does not set a cooldown period. Newly published packages can be malicious or unstable. Add a `cooldown` block with `default-days: 7` to each `package-ecosystem` entry und
- [medium] package_managers.dependabot.dependabot-missing-cooldown.dependabot-missing-cooldown @ .github/dependabot.yml:7 — This Dependabot configuration does not set a cooldown period. Newly published packages can be malicious or unstable. Add a `cooldown` block with `default-days: 7` to each `package-ecosystem` entry und
- [warning] yaml.github-actions.security.github-actions-mutable-action-tag.github-actions-mutable-action-tag @ .github/workflows/codeql.yml:36 — GitHub Actions step uses a mutable tag or branch reference. Tags and branch names can be silently repointed by the action owner, enabling supply-chain attacks — as seen in the trivy-action and kics-gi
- [warning] yaml.github-actions.security.github-actions-mutable-action-tag.github-actions-mutable-action-tag @ .github/workflows/codeql.yml:40 — GitHub Actions step uses a mutable tag or branch reference. Tags and branch names can be silently repointed by the action owner, enabling supply-chain attacks — as seen in the trivy-action and kics-gi
- [warning] yaml.github-actions.security.github-actions-mutable-action-tag.github-actions-mutable-action-tag @ .github/workflows/codeql.yml:49 — GitHub Actions step uses a mutable tag or branch reference. Tags and branch names can be silently repointed by the action owner, enabling supply-chain attacks — as seen in the trivy-action and kics-gi
- [warning] yaml.github-actions.security.github-actions-mutable-action-tag.github-actions-mutable-action-tag @ .github/workflows/gin.yml:19 — GitHub Actions step uses a mutable tag or branch reference. Tags and branch names can be silently repointed by the action owner, enabling supply-chain attacks — as seen in the trivy-action and kics-gi
- [warning] yaml.github-actions.security.github-actions-mutable-action-tag.github-actions-mutable-action-tag @ .github/workflows/gin.yml:23 — GitHub Actions step uses a mutable tag or branch reference. Tags and branch names can be silently repointed by the action owner, enabling supply-chain attacks — as seen in the trivy-action and kics-gi
- [warning] yaml.github-actions.security.github-actions-mutable-action-tag.github-actions-mutable-action-tag @ .github/workflows/gin.yml:27 — GitHub Actions step uses a mutable tag or branch reference. Tags and branch names can be silently repointed by the action owner, enabling supply-chain attacks — as seen in the trivy-action and kics-gi

## Notes

Generated mechanically (no LLM endpoint configured). Re-run with OPENAI_API_KEY/OPENAI_BASE_URL set for an LLM-written report.
