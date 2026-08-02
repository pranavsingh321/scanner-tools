# gin — Multi-tool summary

**Source:** https://github.com/gin-gonic/gin (Go web framework)
**Analyzed:** 2026-08-02, shallow clone, container image `analyzers:latest`
**Raw artifacts:** `artifacts/gin/{tokei,scc,repomix,gitingest,files-to-prompt}/`

Identical repository to `go-gin` (same gin-gonic/gin, cloned under a second name) — all metrics match exactly.

| Metric | Value |
|---|---|
| Files analyzed (gitingest) | 129 |
| Code LOC (tokei) | 19,341 |
| Comments (tokei) | 4,489 |
| Blank lines (tokei) | 4,490 |
| LLM token estimate (gitingest) | 250.5k |
| repomix pack size | 872 KB |

## My summary
Duplicate-run sanity check: tokei, scc, gitingest, repomix and files-to-prompt produce byte-identical results to the `go-gin` folder, confirming the toolchain is deterministic and reproducible. See `summary/go-gin.md` for the analysis.
