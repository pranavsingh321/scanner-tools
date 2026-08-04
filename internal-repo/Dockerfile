# internal-repo tool image: SBOM, SCA, secrets, SAST, malware, network/web scanning.
# Debian-based (glibc) because CodeQL is not compatible with musl/Alpine.
# Each tool runs inside a container against a repo mounted read-only at /repo
# with output written to /out.

FROM golang:bookworm AS build
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
ENV CGO_ENABLED=0
RUN go install github.com/google/osv-scanner/cmd/osv-scanner@latest
RUN go install github.com/zricethezav/gitleaks/v8@latest
RUN go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest
RUN go install github.com/projectdiscovery/naabu/v2/cmd/naabu@latest
RUN go install github.com/projectdiscovery/httpx/cmd/httpx@latest

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates git python3 python3-pip clamav \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY --from=build /go/bin/osv-scanner /go/bin/gitleaks \
    /go/bin/nuclei /go/bin/naabu /go/bin/httpx /usr/local/bin/

RUN curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/install.sh | sh -s -- -b /usr/local/bin \
    && curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin \
    && curl -sSfL https://raw.githubusercontent.com/trufflesecurity/trufflehog/main/scripts/install.sh | sh -s -- -b /usr/local/bin

RUN pip3 install --no-cache-dir --break-system-packages ggshield \
    && curl -fsSL https://raw.githubusercontent.com/opengrep/opengrep/main/install.sh | bash \
    && ln -s /root/.opengrep/cli/latest/opengrep /usr/local/bin/opengrep

# GitHub only publishes an x86_64 (linux64) CodeQL bundle, so it is installed on amd64 hosts only.
ARG TARGETARCH
RUN if [ "$TARGETARCH" = "amd64" ]; then \
        curl -sSL -o /tmp/codeql.tar.gz https://github.com/github/codeql-action/releases/latest/download/codeql-bundle-linux64.tar.gz \
        && mkdir -p /opt/codeql \
        && tar -xzf /tmp/codeql.tar.gz -C /opt/codeql \
        && rm -f /tmp/codeql.tar.gz \
        && ln -s /opt/codeql/codeql/codeql /usr/local/bin/codeql; \
    fi

WORKDIR /repo
