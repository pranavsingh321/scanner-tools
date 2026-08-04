# glance — Multi-tool summary

**Source:** https://github.com/openstack/glance (OpenStack image service)
**Analyzed:** 2026-08-02, shallow clone, container image `analyzers:latest`
**Raw artifacts:** `artifacts/glance/{tokei,scc,repomix,gitingest,files-to-prompt}/`

| Metric | Value |
|---|---|
| Files analyzed (gitingest) | 923 |
| Code LOC (tokei) | 130,761 |
| Comments (tokei) | 13,661 |
| Blank lines (tokei) | 27,260 |
| LLM token estimate (gitingest) | 1.6M |
| repomix pack size | 22 MB folder |

## Language mix
- tokei: Python 81,597, PO File 23,057, ReStructuredText 11,213
- scc: Python 81,062, ReStructuredText 11,213, JSON 6,276 — ReST identical

## Top-level structure
`glance/` (main package), `api-ref/`, `doc/`, `etc/`, `httpd/`, `playbooks/`, `rally-jobs/`, `releasenotes/`, `tools/`, `test/`

## My summary
The smallest OpenStack service here (~130k LOC, 1.6M tokens) but still mid-sized. `glance/` contains the API server, registry, and store backends; a large PO (translation) set explains the 23k "code" lines. At 1.6M tokens it needs selection for most models — this is the sweet spot for whatsun's `digest` output (which reported an empty `selected_files` for this repo in the earlier whatsun run, worth double-checking). Tools agree closely on the core Python numbers.
