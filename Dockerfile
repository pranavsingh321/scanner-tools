# syntax=docker/dockerfile:1
#
# Offline-ready Java analysis image.
#
# Build with network access on a connected machine, then transfer the image:
#     docker save analyzers-java:latest | gzip > analyzers-java.tar.gz
# On the air-gapped machine:
#     gunzip -c analyzers-java.tar.gz | docker load
# No network access is needed to scan afterwards.
#
# Optional: pre-seed the OWASP dependency-check NVD database by building with
# --build-arg PRESEED_NVD=1 (downloads the NVD feed during build, ~400 MB).
# Without it, dependency-check degrades gracefully to a static scan and logs a
# warning when the offline NVD database is unavailable.

ARG PMD_VERSION=7.27.0
ARG CHECKSTYLE_VERSION=14.1.0
ARG SPOTBUGS_VERSION=4.10.4
ARG FINDSECBUGS_VERSION=1.14.0
ARG DEPCHECK_VERSION=13.0.0
ARG PRESEED_NVD=0
ARG NVD_API_KEY=

# ---------------------------------------------------------------------------
# Stage 1: build scc (LOC + complexity metrics)
# ---------------------------------------------------------------------------
FROM golang:1.25-alpine AS scc
RUN apk add --no-cache git ca-certificates \
    && go install github.com/boyter/scc/v3@latest

# ---------------------------------------------------------------------------
# Stage 2: download and unpack the Java static analysis toolchain
# ---------------------------------------------------------------------------
FROM eclipse-temurin:21-jdk-alpine AS tools
ARG PMD_VERSION
ARG CHECKSTYLE_VERSION
ARG SPOTBUGS_VERSION
ARG FINDSECBUGS_VERSION
ARG DEPCHECK_VERSION
RUN apk add --no-cache wget unzip curl
RUN set -eux; \
    mkdir -p /opt;
# PMD (quality, error-prone, security, performance, design + CPD duplication)
RUN wget -q "https://github.com/pmd/pmd/releases/download/pmd_releases%2F${PMD_VERSION}/pmd-dist-${PMD_VERSION}-bin.zip" -O /tmp/pmd.zip \
    && unzip -q /tmp/pmd.zip -d /opt \
    && mv /opt/pmd-bin-${PMD_VERSION} /opt/pmd
# Checkstyle (Google/Java style conventions) + a concrete google_checks.xml config
RUN mkdir -p /opt/checkstyle \
    && wget -q "https://github.com/checkstyle/checkstyle/releases/download/checkstyle-${CHECKSTYLE_VERSION}/checkstyle-${CHECKSTYLE_VERSION}-all.jar" -O /opt/checkstyle/checkstyle.jar \
    && unzip -p /opt/checkstyle/checkstyle.jar google_checks.xml > /opt/checkstyle/google_checks.xml
# SpotBugs (bug patterns)
RUN wget -q "https://github.com/spotbugs/spotbugs/releases/download/${SPOTBUGS_VERSION}/spotbugs-${SPOTBUGS_VERSION}.zip" -O /tmp/spotbugs.zip \
    && unzip -q /tmp/spotbugs.zip -d /opt \
    && mv /opt/spotbugs-${SPOTBUGS_VERSION} /opt/spotbugs
# FindSecBugs (security detectors for SpotBugs)
RUN wget -q "https://repo1.maven.org/maven2/com/h3xstream/findsecbugs/findsecbugs-plugin/${FINDSECBUGS_VERSION}/findsecbugs-plugin-${FINDSECBUGS_VERSION}.jar" \
        -O /opt/spotbugs/plugin/findsecbugs-plugin.jar
# OWASP dependency-check (CVE scan of dependencies)
RUN wget -q "https://github.com/dependency-check/DependencyCheck/releases/download/v${DEPCHECK_VERSION}/dependency-check-${DEPCHECK_VERSION}-release.zip" -O /tmp/dc.zip \
    && unzip -q /tmp/dc.zip -d /opt

# Optionally pre-seed the NVD database (requires network at build time).
# NVD moved to an API-only feed that requires a free API key; request one at
# https://nvd.nist.gov/developers/request-an-api-key and pass it via:
#   docker build --build-arg PRESEED_NVD=1 --build-arg NVD_API_KEY=<key> ...
ARG PRESEED_NVD
ARG NVD_API_KEY
RUN if [ "$PRESEED_NVD" = "1" ]; then \
        args=""; \
        [ -n "$NVD_API_KEY" ] && args="--nvdApiKey $NVD_API_KEY"; \
        mkdir -p /opt/dependency-check/data && \
        /opt/dependency-check/bin/dependency-check.sh --updateonly \
            --data /opt/dependency-check/data $args || true; \
    fi

# ---------------------------------------------------------------------------
# Final image: fully self-contained, works with zero network access.
# ---------------------------------------------------------------------------
FROM eclipse-temurin:21-jdk-alpine
LABEL org.opencontainers.image.description="Offline static analysis toolkit: PMD, Checkstyle, SpotBugs+FindSecBugs, OWASP dependency-check, scc, repomix"
ENV JAVA_TOOL_OPTIONS="-Dfile.encoding=UTF-8"
ENV PATH="/opt/pmd/bin:$PATH"
ENV SPOTBUGS_HOME="/opt/spotbugs"
ENV DEPENDENCY_CHECK_HOME="/opt/dependency-check"
RUN apk add --no-cache bash git ca-certificates nodejs npm \
    && npm install -g repomix --silent \
    && rm -rf /root/.npm
# Python analyzers (ruff lint/quality, bandit security, radon complexity).
RUN apk add --no-cache python3 py3-pip \
    && python3 -m pip install --no-cache-dir --break-system-packages \
        ruff bandit radon \
    && rm -rf /root/.cache/pip \
    && python3 --version && ruff --version && bandit --version && radon --version
COPY --from=tools   /opt/pmd              /opt/pmd
COPY --from=tools   /opt/checkstyle       /opt/checkstyle
COPY --from=tools   /opt/spotbugs         /opt/spotbugs
COPY --from=tools   /opt/dependency-check /opt/dependency-check
COPY --from=scc     /go/bin/scc           /usr/local/bin/scc
WORKDIR /repo