"""Single-responsibility refactoring stage.

The refactor agent audits the analyzed code for units (functions, methods,
classes, modules) that mix multiple responsibilities, then refactors them into
single-responsibility units. Verification is the same tool-verify loop used by
remediation; the graph merges the refactor into the same branch/PR.
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from . import findings as F
from .agent_tools import make_agent_tools
from .config import RunConfig
from .llm import get_llm, llm_configured
from .state import RepoResult

MAX_REFACTOR_ROUNDS = 2


def refactor_system_prompt(name: str, repo_dir: str) -> str:
    return f"""You are a senior software architect working in the git checkout at {repo_dir}
for the repo {name}. Your task: improve code structure so that every unit has a single,
clearly named responsibility (Single Responsibility Principle).

Rules:
- Focus on the highest-value violations: functions doing several things, god classes,
  helpers buried inside unrelated modules, duplicated logic that should be extracted.
- Prefer small, safe, behavior-preserving refactors. Do NOT change public APIs used
  elsewhere unless you update all call sites in the same change. Do NOT change tests'
  meaning. Do NOT rename things for style only.
- Work on files on disk only; do NOT commit or push (the orchestrator handles git).
- After refactoring, run the verify tool (see tools) to confirm the code still passes
  analysis. If a refactor breaks analysis, fix it or revert it."""


def refactor_repo(
    cfg: RunConfig,
    repo: RepoResult,
    tools: list[str],
    script_for,
    image: str,
) -> str:
    """Invoke the refactor agent on the repo; returns its closing message."""
    if not llm_configured():
        print(f"==> [{repo.name}] refactor skipped (no LLM endpoint configured)")
        return "skipped: no LLM endpoint"

    prompt = (
        f"Repo: {repo.name}. The static-analysis tools that are available for "
        f"verification: {', '.join(tools)}. Audit the code in the working tree for "
        "single-responsibility violations, apply safe refactors, then run verify_tool "
        "for each tool to make sure nothing regressed."
    )
    agent = create_react_agent(
        model=get_llm(),
        tools=make_agent_tools(cfg, repo.repo_dir, repo.name, image, script_for),
        prompt=refactor_system_prompt(repo.name, repo.repo_dir),
    )
    result = agent.invoke({"messages": [HumanMessage(prompt)]})
    reply = result.get("messages", [])
    return str(reply[-1].content) if reply else "(no response)"
