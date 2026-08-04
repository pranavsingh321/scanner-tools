# k8s-kubernetes — Multi-tool summary

**Source:** https://github.com/kubernetes/kubernetes
**Analyzed:** 2026-08-02, shallow clone, container image `analyzers:latest`
**Raw artifacts:** `artifacts/k8s-kubernetes/{tokei,scc,repomix,gitingest,files-to-prompt}/`

| Metric | Value |
|---|---|
| Files analyzed (gitingest) | 10,002 (capped) |
| Code LOC (tokei) | 5,627,707 |
| Comments (tokei) | 973,407 |
| Blank lines (tokei) | 500,935 |
| LLM token estimate (gitingest) | 11.3M |
| repomix pack | 225 MB |
| files-to-prompt | 272 MB |

## Language mix
- tokei: Go 4,122,175, JSON 1,032,485, YAML 387,819
- scc: Go 4,128,172, JSON 1,032,528, YAML 217,837 — Go/JSON agree within 0.15%

## Top-level structure
`cmd/` (kube-apiserver, kubelet, kubectl, etc.), `pkg/` (under `src/k8s.io/kubernetes`), `staging/` (vendored k8s.io/* components), `cluster/`, `test/` (e2e/integration), `publishing/`. gitingest respects `.gitignore`, so `third_party/` and other ignored trees are excluded.

## My summary
The extreme case: 5.6M LOC, ~11.3M tokens — ~50x a 200k-token context. Even the *digest* file (46 MB) is large. Key takeaways:
- **Never pack this whole repo** — repomix produces a 225 MB file unusable as a prompt.
- gitingest's file cap (10,002) means its tree/digest is truncated; use it as a high-level index, not a census.
- For LLM work, use whatsun's `digest` (selected files) or scope to one subtree (`pkg/kubelet`, `pkg/apis/…`).
- scc and tokei are in tight agreement (Go ~4.12M LOC), so LOC numbers are trustworthy; YAML differs more (388k vs 218k) due to how code blocks/embedded YAML are counted.
