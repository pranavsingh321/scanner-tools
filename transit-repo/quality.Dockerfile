# quality:latest — security & code-quality tools, selected per language at runtime
# based on inventory artifacts (scc.json). Kept separate from analyzers:latest.
FROM python:3.12-slim
ARG TARGETARCH
ENV GOSEC_VERSION=2.28.0 \
    STATICCHECK_VERSION=2026.1 \
    GITLEAKS_VERSION=8.30.1 \
    HADOLINT_VERSION=2.15.1 \
    GO_VERSION=1.26.5 \
    SEMGREP_RULES=/opt/semgrep/default.yaml

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates curl shellcheck \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir \
        semgrep==1.172.0 ruff==0.16.1 bandit==1.9.4

# Go toolchain (staticcheck/gosec shell out to `go` at runtime).
RUN set -eux; \
    curl -fsSLo /tmp/go.tgz "https://go.dev/dl/go${GO_VERSION}.linux-${TARGETARCH:-amd64}.tar.gz"; \
    tar xzf /tmp/go.tgz -C /usr/local; \
    rm -f /tmp/go.tgz; \
    /usr/local/go/bin/go version

# Go / static binaries (releases ship per-arch assets), plus the semgrep
# p/default ruleset vendored so scanning works fully offline.
RUN set -eux; arch="${TARGETARCH:-amd64}"; \
    mkdir -p /opt/tools /tmp/build; \
    curl -fsSLo /tmp/build/gosec.tgz "https://github.com/securego/gosec/releases/download/v${GOSEC_VERSION}/gosec_${GOSEC_VERSION}_linux_${arch}.tar.gz"; \
    tar xzf /tmp/build/gosec.tgz -C /opt/tools gosec; \
    curl -fsSLo /tmp/build/staticcheck.tgz "https://github.com/dominikh/go-tools/releases/download/${STATICCHECK_VERSION}/staticcheck_linux_${arch}.tar.gz"; \
    tar xzf /tmp/build/staticcheck.tgz -C /tmp/build; \
    mv /tmp/build/staticcheck/staticcheck /opt/tools/staticcheck; \
    garch="${arch}"; if [ "${arch}" = "amd64" ]; then garch=x64; fi; \
    curl -fsSLo /tmp/build/gitleaks.tgz "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_${garch}.tar.gz"; \
    tar xzf /tmp/build/gitleaks.tgz -C /opt/tools gitleaks; \
    harch="${arch}"; if [ "${arch}" = "amd64" ]; then harch=x86_64; fi; \
    curl -fsSLo /opt/tools/hadolint "https://github.com/hadolint/hadolint/releases/download/v${HADOLINT_VERSION}/hadolint-linux-${harch}"; \
    chmod +x /opt/tools/hadolint; \
    mkdir -p /opt/semgrep; \
    curl -fsSLo "${SEMGREP_RULES}" "https://semgrep.dev/c/p/default"; \
    rm -rf /tmp/build

ENV PATH="/opt/tools:/usr/local/go/bin:${PATH}"
WORKDIR /repo
