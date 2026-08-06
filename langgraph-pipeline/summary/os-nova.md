# os-nova — analysis summary

**Source:** https://github.com/openstack/nova

| Metric | Value |
|---|---|
| trivy | 0 |
| gitleaks | 48 |
| opengrep | 25 |
| clamav | 0 |

## Findings

### gitleaks (inventory, 48 findings)
- [generic-api-key] generic-api-key @ api-guide/source/request_and_response_formats.rst:21 — Detected a Generic API Key, potentially exposing access to various services and sensitive operations.
- [generic-api-key] generic-api-key @ api-guide/source/versions.rst:22 — Detected a Generic API Key, potentially exposing access to various services and sensitive operations.
- [generic-api-key] generic-api-key @ api-guide/source/versions.rst:32 — Detected a Generic API Key, potentially exposing access to various services and sensitive operations.
- [private-key] private-key @ doc/api_samples/os-certificates/certificate-create-resp.json:4 — Identified a Private Key, which may compromise cryptographic security and sensitive data encryption.
- [private-key] private-key @ doc/api_samples/os-keypairs/v2.2/keypairs-post-resp.json:6 — Identified a Private Key, which may compromise cryptographic security and sensitive data encryption.
- [private-key] private-key @ doc/api_samples/os-keypairs/keypairs-post-resp.json:5 — Identified a Private Key, which may compromise cryptographic security and sensitive data encryption.
- [private-key] private-key @ doc/api_samples/os-keypairs/v2.10/keypairs-post-resp.json:6 — Identified a Private Key, which may compromise cryptographic security and sensitive data encryption.
- [private-key] private-key @ doc/api_samples/os-keypairs/v2.35/keypairs-post-resp.json:6 — Identified a Private Key, which may compromise cryptographic security and sensitive data encryption.
### opengrep (inventory, 25 findings)
- [warning] python.lang.security.audit.non-literal-import.non-literal-import @ doc/ext/versioned_notifications.py:59 — Untrusted user input in `importlib.import_module()` function allows an attacker to load arbitrary code. Avoid dynamic values in `importlib.import_module()` or use a whitelist to prevent running untrus
- [error] javascript.lang.security.detect-insecure-websocket.detect-insecure-websocket @ doc/source/admin/figures/serial-console-flow.svg:276 — Insecure WebSocket Detected. WebSocket Secure (wss) should be used for all WebSocket connections.
- [error] javascript.lang.security.detect-insecure-websocket.detect-insecure-websocket @ doc/source/admin/figures/serial-console-flow.svg:504 — Insecure WebSocket Detected. WebSocket Secure (wss) should be used for all WebSocket connections.
- [error] javascript.lang.security.detect-insecure-websocket.detect-insecure-websocket @ doc/source/admin/manage-logs.rst:154 — Insecure WebSocket Detected. WebSocket Secure (wss) should be used for all WebSocket connections.
- [error] javascript.lang.security.detect-insecure-websocket.detect-insecure-websocket @ doc/source/admin/remote-console-access.rst:492 — Insecure WebSocket Detected. WebSocket Secure (wss) should be used for all WebSocket connections.
- [warning] python.lang.security.audit.non-literal-import.non-literal-import @ nova/conf/opts.py:64 — Untrusted user input in `importlib.import_module()` function allows an attacker to load arbitrary code. Avoid dynamic values in `importlib.import_module()` or use a whitelist to prevent running untrus
- [error] javascript.lang.security.detect-insecure-websocket.detect-insecure-websocket @ nova/conf/serial_console.py:69 — Insecure WebSocket Detected. WebSocket Secure (wss) should be used for all WebSocket connections.
- [warning] python.cryptography.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1 @ nova/crypto.py:91 — Detected SHA1 hash algorithm which is considered insecure. SHA1 is not collision resistant and is therefore not suitable as a cryptographic signature. Use SHA256 or SHA3 instead.

## Notes

Generated mechanically (no LLM endpoint configured). Re-run with OPENAI_API_KEY/OPENAI_BASE_URL set for an LLM-written report.
