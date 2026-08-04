# py-flask — Multi-tool summary

**Source:** https://github.com/pallets/flask (Python microframework)
**Analyzed:** 2026-08-02, shallow clone, container image `analyzers:latest`
**Raw artifacts:** `artifacts/py-flask/{tokei,scc,repomix,gitingest,files-to-prompt}/`

| Metric | Value |
|---|---|
| Files analyzed (gitingest) | 224 |
| Code LOC (tokei) | 25,703 |
| Comments (tokei) | 986 |
| Blank lines (tokei) | 7,542 |
| LLM token estimate (gitingest) | 444.0k |
| repomix pack size | 4.1 MB folder |

## Language mix
- tokei: Python 13,980, ReStructuredText 10,820, TOML 334
- scc: Python 13,214, ReStructuredText 10,820, TOML 334 — ReST/TOML identical

## Top-level structure
`src/flask/` (actual package), `tests/`, `docs/`, `examples/`, `flaskr/` (tutorial app), `.github/`, `.devcontainer/`

## My summary
A compact framework: ~14k LOC of real Python in `src/flask`, with the docs (10.8k ReST) nearly as large as the code. The low comment count (986) is notable — the code relies on docstrings-in-docs rather than inline comments. At ~444k tokens the full pack fits a large context but not a small one; the digest or `src/flask`-only selection is ideal. Note files-to-prompt skips binary assets (`.png`) with warnings; all tools otherwise agree.
