# os-nova — Multi-tool summary

**Source:** https://github.com/openstack/nova (OpenStack compute)
**Analyzed:** 2026-08-02, shallow clone, container image `analyzers:latest`
**Raw artifacts:** `artifacts/os-nova/{tokei,scc,repomix,gitingest,files-to-prompt}/`

| Metric | Value |
|---|---|
| Files analyzed (gitingest) | 4,752 |
| Code LOC (tokei) | 621,999 |
| Comments (tokei) | 65,997 |
| Blank lines (tokei) | 109,436 |
| LLM token estimate (gitingest) | 7.4M |
| repomix pack size | 98 MB folder |

## Language mix
- tokei: Python 467,305, ReStructuredText 46,752, PO File 26,214
- scc: Python 469,620, ReStructuredText 46,752, YAML 23,192 — strong agreement

## Top-level structure
`nova/` (main package), plus OpenStack-standard dirs: `api-guide/`, `api-ref/`, `doc/`, `devstack/`, `gate/`, `hooks/`, `playbooks/`, `releasenotes/`, `roles/`, `etc/`

## My summary
A very large Python codebase (~620k LOC, 7.4M tokens). `nova/` is the core (compute, scheduler, network, virt drivers) with heavy test coverage; docs/ReST and translation (PO) files make up a notable share. Token budget makes whole-repo prompting impractical — the whatsun digest (selected files) or per-module scope (`nova/compute`, `nova/scheduler`, `nova/virt`) is the right granularity. Cross-tool agreement is excellent (Python within 0.5%).
