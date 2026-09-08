#!/usr/bin/env python3
"""Source-only knowledge graph + cyclomatic complexity extractor for Python.

Standard library only (the `ast` module), so it runs offline inside the
analyzers-java image and anywhere python3 exists.

Emits JSON shaped like the Java kg-extractor so the same digest/agent pipeline
consumes Python or Java repos: meta, summaries, nodes (module|class|function),
edges (CONTAINS, IMPORTS, EXTENDS, CALLS), plus package dependency rollups,
hub modules, isolated modules and module-level import cycles.

Usage: python3 py_kg_extractor.py -i <repo> -o <out.json> [-r name]
"""
import argparse
import ast
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

SKIP_DIRS = {".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv",
             "venv", "env", "build", "dist", "target", ".gradle", "out"}
EXTS = {".py"}
MAX_LISTINGS = 15
MAX_PKG_DEPS = 60
MAX_CYCLES = 30

NODES = []
NODE_BY_FQN = {}
EDGES = []
PENDING = []            # (etype, from_id, to_fqn, label) deferred resolution
MODULES = {}            # module fqn -> ModuleInfo
COMPLEXITY = {}         # function fqn -> cyclomatic complexity
EXTERNAL_REFS = {"count": 0}


class ModuleInfo:
    def __init__(self, fqn, path):
        self.fqn = fqn
        self.path = path
        self.module_aliases = {}    # alias -> imported module fqn
        self.imported_symbols = {}  # from-import name -> symbol fqn
        self.imported_fqns = []     # target fqns (module or symbol)
        self.fields = 0


# ------------------------------------------------------------------- helpers

def collect_files(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if os.path.splitext(fn)[1] in EXTS:
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def module_fqn(root, path):
    rel = os.path.relpath(path, root)
    rel = rel[:-3] if rel.endswith(".py") else rel
    return rel.replace(os.sep, ".") or "root"


def first_pkg(fqn):
    return fqn.split(".", 1)[0]


def loc_of(ast_node):
    start = getattr(ast_node, "lineno", 0)
    end = getattr(ast_node, "end_lineno", None) or start
    return max(1, end - start + 1)


def mk_node(kind, fqn, name, file, loc, abstract=False):
    node = {"id": len(NODES), "kind": kind, "fqn": fqn, "name": name,
            "label": fqn, "loc": loc, "file": file,
            "isInterface": False, "isAbstract": abstract}
    NODES.append(node)
    NODE_BY_FQN[fqn] = node
    return node


def emit_edge(frm, to, etype, label="", weight=1):
    EDGES.append({"from": frm, "to": to, "type": etype,
                  "label": label, "weight": weight})


def resolve(simple, scope):
    for sc in reversed(scope):
        if simple in sc:
            return sc[simple]
    return None


# -------------------------------------------------------------- complexity

_COMPLEX_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
                  ast.Match, ast.ListComp, ast.SetComp, ast.DictComp,
                  ast.GeneratorExp, ast.IfExp)


def _children_no_nested_funcs(node):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        yield child
        yield from _children_no_nested_funcs(child)


def complexity_of(node):
    cc = 1
    for child in _children_no_nested_funcs(node):
        if isinstance(child, _COMPLEX_NODES):
            cc += 1
        elif isinstance(child, ast.comprehension):
            cc += 1
        elif isinstance(child, ast.BoolOp):
            cc += len(child.values) - 1
    return cc


# ------------------------------------------------------------ import edges

def collect_imports(tree, mod):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = alias.name
                mod.module_aliases[alias.asname or target] = target
                mod.imported_fqns.append(target)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            for alias in node.names:
                fqn = node.module + "." + alias.name
                mod.imported_symbols[alias.asname or alias.name] = fqn
                mod.imported_fqns.append(fqn)
        elif isinstance(node, ast.ImportFrom):  # relative import
            EXTERNAL_REFS["count"] += len(node.names)


# ------------------------------------------------------- defs + call edges

def _is_abstract(node):
    if not isinstance(node, ast.ClassDef):
        return False
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and any(isinstance(d, ast.Name) and d.id == "abstractmethod"
                        for d in child.decorator_list):
            return True
    return False


def _class_fields(class_node):
    return sum(1 for st in class_node.body
               if isinstance(st, (ast.Assign, ast.AnnAssign, ast.AugAssign)))


def handle_calls(func_node, scope, owner_id):
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        label = None
        if isinstance(node.func, ast.Name):
            label = node.func.id
            resolved = resolve(node.func.id, scope)
        elif isinstance(node.func, ast.Attribute):
            label = node.func.attr
            resolved = _resolve_attr(node.func, scope)
        else:
            continue
        if resolved and resolved in NODE_BY_FQN:
            emit_edge(owner_id, NODE_BY_FQN[resolved]["id"], "CALLS", label=label)
        elif resolved:
            PENDING.append(("CALLS", owner_id, resolved, label))
        else:
            EXTERNAL_REFS["count"] += 1


def _resolve_attr(attr_node, scope):
    parts = []
    cur = attr_node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    parts.reverse()
    if isinstance(cur, ast.Name):
        base = resolve(cur.id, scope)
        if base:
            return ".".join([base] + parts)
    return None


def collect_defs(mod, tree):
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def container_of(node):
        p = parents.get(node)
        while p is not None and not isinstance(
                p, (ast.Module, ast.ClassDef, ast.FunctionDef,
                    ast.AsyncFunctionDef)):
            p = parents.get(p)
        return p

    mod_node_id = NODE_BY_FQN[mod.fqn]["id"]

    def register(node, scope, cid):
        name = node.name
        container = container_of(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "function"
            fqn = mod.fqn + "." + name
            if isinstance(container, ast.ClassDef):
                fqn = mod.fqn + "." + container.name + "." + name
            COMPLEXITY[fqn] = complexity_of(node)
        else:
            kind = "class"
            fqn = mod.fqn + "." + name
        node_dict = mk_node(kind, fqn, name, mod.path, loc_of(node),
                            abstract=_is_abstract(node))
        nid = node_dict["id"]
        emit_edge(cid, nid, "CONTAINS", label=name)
        mod.fields += _class_fields(node) if kind == "class" else 0

        if kind == "class":
            for base in node.bases:
                bref = None
                if isinstance(base, ast.Name):
                    bref = resolve(base.id, scope)
                elif isinstance(base, ast.Attribute):
                    bref = _resolve_attr(base, scope)
                if bref and bref in NODE_BY_FQN:
                    emit_edge(nid, NODE_BY_FQN[bref]["id"], "EXTENDS",
                              label=base.attr if isinstance(base, ast.Attribute)
                              else base.id)
                elif bref:
                    PENDING.append(("EXTENDS", nid, bref,
                                   base.attr if isinstance(base, ast.Attribute)
                                   else base.id))
                else:
                    EXTERNAL_REFS["count"] += 1

        inner_scope = dict(scope[-1]) if scope else {}
        inner_scope[name] = fqn
        if kind == "class":
            for st in node.body:
                if isinstance(st, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    targets = st.targets if isinstance(st, ast.Assign) \
                        else [st.target]
                    for tgt in targets:
                        if isinstance(tgt, ast.Name):
                            inner_scope[tgt.id] = fqn + "." + tgt.id
        body_scope = scope + [inner_scope]
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef,
                                  ast.AsyncFunctionDef)):
                register(child, body_scope, nid)
        if kind == "function":
            handle_calls(node, body_scope, nid)
        return nid

    scope = [dict(mod.module_aliases), dict(mod.imported_symbols)]
    for child in ast.iter_child_nodes(tree):
        if isinstance(child, (ast.ClassDef, ast.FunctionDef,
                              ast.AsyncFunctionDef)):
            register(child, scope, mod_node_id)
            scope[0][child.name] = mod.fqn + "." + child.name
        elif isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = child.targets if isinstance(child, ast.Assign) \
                else [child.target]
            for tgt in targets:
                if isinstance(tgt, ast.Name):
                    scope[0][tgt.id] = mod.fqn + "." + tgt.id


# ------------------------------------------------------------------- scan

def scan(root):
    result = {"files": 0, "parsed_files": 0, "parse_failures": 0}
    parsed = []
    for path in collect_files(root):
        result["files"] += 1
        fqn = module_fqn(root, path)
        mod = ModuleInfo(fqn, os.path.relpath(path, root))
        MODULES[fqn] = mod
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                src = fh.read()
        except OSError:
            result["parse_failures"] += 1
            continue
        try:
            tree = ast.parse(src, filename=path)
        except SyntaxError:
            result["parse_failures"] += 1
            continue
        result["parsed_files"] += 1
        mk_node("module", fqn, os.path.basename(path), mod.path,
                src.count("\n"))
        parsed.append((mod, tree))

    # Second pass so cross-module resolution sees every module/symbol node.
    for mod, tree in parsed:
        collect_imports(tree, mod)
        collect_defs(mod, tree)

    # Finalize deferred edges once every node is registered.
    for etype, from_id, to_fqn, label in PENDING:
        if to_fqn in NODE_BY_FQN:
            emit_edge(from_id, NODE_BY_FQN[to_fqn]["id"], etype, label=label)
        else:
            EXTERNAL_REFS["count"] += 1
    for mod in MODULES.values():
        mnode_id = NODE_BY_FQN[mod.fqn]["id"]
        for to_fqn in mod.imported_fqns:
            if to_fqn in NODE_BY_FQN:
                emit_edge(mnode_id, NODE_BY_FQN[to_fqn]["id"], "IMPORTS")
            elif to_fqn.split(".", 1)[0] in NODE_BY_FQN:
                emit_edge(mnode_id, NODE_BY_FQN[to_fqn.split(".", 1)[0]]["id"],
                          "IMPORTS")
            else:
                EXTERNAL_REFS["count"] += 1
    return result


# --------------------------------------------------------------- summaries

def find_module_cycles():
    graph = defaultdict(list)
    for e in EDGES:
        if e["type"] == "IMPORTS":
            frm, to = NODES[e["from"]], NODES[e["to"]]
            if frm["kind"] == "module" and to["kind"] == "module":
                graph[e["from"]].append(e["to"])
    on_path, seen, cycles = set(), set(), []
    stack = []

    def dfs(nid):
        if nid in on_path:
            if nid in stack:
                idx = stack.index(nid)
                nams = [NODES[i]["fqn"] for i in stack[idx:]]
                text = " -> ".join(nams + [nams[0]])
                if text not in cycles:
                    cycles.append(text)
                    if len(cycles) >= MAX_CYCLES:
                        raise StopIteration
            return
        if nid in seen:
            return
        seen.add(nid)
        on_path.add(nid)
        stack.append(nid)
        for nxt in graph.get(nid, []):
            dfs(nxt)
        stack.pop()
        on_path.discard(nid)

    try:
        for nid in list(graph):
            dfs(nid)
    except StopIteration:
        pass
    return cycles[:MAX_CYCLES]


def build_summaries(scan_result, repo_name):
    funcs = [n for n in NODES if n["kind"] == "function"]
    classes = [n for n in NODES if n["kind"] == "class"]
    modules = [n for n in NODES if n["kind"] == "module"]

    avg_cc = sum(COMPLEXITY.get(f["fqn"], 1) for f in funcs) / max(1, len(funcs))
    avg_loc = sum(f["loc"] for f in funcs) / max(1, len(funcs))

    def top(key, n=MAX_LISTINGS):
        return sorted(funcs, key=key, reverse=True)[:n]

    top_cc = top(lambda f: COMPLEXITY.get(f["fqn"], 1))
    top_loc = top(lambda f: f["loc"])
    top_cc = [{"module": ".".join(x["fqn"].split(".")[:-1]),
               "function": x["name"], "fqn": x["fqn"],
               "complexity": COMPLEXITY.get(x["fqn"], 1),
               "loc": x["loc"], "file": x["file"]} for x in top_cc]
    top_loc = [{"module": ".".join(x["fqn"].split(".")[:-1]),
                "function": x["name"], "fqn": x["fqn"],
                "loc": x["loc"], "file": x["file"]} for x in top_loc]

    edge_counts = defaultdict(int)
    for e in EDGES:
        edge_counts[e["type"]] += 1

    mod_edges = [e for e in EDGES if e["type"] == "IMPORTS"
                 and NODES[e["from"]]["kind"] == "module"
                 and NODES[e["to"]]["kind"] == "module"]
    indeg = defaultdict(int)
    outdeg = defaultdict(int)
    for e in mod_edges:
        outdeg[e["from"]] += 1
        indeg[e["to"]] += 1
    hubs = sorted(({"module": NODES[i]["fqn"], "deps": outdeg.get(i, 0),
                    "dependents": indeg.get(i, 0)}
                   for e in mod_edges for i in (e["from"], e["to"])
                   if NODES[i]["kind"] == "module"),
                  key=lambda h: (h["dependents"], h["deps"]),
                  reverse=True)
    hub_dedup = []
    seen_hub = set()
    for h in hubs:
        if h["module"] in seen_hub:
            continue
        seen_hub.add(h["module"])
        hub_dedup.append(h)
    hubs = hub_dedup[:20]

    pkg_deps = defaultdict(int)
    for e in EDGES:
        if e["type"] not in ("IMPORTS", "CALLS", "EXTENDS"):
            continue
        a, b = NODES[e["from"]]["fqn"], NODES[e["to"]]["fqn"]
        pa, pb = first_pkg(a), first_pkg(b)
        if pa and pb and pa != pb:
            pkg_deps[(pa, pb)] += e.get("weight", 1)
    pkg_deps = sorted(({"from": a, "to": b, "weight": w}
                       for (a, b), w in pkg_deps.items()),
                      key=lambda d: d["weight"], reverse=True)[:MAX_PKG_DEPS]

    isolated = sorted(n["fqn"] for n in modules
                      if outdeg.get(n["id"], 0) == 0
                      and indeg.get(n["id"], 0) == 0)

    return {
        "files": scan_result["files"],
        "parsed_files": scan_result["parsed_files"],
        "parse_failures": scan_result["parse_failures"],
        "modules": len(modules),
        "classes": len(classes),
        "functions": len(funcs),
        "methods": len(funcs),
        "fields": sum(m.fields for m in MODULES.values()),
        "packages": len({first_pkg(m) for m in MODULES}),
        "total_loc": sum(n["loc"] for n in modules),
        "external_type_references": EXTERNAL_REFS["count"],
        "avg_function_complexity": round(avg_cc, 2),
        "avg_function_loc": round(avg_loc, 2),
        "top_complexity_functions": top_cc,
        "top_loc_functions": top_loc,
        "edge_counts": dict(edge_counts),
        "hub_modules": hubs,
        "package_dependencies": pkg_deps,
        "isolated_modules": isolated,
        "dependency_cycles": find_module_cycles(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", required=True)
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("-r", "--repo", default="repo")
    args = ap.parse_args()

    root = os.path.abspath(args.input)
    if not os.path.isdir(root):
        print(f"error: not a directory: {root}", file=sys.stderr)
        sys.exit(1)

    scan_result = scan(root)
    summaries = build_summaries(scan_result, args.repo)
    doc = {
        "meta": {"repo": args.repo, "tool": "py-kg-extractor",
                 "generated": datetime.now(timezone.utc)
                 .isoformat().replace("+00:00", "Z")},
        "summaries": summaries,
        "nodes": NODES,
        "edges": EDGES,
    }
    out = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=True)
    print(f"done: {scan_result['files']} files, "
          f"{len(NODES)} nodes, {len(EDGES)} edges -> {out}",
          file=sys.stderr)


if __name__ == "__main__":
    main()