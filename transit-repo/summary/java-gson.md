# java-gson — Multi-tool summary

**Source:** https://github.com/google/gson (Java JSON library)
**Analyzed:** 2026-08-02, shallow clone, container image `analyzers:latest`
**Raw artifacts:** `artifacts/java-gson/{tokei,scc,repomix,gitingest,files-to-prompt}/`

| Metric | Value |
|---|---|
| Files analyzed (gitingest) | 312 |
| Code LOC (tokei) | 40,514 |
| Comments (tokei) | 13,325 |
| Blank lines (tokei) | 6,974 |
| LLM token estimate (gitingest) | 535.2k |
| repomix pack size | 6.7 MB → source ~2.5 MB |

## Language mix
- tokei: Java 38,177, XML 1,473, Protocol Buffers 344
- scc: Java 38,082, XML 1,460, Markdown 1,454 — near-identical Java/XML counts

## Top-level structure
`gson/` (core package), `extras/`, `metrics/`, `proto/`, `test-graal-native-image/`, `test-jpms/`, `test-shrinker/`, `.mvn/`

## My summary
Compact, self-contained Java library: ~38k lines of Java across core `gson/` plus a handful of satellite modules and test harnesses. High comment ratio (13.3k comments vs 40.5k code) — the source is thoroughly documented (reflection adapter, `Gson` builder, type adapters). At ~535k tokens it exceeds a single small-context window but fits a 200k+ model; for anything smaller, gitingest's digest or repomix's compress mode is the right call. Cross-tool agreement (tokei vs scc) is within 0.3%.
