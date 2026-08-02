# os-neutron — Multi-tool summary

**Source:** https://github.com/openstack/neutron (OpenStack networking)
**Analyzed:** 2026-08-02, shallow clone, container image `analyzers:latest`
**Raw artifacts:** `artifacts/os-neutron/{tokei,scc,repomix,gitingest,files-to-prompt}/`

| Metric | Value |
|---|---|
| Files analyzed (gitingest) | 3,265 |
| Code LOC (tokei) | 451,899 |
| Comments (tokei) | 43,081 |
| Blank lines (tokei) | 75,341 |
| LLM token estimate (gitingest) | 5.0M |
| repomix pack size | 76 MB folder |

## Language mix
- tokei: Python 333,603, SVG 50,941, ReStructuredText 40,758
- scc: Python 331,188, SVG 50,941, ReStructuredText 40,758 — SVG and ReST **identical**; Python within 0.7%

## Top-level structure
`neutron/` (main package) + `api-ref/`, `devstack/`, `doc/`, `etc/`, `playbooks/`, `rally-jobs/`, `releasenotes/`, `roles/`, `scripts/`, `.agents/`

## My summary
Similar shape to nova but ~30% smaller (452k LOC, 5.0M tokens). `neutron/` holds the ML2 plugin, agents, and extensions; interestingly SVG files rank #2 in both tokei and scc — documentation diagrams dominate after Python. Whole-repo prompting is not feasible at 5M tokens; module scoping (`neutron/plugins`, `neutron/agent`) or a whatsun-style selected-file digest is recommended. The two LOC tools agree closely, confirming the numbers.
