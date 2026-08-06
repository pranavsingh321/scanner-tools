# java-springboot — analysis summary

**Source:** https://github.com/spring-projects/spring-boot

| Metric | Value |
|---|---|
| gitleaks | 198 |
| opengrep | 178 |
| clamav | 0 |

## Findings

### gitleaks (inventory, 198 findings)
- [generic-api-key] generic-api-key @ build-plugin/spring-boot-gradle-plugin/src/docs/antora/modules/gradle-plugin/examples/packaging/boot-build-image-docker-auth-token.gradle:14 — Detected a Generic API Key, potentially exposing access to various services and sensitive operations.
- [generic-api-key] generic-api-key @ build-plugin/spring-boot-gradle-plugin/src/test/java/org/springframework/boot/gradle/docs/PackagingDocumentationTests.java:292 — Detected a Generic API Key, potentially exposing access to various services and sensitive operations.
- [private-key] private-key @ buildpack/spring-boot-buildpack-platform/src/test/java/org/springframework/boot/buildpack/platform/docker/ssl/PemFileWriter.java:76 — Identified a Private Key, which may compromise cryptographic security and sensitive data encryption.
- [private-key] private-key @ buildpack/spring-boot-buildpack-platform/src/test/java/org/springframework/boot/buildpack/platform/docker/ssl/PemFileWriter.java:93 — Identified a Private Key, which may compromise cryptographic security and sensitive data encryption.
- [private-key] private-key @ buildpack/spring-boot-buildpack-platform/src/test/java/org/springframework/boot/buildpack/platform/docker/ssl/PemFileWriter.java:100 — Identified a Private Key, which may compromise cryptographic security and sensitive data encryption.
- [private-key] private-key @ buildpack/spring-boot-buildpack-platform/src/test/java/org/springframework/boot/buildpack/platform/docker/ssl/PemFileWriter.java:104 — Identified a Private Key, which may compromise cryptographic security and sensitive data encryption.
- [private-key] private-key @ buildpack/spring-boot-buildpack-platform/src/test/java/org/springframework/boot/buildpack/platform/docker/ssl/PemFileWriter.java:120 — Identified a Private Key, which may compromise cryptographic security and sensitive data encryption.
- [private-key] private-key @ buildpack/spring-boot-buildpack-platform/src/test/java/org/springframework/boot/buildpack/platform/docker/ssl/PemFileWriter.java:126 — Identified a Private Key, which may compromise cryptographic security and sensitive data encryption.
### opengrep (inventory, 178 findings)
- [error] yaml.github-actions.security.run-shell-injection.run-shell-injection @ .github/actions/await-http-resource/action.yml:12 — Using variable interpolation `${{...}}` with `github` context data in a `run:` step could allow an attacker to inject their own code into the runner. This would allow them to steal secrets and code. `
- [error] yaml.github-actions.security.run-shell-injection.run-shell-injection @ .github/actions/create-github-release/action.yml:34 — Using variable interpolation `${{...}}` with `github` context data in a `run:` step could allow an attacker to inject their own code into the runner. This would allow them to steal secrets and code. `
- [warning] yaml.github-actions.security.github-actions-mutable-action-tag.github-actions-mutable-action-tag @ .github/actions/prepare-gradle-build/action.yml:37 — GitHub Actions step uses a mutable tag or branch reference. Tags and branch names can be silently repointed by the action owner, enabling supply-chain attacks — as seen in the trivy-action and kics-gi
- [error] yaml.github-actions.security.run-shell-injection.run-shell-injection @ .github/actions/prepare-gradle-build/action.yml:65 — Using variable interpolation `${{...}}` with `github` context data in a `run:` step could allow an attacker to inject their own code into the runner. This would allow them to steal secrets and code. `
- [error] yaml.github-actions.security.run-shell-injection.run-shell-injection @ .github/actions/publish-gradle-plugin/action.yml:29 — Using variable interpolation `${{...}}` with `github` context data in a `run:` step could allow an attacker to inject their own code into the runner. This would allow them to steal secrets and code. `
- [warning] yaml.github-actions.security.github-actions-mutable-action-tag.github-actions-mutable-action-tag @ .github/actions/publish-gradle-plugin/action.yml:31 — GitHub Actions step uses a mutable tag or branch reference. Tags and branch names can be silently repointed by the action owner, enabling supply-chain attacks — as seen in the trivy-action and kics-gi
- [error] yaml.github-actions.security.run-shell-injection.run-shell-injection @ .github/actions/publish-gradle-plugin/action.yml:38 — Using variable interpolation `${{...}}` with `github` context data in a `run:` step could allow an attacker to inject their own code into the runner. This would allow them to steal secrets and code. `
- [error] yaml.github-actions.security.run-shell-injection.run-shell-injection @ .github/actions/publish-to-sdkman/action.yml:22 — Using variable interpolation `${{...}}` with `github` context data in a `run:` step could allow an attacker to inject their own code into the runner. This would allow them to steal secrets and code. `

## Notes

Generated mechanically (no LLM endpoint configured). Re-run with OPENAI_API_KEY/OPENAI_BASE_URL set for an LLM-written report.
