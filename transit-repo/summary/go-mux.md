# go-mux — Multi-tool summary

**Source:** https://github.com/gorilla/mux (Go HTTP router)
**Analyzed:** 2026-08-02, shallow clone, container image `analyzers:latest`
**Raw artifacts:** `artifacts/go-mux/{tokei,scc,repomix,gitingest,files-to-prompt}/`

| Metric | Value |
|---|---|
| Files analyzed (gitingest) | 26 |
| Code LOC (tokei) | 6,214 |
| Comments (tokei) | 1,274 |
| Blank lines (tokei) | 902 |
| LLM token estimate (gitingest) | 71.1k |
| repomix pack size | 780 KB → source ~200 KB |

## Language mix
- tokei: Go 5,820, Makefile 27
- scc: Go 5,820, Markdown 629, YAML 114 — Go count identical to tokei (both derive from the same `path.go`/`mux.go`/`regexp.go` sources)

## Top-level structure
Flat layout: `mux.go`, `path.go`, `regexp.go`, `route.go`, `middleware.go` + `*_test.go` at root, plus `.github/`.

## My summary
A small, single-package router — 26 files, ~6.2k LOC, essentially pure Go at the root level. At 71k tokens the entire repo is a compact LLM context; the pack/digest outputs are ~10x smaller than gin despite similar purpose. Comments (1.3k) are substantial relative to code, indicating a well-documented codebase. All five tools agree closely, so any of them alone is sufficient for this repo.
