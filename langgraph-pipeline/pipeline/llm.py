"""OpenAI-compatible LLM client + prompt builders."""
from __future__ import annotations

import os

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI


def llm_configured() -> bool:
    """True when an OpenAI-compatible endpoint is available (key or local URL)."""
    return bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_BASE_URL"))


def get_llm() -> ChatOpenAI:
    """Chat model that speaks the OpenAI protocol.

    Point OPENAI_BASE_URL at any compatible endpoint (OpenAI, Ollama, vLLM,
    OpenRouter, LM Studio) and set OPENAI_API_KEY accordingly.
    """
    return ChatOpenAI(
        model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        api_key=os.environ.get("OPENAI_API_KEY", "not-needed"),
        base_url=os.environ.get("OPENAI_BASE_URL"),
        temperature=0,
    )


def summarize_messages(repo_name: str, source: str, metrics: str, findings: str) -> list:
    return [
        SystemMessage(content=(
            "You are a security/code-quality report writer. Given per-tool metrics and a "
            "list of findings for a repository, write a concise markdown report titled "
            f"'# {repo_name} — analysis summary'. Include a metrics table, a short "
            "'Tool results' section with the notable findings, and a 'Notes' section. "
            "Do not invent numbers. Be factual and terse. Output markdown only."
        )),
        HumanMessage(content=(
            f"Source: {source}\n\nMetrics:\n{metrics}\n\n"
            f"Findings (top, per tool):\n{findings}"
        )),
    ]


def remediate_system_prompt(name: str, repo_dir: str) -> str:
    return f"""You are an automated remediation engineer working in a git checkout at
{repo_dir} for the repo {name}. You are given structured findings from static/security
analysis. Your job is to fix the SAFE ones directly in the working tree.

Rules:
- Fix only issues you are confident about: leaked secrets (remove/redact), clear
  lint/static-analysis defects (unused imports, obvious bugs), and dependency version
  bumps to the fixed version when the next version is compatible.
- NEVER weaken security checks, delete test assertions, or reformat code merely to
  silence a linter unless the change is semantically identical.
- If a fix is risky, ambiguous, or requires network/credentials, skip it and explain why.
- After editing, run the verify tool (see tools) to re-check. Repeat until clean or you
  can't make safe progress.
- Do NOT commit or push; the orchestrator handles git. Only edit files on disk."""
