package scanner.tools;

import com.github.javaparser.JavaParser;
import com.github.javaparser.ParseResult;
import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.AnnotationDeclaration;
import com.github.javaparser.ast.body.BodyDeclaration;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.ConstructorDeclaration;
import com.github.javaparser.ast.body.EnumDeclaration;
import com.github.javaparser.ast.body.FieldDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.Parameter;
import com.github.javaparser.ast.body.RecordDeclaration;
import com.github.javaparser.ast.body.TypeDeclaration;
import com.github.javaparser.ast.body.VariableDeclarator;
import com.github.javaparser.ast.expr.BinaryExpr;
import com.github.javaparser.ast.expr.ConditionalExpr;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.expr.NameExpr;
import com.github.javaparser.ast.expr.ObjectCreationExpr;
import com.github.javaparser.ast.expr.TypeExpr;
import com.github.javaparser.ast.stmt.CatchClause;
import com.github.javaparser.ast.stmt.DoStmt;
import com.github.javaparser.ast.stmt.ForEachStmt;
import com.github.javaparser.ast.stmt.ForStmt;
import com.github.javaparser.ast.stmt.IfStmt;
import com.github.javaparser.ast.stmt.SwitchEntry;
import com.github.javaparser.ast.stmt.WhileStmt;
import com.github.javaparser.ast.type.ArrayType;
import com.github.javaparser.ast.type.ClassOrInterfaceType;
import com.github.javaparser.ast.type.PrimitiveType;
import com.github.javaparser.ast.type.Type;
import com.github.javaparser.ast.type.VarType;
import com.github.javaparser.ast.visitor.VoidVisitorAdapter;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Collectors;

/**
 * Offline, source-only knowledge graph and complexity extractor for Java repositories.
 * Uses JavaParser to read *.java files and emits JSON:
 *   nodes: package, class|interface|enum|record|annotation
 *   edges: CONTAINS, CONTAINS_NESTED, EXTENDS, IMPLEMENTS, DEPENDS_ON, INVOKES
 * plus aggregate summaries (cyclomatic complexity, hub types, package dependencies, cycles).
 * No compilation and no network access required at scan time.
 */
public final class KnowledgeGraphExtractor {

    private KnowledgeGraphExtractor() {}

    // -------- lightweight models ----------

    static final class MethodModel {
        String name;
        String returnType = "";
        final List<String> params = new ArrayList<>();
        int loc;
        int complexity;
        boolean hasBody;
    }

    static final class FieldModel {
        String name;
        String type;
        boolean isStatic;
        boolean isFinal;
    }

    static final class TypeModel {
        String fqn;
        String simple;
        String kind;                 // class|interface|enum|record|annotation
        String parentFqn;
        boolean isInterface;
        String file;
        int loc;
        final List<String> modifiers = new ArrayList<>();
        String superName;
        final List<String> implNames = new ArrayList<>();
        final Map<String, Integer> refs = new LinkedHashMap<>();      // simple type name -> count
        final Map<String, Set<String>> calls = new LinkedHashMap<>(); // target simple name -> method names
        final List<MethodModel> methods = new ArrayList<>();
        final List<FieldModel> fields = new ArrayList<>();
    }

    static final class FileModel {
        String pkg = "";
        final Map<String, String> importSimpleToFqn = new LinkedHashMap<>();
        final List<TypeModel> types = new ArrayList<>();
    }

    static final class Node {
        int id;
        String label;
        String name;
        String fqn;
        String kind;
        String file;
        int loc;
        boolean isInterface;
        boolean isAbstract;
    }

    static final class Edge {
        int from, to;
        String type;
        String label;
        int weight;
    }

    // -------- CLI ----------

    public static void main(String[] args) throws IOException {
        String input = null, output = null, repo = "unknown";
        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "-i": case "--input":  input = args[++i]; break;
                case "-o": case "--output": output = args[++i]; break;
                case "-r": case "--repo":   repo = args[++i]; break;
                default: System.err.println("Unknown argument: " + args[i]); usage(); return;
            }
        }
        if (input == null) { usage(); return; }

        Path root = Path.of(input).toAbsolutePath().normalize();
        if (!Files.isDirectory(root)) {
            System.err.println("Not a directory: " + root);
            System.exit(2);
        }

        List<Path> javaFiles = findJavaFiles(root);

        ParserConfiguration config = new ParserConfiguration()
                .setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_21);
        JavaParser parser = new JavaParser(config);

        // ---- Pass 1: parse, build lightweight models, register known FQNs ----
        List<FileModel> files = new ArrayList<>();
        for (Path f : javaFiles) {
            FileModel fm = new FileModel();
            CompilationUnit cu = parse(parser, f);
            if (cu == null) { parsedFail++; continue; }
            parsedOk++;
            fileCount++;
            cu.getPackageDeclaration().ifPresent(pd -> fm.pkg = pd.getNameAsString());
            for (var imp : cu.getImports()) {
                String n = imp.getNameAsString();
                if (imp.isStatic() || imp.isAsterisk()) continue;
                fm.importSimpleToFqn.putIfAbsent(simpleName(n), n);
            }
            String pkg = fm.pkg;
            for (TypeDeclaration<?> td : cu.getTypes()) {
                fm.types.addAll(collectTypes(td, pkg, null, 0, f.toString()));
            }
            for (TypeModel tm : fm.types) {
                knownFqns.add(tm.fqn);
                modelByFqn.put(tm.fqn, tm);
            }
            files.add(fm);
        }

        // package nodes first (deterministic order)
        Map<String, Integer> pkgNodeIds = new LinkedHashMap<>();
        for (FileModel fm : files) {
            pkgNodeIds.computeIfAbsent(fm.pkg, p -> makePackageNode(p).id);
        }

        // ---- Pass 2: nodes and edges ----
        for (FileModel fm : files) {
            int pkgId = pkgNodeIds.get(fm.pkg);
            Map<String, String> simpleToFqn = buildResolutionMap(fm);
            for (TypeModel tm : fm.types) {
                Node n = makeTypeNode(tm);
                addEdge(pkgId, n.id, "CONTAINS", null, 1);
                if (tm.parentFqn != null) {
                    Node parent = nodeByFqn.get(tm.parentFqn);
                    if (parent != null) addEdge(parent.id, n.id, "CONTAINS_NESTED", null, 1);
                }
                if (tm.superName != null) {
                    Integer target = typeNodeFor(simpleToFqn, tm.superName);
                    if (target != null) addEdge(n.id, target, "EXTENDS", null, 1);
                }
                for (String iface : tm.implNames) {
                    Integer target = typeNodeFor(simpleToFqn, iface);
                    if (target != null) addEdge(n.id, target, "IMPLEMENTS", null, 1);
                }
                for (Map.Entry<String, Integer> r : tm.refs.entrySet()) {
                    String fqn = resolve(simpleToFqn, r.getKey(), fm);
                    if (fqn == null) { externalTypeRefs += r.getValue(); continue; }
                    Node t = nodeByFqn.get(fqn);
                    if (t != null) addEdge(n.id, t.id, "DEPENDS_ON", null, r.getValue());
                }
                for (Map.Entry<String, Set<String>> c : tm.calls.entrySet()) {
                    String target = resolve(simpleToFqn, c.getKey(), fm);
                    if (target == null) continue;
                    Node t = nodeByFqn.get(target);
                    if (t == null) continue;
                    for (String m : c.getValue()) addEdge(n.id, t.id, "INVOKES", m, 1);
                }
            }
        }

        String json = renderJson(repo, buildSummaries());
        if (output == null) {
            System.out.print(json);
        } else {
            Files.writeString(Path.of(output), json, StandardCharsets.UTF_8);
            System.err.println("Parsed " + parsedOk + " files (" + parsedFail + " failed) -> " + output);
        }
    }

    static void usage() {
        System.err.println("Usage: kg-extractor -i <srcDir> [-o <out.json>] [-r <repoName>]");
    }

    // -------- parsing ----------

    static CompilationUnit parse(JavaParser parser, Path file) {
        try {
            ParseResult<CompilationUnit> pr = parser.parse(file.toFile());
            if (pr.isSuccessful() && pr.getResult().isPresent()) return pr.getResult().get();
            return null;
        } catch (Exception e) {
            return null;
        }
    }

    static String simpleName(String fqn) {
        if (fqn == null || fqn.isEmpty()) return "";
        int last = Math.max(fqn.lastIndexOf('.'), fqn.lastIndexOf('$'));
        return last < 0 ? fqn : fqn.substring(last + 1);
    }

    static List<TypeModel> collectTypes(TypeDeclaration<?> td, String pkg, String parentFqn,
                                        int depth, String file) {
        List<TypeModel> result = new ArrayList<>();
        String simple = td.getNameAsString();
        String prefix = parentFqn != null ? parentFqn : ((pkg == null || pkg.isEmpty()) ? "" : pkg);
        String fqn = prefix.isEmpty() ? simple : prefix + "." + simple;

        TypeModel m = new TypeModel();
        m.fqn = fqn;
        m.simple = simple;
        m.parentFqn = parentFqn;
        m.file = file;
        td.getRange().ifPresent(r -> m.loc = r.end.line - r.begin.line + 1);

        if (td instanceof ClassOrInterfaceDeclaration cio) {
            m.kind = cio.isInterface() ? "interface" : "class";
            m.isInterface = cio.isInterface();
            if (!cio.isInterface()) {
                cio.getExtendedTypes().forEach(t -> m.superName = t.getNameAsString());
            }
            cio.getImplementedTypes().forEach(t -> m.implNames.add(t.getNameAsString()));
        } else if (td instanceof EnumDeclaration en) {
            m.kind = "enum";
            en.getImplementedTypes().forEach(t -> m.implNames.add(t.getNameAsString()));
        } else if (td instanceof RecordDeclaration rec) {
            m.kind = "record";
            rec.getImplementedTypes().forEach(t -> m.implNames.add(t.getNameAsString()));
        } else if (td instanceof AnnotationDeclaration) {
            m.kind = "annotation";
        } else {
            m.kind = "class";
        }

        for (BodyDeclaration<?> member : td.getMembers()) {
            if (member instanceof MethodDeclaration md) {
                m.methods.add(methodModel(md, simple));
            } else if (member instanceof ConstructorDeclaration cd) {
                MethodModel mm = new MethodModel();
                mm.name = "new " + simple;
                for (Parameter p : cd.getParameters()) mm.params.add(typeName(p.getType()));
                mm.hasBody = cd.getBody() != null;
                cd.getRange().ifPresent(rr -> mm.loc = rr.end.line - rr.begin.line + 1);
                mm.complexity = mm.hasBody ? cyclomatic(cd.getBody()) : 1;
                m.methods.add(mm);
            } else if (member instanceof FieldDeclaration fd) {
                for (VariableDeclarator vd : fd.getVariables()) {
                    FieldModel fm = new FieldModel();
                    fm.name = vd.getNameAsString();
                    fm.type = typeName(fd.getElementType());
                    fm.isStatic = fd.isStatic();
                    fm.isFinal = fd.isFinal();
                    m.fields.add(fm);
                }
            } else if (member instanceof TypeDeclaration<?> nested) {
                result.addAll(collectTypes(nested, pkg, m.fqn, depth + 1, file));
            }
        }

        harvestReferences(td, m);
        result.add(m);
        return result;
    }

    static MethodModel methodModel(MethodDeclaration md, String ownerSimple) {
        MethodModel mm = new MethodModel();
        mm.name = md.getNameAsString();
        mm.returnType = typeName(md.getType());
        for (Parameter p : md.getParameters()) mm.params.add(typeName(p.getType()));
        mm.hasBody = md.getBody().isPresent();
        if (mm.hasBody) {
            md.getBody().get().getRange().ifPresent(r -> mm.loc = r.end.line - r.begin.line + 1);
            mm.complexity = cyclomatic(md.getBody().get());
        } else {
            mm.loc = 0;
            mm.complexity = 1;
        }
        return mm;
    }

    static String typeName(Type t) {
        if (t instanceof ClassOrInterfaceType c) return stripGenerics(c.getNameAsString());
        if (t instanceof PrimitiveType p) return p.asString();
        if (t instanceof ArrayType a) return typeName(a.getComponentType()) + "[]";
        if (t instanceof VarType) return "var";
        return t.toString();
    }

    static String stripGenerics(String s) {
        int i = s.indexOf('<');
        return i < 0 ? s : s.substring(0, i);
    }

    /** AST-based cyclomatic complexity: 1 + decision points. */
    static int cyclomatic(com.github.javaparser.ast.stmt.Statement body) {
        AtomicInteger cc = new AtomicInteger(1);
        body.accept(new VoidVisitorAdapter<Void>() {
            @Override public void visit(IfStmt n, Void a)   { cc.incrementAndGet(); super.visit(n, a); }
            @Override public void visit(ForStmt n, Void a)  { cc.incrementAndGet(); super.visit(n, a); }
            @Override public void visit(ForEachStmt n, Void a) { cc.incrementAndGet(); super.visit(n, a); }
            @Override public void visit(WhileStmt n, Void a){ cc.incrementAndGet(); super.visit(n, a); }
            @Override public void visit(DoStmt n, Void a)   { cc.incrementAndGet(); super.visit(n, a); }
            @Override public void visit(SwitchEntry n, Void a) { cc.incrementAndGet(); super.visit(n, a); }
            @Override public void visit(CatchClause n, Void a) { cc.incrementAndGet(); super.visit(n, a); }
            @Override public void visit(ConditionalExpr n, Void a) { cc.incrementAndGet(); super.visit(n, a); }
            @Override public void visit(BinaryExpr n, Void a) {
                if (n.getOperator() == BinaryExpr.Operator.AND || n.getOperator() == BinaryExpr.Operator.OR) {
                    cc.incrementAndGet();
                }
                super.visit(n, a);
            }
        }, null);
        return cc.get();
    }

    static void harvestReferences(TypeDeclaration<?> td, TypeModel m) {
        td.accept(new VoidVisitorAdapter<Void>() {
            @Override public void visit(ClassOrInterfaceType n, Void a) {
                String name = stripGenerics(n.getNameAsString());
                if (!name.equals(m.simple)) m.refs.merge(name, 1, Integer::sum);
                super.visit(n, a);
            }
            @Override public void visit(MethodCallExpr n, Void a) {
                if (n.getScope().isPresent() && n.getScope().get() instanceof NameExpr scope) {
                    m.calls.computeIfAbsent(scope.getNameAsString(), k -> new HashSet<>())
                            .add(n.getNameAsString());
                }
                super.visit(n, a);
            }
            @Override public void visit(ObjectCreationExpr n, Void a) {
                String name = stripGenerics(n.getType().getNameAsString());
                if (!name.equals(m.simple)) m.refs.merge(name, 1, Integer::sum);
                super.visit(n, a);
            }
            @Override public void visit(TypeExpr n, Void a) {
                if (n.getType() instanceof ClassOrInterfaceType c) {
                    String name = stripGenerics(c.getNameAsString());
                    if (!name.equals(m.simple)) m.refs.merge(name, 1, Integer::sum);
                }
                super.visit(n, a);
            }
        }, null);

        // nest method calls into a same-type ref is handled above; also drop self-calls later.
    }

    // -------- resolution ----------

    static Map<String, String> buildResolutionMap(FileModel fm) {
        Map<String, String> map = new HashMap<>(fm.importSimpleToFqn);
        for (TypeModel t : fm.types) {
            map.putIfAbsent(t.simple, t.fqn);
            if (t.parentFqn != null) {
                int i = t.parentFqn.lastIndexOf('.');
                String parentSimple = i < 0 ? t.parentFqn : t.parentFqn.substring(i + 1);
                map.putIfAbsent(parentSimple + "." + t.simple, t.fqn);
            }
        }
        return map;
    }

    static String resolve(Map<String, String> simpleToFqn, String simple, FileModel fm) {
        String s = stripGenerics(simple).trim();
        if (s.isEmpty()) return null;
        if (s.contains(".")) return knownFqns.contains(s) ? s : null;
        String direct = simpleToFqn.get(s);
        if (direct != null && knownFqns.contains(direct)) return direct;
        if (!fm.pkg.isEmpty()) {
            String cand = fm.pkg + "." + s;
            if (knownFqns.contains(cand)) return cand;
        }
        if (s.equals("String") || s.equals("Object") || s.equals("Integer")
                || s.equals("Long") || s.equals("Double") || s.equals("Exception")
                || s.equals("RuntimeException") || s.equals("Iterable")) {
            return null; // java.lang externals
        }
        return null;
    }

    // -------- nodes / edges ----------

    static final List<Node> nodes = new ArrayList<>();
    static final List<Edge> edges = new ArrayList<>();
    static final Set<String> knownFqns = new HashSet<>();
    static final Map<String, TypeModel> modelByFqn = new LinkedHashMap<>();
    static final Map<String, Node> nodeByFqn = new LinkedHashMap<>();
    static final Map<Integer, Node> nodeById = new HashMap<>();
    static int nextId = 0;
    static long totalLoc = 0;
    static int fileCount = 0, parsedOk = 0, parsedFail = 0,
               typeCount = 0, methodCount = 0, methodBodyCount = 0, fieldCount = 0;
    static long externalTypeRefs = 0;

    static Node makePackageNode(String pkg) {
        Node n = new Node();
        n.id = nextId++;
        n.label = "package";
        n.name = pkg.isEmpty() ? "(default)" : pkg;
        nodes.add(n);
        return n;
    }

    static Node makeTypeNode(TypeModel tm) {
        Node n = new Node();
        n.id = nextId++;
        n.label = "type";
        n.name = tm.simple;
        n.fqn = tm.fqn;
        n.kind = tm.kind;
        n.file = tm.file;
        n.loc = tm.loc;
        n.isInterface = tm.isInterface;
        nodes.add(n);
        nodeByFqn.put(tm.fqn, n);
        nodeById.put(n.id, n);
        typeCount++;
        methodCount += tm.methods.size();
        fieldCount += tm.fields.size();
        totalLoc += tm.loc;
        for (MethodModel mm : tm.methods) if (mm.hasBody) methodBodyCount++;
        return n;
    }

    static Integer typeNodeFor(Map<String, String> simpleToFqn, String simple) {
        if (simple == null) return null;
        String target = simpleToFqn.get(stripGenerics(simple));
        if (target == null) return null;
        Node t = nodeByFqn.get(target);
        return t != null ? t.id : null;
    }

    static void addEdge(int from, int to, String type, String label, int weight) {
        for (Edge e : edges) {
            if (e.from == from && e.to == to && e.type.equals(type) &&
                    (e.label == null ? label == null : e.label.equals(label))) {
                e.weight += weight;
                return;
            }
        }
        Edge e = new Edge();
        e.from = from; e.to = to; e.type = type; e.label = label; e.weight = weight;
        edges.add(e);
    }

    // -------- summaries ----------

    static Map<String, Object> buildSummaries() {
        Map<String, Object> s = new LinkedHashMap<>();
        s.put("files", fileCount);
        s.put("parsed_files", parsedOk);
        s.put("parse_failures", parsedFail);
        s.put("packages", countPackages());
        s.put("types", typeCount);
        s.put("methods", methodCount);
        s.put("methods_with_bodies", methodBodyCount);
        s.put("fields", fieldCount);
        s.put("total_loc", totalLoc);
        s.put("external_type_references", externalTypeRefs);
        s.put("avg_type_loc", round(totalLoc / (double) Math.max(1, typeCount)));

        List<Map<String, Object>> topComplex = new ArrayList<>();
        List<Map<String, Object>> topLoc = new ArrayList<>();
        double sumComplex = 0, sumLoc = 0;
        for (TypeModel tm : modelByFqn.values()) {
            for (MethodModel mm : tm.methods) {
                if (!mm.hasBody) continue;
                sumComplex += mm.complexity;
                sumLoc += mm.loc;
                topComplex.add(map("type", tm.fqn, "method", mm.name, "complexity", mm.complexity,
                        "loc", mm.loc, "file", tm.file));
                topLoc.add(map("type", tm.fqn, "method", mm.name, "loc", mm.loc,
                        "complexity", mm.complexity, "file", tm.file));
            }
        }
        topComplex.sort((a, b) -> intVal(b, "complexity") - intVal(a, "complexity"));
        topLoc.sort((a, b) -> intVal(b, "loc") - intVal(a, "loc"));
        s.put("avg_method_complexity", round(sumComplex / (double) Math.max(1, methodBodyCount)));
        s.put("avg_method_loc", round(sumLoc / (double) Math.max(1, methodBodyCount)));
        s.put("top_complexity_methods", topComplex.subList(0, Math.min(15, topComplex.size())));
        s.put("top_loc_methods", topLoc.subList(0, Math.min(15, topLoc.size())));

        int[] ec = {0, 0, 0, 0};
        Map<Integer, Integer> outDeg = new HashMap<>(), inDeg = new HashMap<>();
        for (Edge e : edges) {
            if (e.type.equals("CONTAINS") || e.type.equals("CONTAINS_NESTED")) continue;
            outDeg.merge(e.from, 1, Integer::sum);
            inDeg.merge(e.to, 1, Integer::sum);
            switch (e.type) {
                case "EXTENDS": ec[0]++; break;
                case "IMPLEMENTS": ec[1]++; break;
                case "DEPENDS_ON": ec[2]++; break;
                case "INVOKES": ec[3]++; break;
                default: break;
            }
        }
        s.put("edge_counts", map("extends", ec[0], "implements", ec[1],
                "depends_on", ec[2], "invokes", ec[3]));

        List<Map<String, Object>> hubs = new ArrayList<>();
        for (TypeModel tm : modelByFqn.values()) {
            Node n = nodeByFqn.get(tm.fqn);
            if (n == null) continue;
            int deps = outDeg.getOrDefault(n.id, 0);
            int dependents = inDeg.getOrDefault(n.id, 0);
            if (deps > 0 || dependents > 0) {
                hubs.add(map("type", tm.fqn, "deps", deps, "dependents", dependents));
            }
        }
        hubs.sort((a, b) -> (intVal(b, "deps") + intVal(b, "dependents")) - (intVal(a, "deps") + intVal(a, "dependents")));
        s.put("hub_types", hubs.subList(0, Math.min(20, hubs.size())));

        Map<String, Map<String, Integer>> pkgDeps = new LinkedHashMap<>();
        Set<String> allPkgs = new HashSet<>();
        for (TypeModel tm : modelByFqn.values()) {
            String p1 = packageOf(tm.fqn);
            allPkgs.add(p1);
            Node n = nodeByFqn.get(tm.fqn);
            if (n == null) continue;
            for (Edge e : edges) {
                if (e.from != n.id || !(e.type.equals("DEPENDS_ON") || e.type.equals("INVOKES"))) continue;
                Node t = nodeById(e.to);
                if (t == null) continue;
                String p2 = packageOf(t.fqn);
                allPkgs.add(p2);
                if (!p1.equals(p2)) {
                    pkgDeps.computeIfAbsent(p1, k -> new LinkedHashMap<>()).merge(p2, e.weight, Integer::sum);
                }
            }
        }
        List<Map<String, Object>> pkgDepList = new ArrayList<>();
        for (Map.Entry<String, Map<String, Integer>> e1 : pkgDeps.entrySet()) {
            for (Map.Entry<String, Integer> e2 : e1.getValue().entrySet()) {
                pkgDepList.add(map("from", e1.getKey(), "to", e2.getKey(), "weight", e2.getValue()));
            }
        }
        pkgDepList.sort((a, b) -> intVal(b, "weight") - intVal(a, "weight"));
        s.put("package_dependencies", pkgDepList.subList(0, Math.min(60, pkgDepList.size())));

        List<String> isolated = allPkgs.stream()
                .filter(p -> !pkgDeps.containsKey(p))
                .sorted().collect(Collectors.toCollection(ArrayList::new));
        s.put("isolated_packages", isolated);

        s.put("dependency_cycles", findCycles());
        return s;
    }

    static int countPackages() {
        Set<String> pkgs = new HashSet<>();
        for (TypeModel tm : modelByFqn.values()) pkgs.add(packageOf(tm.fqn));
        return pkgs.size();
    }

    static String packageOf(String fqn) {
        int i = fqn.lastIndexOf('.');
        return i < 0 ? "(default)" : fqn.substring(0, i);
    }

    /** Detect simple 2-cycles between types (A depends on B and B depends on A). */
    static List<String> findCycles() {
        Map<String, Edge> byPair = new HashMap<>();
        Set<String> cycles = new HashSet<>();
        for (Edge e : edges) {
            if (!e.type.equals("DEPENDS_ON")) continue;
            String key = e.from + ":" + e.to;
            String rev = e.to + ":" + e.from;
            Edge other = byPair.get(rev);
            if (other != null) {
                Node a = nodeById(e.from), b = nodeById(e.to);
                if (a != null && b != null) {
                    String shorter = a.fqn.compareTo(b.fqn) <= 0 ? a.fqn + " <-> " + b.fqn : b.fqn + " <-> " + a.fqn;
                    cycles.add(shorter);
                }
            }
            byPair.put(key, e);
        }
        List<String> sorted = new ArrayList<>(cycles);
        sorted.sort(String::compareTo);
        return sorted.subList(0, Math.min(30, sorted.size()));
    }

    static Node nodeById(int id) {
        return nodeByIdMap.get(id);
    }

    static final Map<Integer, Node> nodeByIdMap = nodeById;

    // -------- rendering ----------

    static String renderJson(String repo, Map<String, Object> summaries) {
        StringBuilder sb = new StringBuilder();
        sb.append("{\n");
        sb.append("  \"meta\": ")
          .append("{\"repo\":").append(js(repo))
          .append(",\"tool\":\"kg-extractor 1.0.0\"")
          .append(",\"generated\":").append(System.currentTimeMillis())
          .append("},\n");
        sb.append("  \"summaries\": ").append(objToJson(summaries)).append(",\n");
        sb.append("  \"nodes\": [\n");
        for (int i = 0; i < nodes.size(); i++) {
            sb.append(i == 0 ? "    " : ",\n    ").append(nodeToJson(nodes.get(i)));
        }
        sb.append("\n  ],\n");
        sb.append("  \"edges\": [\n");
        for (int i = 0; i < edges.size(); i++) {
            sb.append(i == 0 ? "    " : ",\n    ").append(edgeToJson(edges.get(i)));
        }
        sb.append("\n  ]\n");
        sb.append("}\n");
        return sb.toString();
    }

    static String nodeToJson(Node n) {
        StringBuilder sb = new StringBuilder();
        sb.append('{').append("\"id\":").append(n.id)
          .append(",\"label\":").append(js(n.label))
          .append(",\"name\":").append(js(n.name));
        if (n.fqn != null) sb.append(",\"fqn\":").append(js(n.fqn));
        if (n.kind != null) sb.append(",\"kind\":").append(js(n.kind));
        if (n.loc > 0) sb.append(",\"loc\":").append(n.loc);
        if (n.isInterface) sb.append(",\"isInterface\":true");
        if (n.isAbstract) sb.append(",\"isAbstract\":true");
        if (n.file != null) sb.append(",\"file\":").append(js(n.file));
        return sb.append('}').toString();
    }

    static String edgeToJson(Edge e) {
        StringBuilder sb = new StringBuilder();
        sb.append('{').append("\"from\":").append(e.from)
          .append(",\"to\":").append(e.to)
          .append(",\"type\":").append(js(e.type));
        if (e.label != null) sb.append(",\"label\":").append(js(e.label));
        if (e.weight != 1) sb.append(",\"weight\":").append(e.weight);
        return sb.append('}').toString();
    }

    // -------- JSON helpers ----------

    static String js(String s) {
        if (s == null) return "null";
        StringBuilder sb = new StringBuilder("\"");
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
            }
        }
        return sb.append('"').toString();
    }

    @SuppressWarnings("unchecked")
    static String objToJson(Map<String, Object> m) {
        StringBuilder sb = new StringBuilder();
        sb.append('{');
        boolean first = true;
        for (Map.Entry<String, Object> e : m.entrySet()) {
            if (!first) sb.append(',');
            first = false;
            sb.append(js(e.getKey())).append(':').append(toJson(e.getValue()));
        }
        return sb.append('}').toString();
    }

    @SuppressWarnings("unchecked")
    static String toJson(Object o) {
        if (o == null) return "null";
        if (o instanceof String s) return js(s);
        if (o instanceof Number || o instanceof Boolean) return o.toString();
        if (o instanceof Map<?, ?> mm) return objToJson((Map<String, Object>) mm);
        if (o instanceof List<?> l) {
            StringBuilder sb = new StringBuilder("[");
            for (int i = 0; i < l.size(); i++) {
                if (i > 0) sb.append(',');
                sb.append(toJson(l.get(i)));
            }
            return sb.append(']').toString();
        }
        return js(String.valueOf(o));
    }

    static Map<String, Object> map(Object... kv) {
        Map<String, Object> r = new LinkedHashMap<>();
        for (int i = 0; i + 1 < kv.length; i += 2) r.put(String.valueOf(kv[i]), kv[i + 1]);
        return r;
    }

    static int intVal(Map<String, Object> o, String k) {
        Object v = o.get(k);
        return v instanceof Number n ? n.intValue() : 0;
    }

    static double round(double d) { return Math.round(d * 100.0) / 100.0; }

    // -------- file discovery ----------

    static List<Path> findJavaFiles(Path root) {
        List<Path> out = new ArrayList<>();
        try (var stream = Files.walk(root)) {
            stream.filter(p -> p.toString().endsWith(".java"))
                  .filter(p -> !skip(p))
                  .forEach(out::add);
        } catch (IOException e) {
            System.err.println("walk failed: " + e.getMessage());
        }
        out.sort((a, b) -> a.toString().compareTo(b.toString()));
        return out;
    }

    static boolean skip(Path p) {
        for (Path part : p) {
            String s = part.toString();
            if (s.startsWith(".") || isBuildDir(s)) return true;
        }
        return false;
    }

    static boolean isBuildDir(String s) {
        return s.equals("target") || s.equals("build") || s.equals("out")
                || s.equals("node_modules") || s.equals(".gradle") || s.equals("dist");
    }
}