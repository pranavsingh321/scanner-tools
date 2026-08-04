# multi-tool

Two independent, containerized analysis repos, each self-contained (own driver script, image build, artifacts, and summaries):

| Folder | What it is |
|---|---|
| `transit-repo/` | Repo analysis / ingestion: `tokei`, `scc`, `repomix`, `gitingest`, `files-to-prompt` |
| `internal-repo/` | Security analysis: SBOM (Syft), dependency scanning (Trivy, osv-scanner), secrets (gitleaks, ggshield), code analysis (opengrep, CodeQL), malware (ClamAV), network/web (nuclei, naabu, httpx) + documented services (SonarQube, ZAP, OpenVAS, Falco) |

Both folders follow the same layout and are run independently:

```
<repo>/
├── run-tools.sh      # driver script (container dispatch, artifact writing)
├── Dockerfile        # builds the tool image
├── README.md         # tool mapping, usage, comparison
├── artifacts/        # raw output, artifacts/<repo>/<tool>/
└── summary/          # per-repo markdown summaries
```

See each folder's own `README.md` for usage.
