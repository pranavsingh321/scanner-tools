# java-springboot — Multi-tool summary

**Source:** https://github.com/spring-projects/spring-boot
**Analyzed:** 2026-08-02, shallow clone, container image `analyzers:latest`
**Raw artifacts:** `artifacts/java-springboot/{tokei,scc,repomix,gitingest,files-to-prompt}/`

| Metric | Value |
|---|---|
| Files analyzed (gitingest) | 10,000 (capped — repo has more) |
| Code LOC (tokei) | 631,612 |
| Comments (tokei) | 238,023 |
| Blank lines (tokei) | 143,754 |
| LLM token estimate (gitingest) | 8.4M |
| repomix pack size | 116 MB total folder; pack ~90 MB |

## Language mix
- tokei: Java 516,935, JSON 62,623, AsciiDoc 22,918
- scc: Java 516,935, JSON 59,305, Gradle 29,121 — Java counts **identical** across both tools

## Top-level structure
Multi-module Gradle parent: `antora/`, `assertions/`, `boot/`, `build-plugin/`, `buildpack/`, `cli/`, `config/`, `core/`, `documentation/`, `eclipse/`, `image/`, `integration-test/`, `spring-boot-project/` modules.

## My summary
A large, heavily modular framework monorepo (~630k LOC, ~8.4M tokens). Two hard facts for LLM use:
1. **gitingest caps at 10,000 files** — its token estimate is a lower bound; the repo is larger than reported.
2. At 8.4M tokens, no current model can take the whole repo. Full packing (repomix 90 MB) is impractical for prompts.
Effective strategies: scope to a single module (`boot`, `cli`, `buildpack`…) or use whatsun's file-selection digest to pull only relevant files. Interesting: comment density is very high (238k comments), typical of the Spring project's emphasis on Javadoc.
