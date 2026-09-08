All artifacts read. Writing the report now.
Report written to `summary/gson.md`. Key findings:

- **Quality:** 14,204 PMD hits but 96% style noise (`LocalVariableCouldBeFinal`+`MethodArgumentCouldBeFinal` ≈ 43%); real signal is JUnit4/Jupiter mismatch (1,585) and date-format duplication. Checkstyle: 0 errors / 959 warnings. CPD: 15 duplications, ~1% of lines — 5 of 15 blocks are `UtcDateTypeAdapter` forking core `ISO8601Utils`.
- **Security:** SpotBugs **found no bytecode** and dependency-check ran **NVD-offline with 0 deps/0 CVEs** — both sections are explicitly "no data", not clean bills. PMD security rules fired zero hits; only 4 security-adjacent findings, all in tests/benchmarks. Risk: Low–Medium (Medium driven by tool gaps + deserialization surface).
- **Complexity:** avg cc 1.66, max 47 (`JsonReader::doPeek`); `JsonReader` owns 8 of the top-15 complex methods. No package cycles.
- **Recommendations:** 10 items split into quick wins (tooling fixes, dedupe date parser, PMD tuning) vs structural (JsonReader state-machine rewrite, `GsonTypes::resolve` refactor, MethodHandles over `setAccessible`).
an.

| Metric | Value | Source |
|---|---|---|
| Files scanned (Java) | 264 | scc / kg |
| Files in LLM pack | 312 (incl. docs) | repomix |
| Code LOC (Java) | 38,424 (11,975 comment / 6,213 blank; total 56,612) | scc |
| LOC parsed (KG) | 53,780 | knowledge-graph.json |
| Types / Methods / Fields | 718 / 3,110 / 1,066 | knowledge-graph.json |
| Packages | 156 | knowledge-graph.json |
| LLM pack size | 534,873 tokens / 2,313,723 chars (~2.3 MB) | repomix |
| Bytes (Java only) | ~2.0 MB | scc |

## Code Quality

### PMD — 14,204 violations (244 of 264 files)

Split by priority: **P1 1,876 · P2 38 · P3 12,190 · P4 100**.
Split by ruleset: **Code Style 9,590 · Error Prone 2,426 · Best Practices 1,116 · Design 897 · Performance 175**.

Top rules (rule — count — example):

| Rule | Count | Example |
|---|---|---|
| `LocalVariableCouldBeFinal` | 4,349 | `RawCollectionsExample.java:43` |
| `MethodArgumentCouldBeFinal` | 1,730 | `RawCollectionsExample.java:30` |
| `WrongTestAnnotation` | 1,585 | `extras/.../InterceptorTest.java:47` — `@org.junit.Before` is JUnit 4, codebase is JUnit Jupiter |
| `ShortVariable` | 1,072 | `InterceptorFactory.java:60` — variable `in` |
| `UnitTestContainsTooManyAsserts` | 867 | `InterceptorTest.java:57` (>1 assert per test) |
| `CommentDefaultAccessModifier` | 799 | `RawCollectionsExample.java:26` |
| `OnlyOneReturn` | 354 | `InterceptorFactory.java:33` |
| `LongVariable` | 327 | `RuntimeTypeAdapterFactory.java:255` — `jsonElementAdapter` |
| `CloseResource` | 313 | `gson/src/main/java/com/google/gson/Gson.java:545` — `JsonTreeWriter` never closed |
| `LawOfDemeter` | 239 | `InterceptorTest.java:106` |
| `CyclomaticComplexity` | 68 | `UtcDateTypeAdapter.java:140` — `parse()` cc=22 |
| `AvoidCatchingGenericException` | 28 | `InterceptorFactory.java:49` — `catch (Exception)` |
| `AvoidAccessibilityAlteration` | 12 | `PostConstructAdapterFactory.java:39` — `setAccessible()` |

The `WrongTestAnnotation` cluster (1,585) shows a JUnit 4/Jupiter mismatch is endemic; `CloseResource`
is mostly noise (JSON read/write objects hold no OS handles), but real file/stream handling should
still be checked. Notable error-prone hits in main code: `NullAssignment` (23, e.g. `GsonBuilder.java:676`),
`AvoidDeeplyNestedIfStmts` (18, concentrated in `UtcDateTypeAdapter.java:180`), `AvoidCatchingGenericException`.

### Checkstyle — 0 errors, 959 warnings (215 files)

Google Java style profile. Top checks:

| Check | Count |
|---|---|
| `MissingJavadocMethod` | 192 |
| `GoogleNonConstantFieldName` | 161 |
| `SummaryJavadoc` | 158 |
| `MissingJavadocType` | 94 |
| `EmptyLineSeparator` | 62 |
| `JavadocParagraph` | 54 |
| `VariableDeclarationUsageDistance` | 38 |
| `AbbreviationAsWordInName` | 38 |
| `GoogleMethodName` (+ `Indentation`/`NeedBraces`, etc.) | 36 + |

Worst files: `gson/src/test/java/com/google/gson/common/TestTypes.java` (55), `metrics/.../ParseBenchmark.java` (38).
All hits are warnings; no errors.

### CPD duplication — 15 duplications / 401 duplicated lines

Scanned 264 files (~231,911 tokens). **≈1.0% of code lines** (401 of 38,424) are duplicated — low overall, but
concentrated. Worst clusters:

- **`UtcDateTypeAdapter` ↔ `ISO8601Utils`: 5 of 15 duplication blocks.** The extras date adapter
  re-implements the core `ISO8601Utils` ISO-8601 parser nearly verbatim (e.g. lines 75–114 vs 91–130,
  232–267 vs 309–344, 140–164 vs 147–173, plus 3 more).
- `RuntimeTypeAdapterFactory` ↔ its functional test mirrors the factory in test form (3 blocks, e.g. 275–308 vs 182–216).
- `BagOfPrimitivesDeserializationBenchmark` ↔ `CollectionsDeserializationBenchmark` (2 blocks).
- `JsonAdapterAnnotationOnClassesTest` (2 intra-file blocks) and `TestTypes`/`BagOfPrimitives` (1 block).

## Security

> **Tooling caveat up front:** the two binary/CVE scanners produced zero usable signal this run.
> Treat the low hit-counts below as *non-evidence*, not proof of security.

### SpotBugs / FindSecBugs — no bytecode, scan empty

The report contains no bug instances. It carries a single placeholder: *"No compiled classes or jars
found; SpotBugs requires bytecode. Run a build or vendor dependencies first."* **Bytecode was
unavailable**, so no bug patterns (incl. security categories) were evaluated. This is a genuine gap —
the reflective type-adapter and protobuf-deserialization paths are exactly where a bytecode-based
find-sec-bugs pass would be valuable.

### OWASP dependency-check — no data

`dependency-check-report.json`: engine `offline-stub`, `dependencies: []`, `warnings: ["NVD database
unavailable offline; pre-seed via: docker build --build-arg PRESEED_NVD=1"]` (the run also failed on an
unrecognized `--disableRetireJS` flag, per `depcheck.log`). **0 dependencies scanned, 0 CVEs.** Not a
clean bill of health — no CVE assessment is possible without the NVD seed.

### PMD security rules

No `security.xml` ruleset violations were raised (no injection / weak-crypto / etc. hits at all).
The only security-adjacent findings:

- `AvoidUsingHardCodedIP` ×2 — `DefaultInetAddressTypeAdapterTest.java:42` and `:53` (test fixture, `8.8.8.8`/IPv6). Not a defect.
- `UseProperClassLoader` ×1 — `OSGiManifestIT.java:168` (test).
- `NonSerializableClass` ×1 — `metrics/.../ParseBenchmark.java:69` (JMH benchmark inner class).

### Risk assessment: **Low–Medium (partly inconclusive)**

- **Low on the evidence present:** clean layering, no PMD injection/weak-crypto findings, no cycle
  shake-out, duplication confined to ~1% and mostly to the date-format utility.
- **Medium when the gaps count:** (a) Gson's core use case is reflective deserialization of
  (often untrusted) streams — the kind of surface FindSecBugs exists to check, and bytecode analysis
  did not run; (b) dependency-CVE status is unknown with the NVD offline; (c) 313 `CloseResource`
  and 12 `setAccessible()` hits remain un-triaged in main code. Once bytecode + NVD seed are available
  the Medium side of this call should be re-scored.

## Complexity

Cyclomatic complexity (kg-extractor): **average 1.66 per method**, max **47**; average method LOC 10.18.

| Method | File | cc | LOC |
|---|---|---|---|
| `JsonReader::doPeek` | `gson/.../stream/JsonReader.java` | 47 | 166 |
| `JsonReader::peekNumber` | `gson/.../stream/JsonReader.java` | 40 | 111 |
| `ISO8601Utils::parse` | `gson/.../internal/bind/util/ISO8601Utils.java` | 31 | 163 |
| `JsonReader::readEscapeCharacter` | `gson/.../stream/JsonReader.java` | 26 | 65 |
| `JsonReader::nextUnquotedValue` | `gson/.../stream/JsonReader.java` | 25 | 57 |
| `GsonTypes::resolve` | `gson/.../internal/GsonTypes.java` | 24 | 101 |
| `LinkedTreeMap::rebalance` | `gson/.../internal/LinkedTreeMap.java` | 22 | 59 |
| `ReflectiveTypeAdapterFactory::getBoundFields` | `gson/.../internal/bind/ReflectiveTypeAdapterFactory.java` | 21 | 109 |
| `JsonReader::peek` / `skipValue` / `skipUnquotedValue` | `gson/.../stream/JsonReader.java` | 20 each | 38–77 |
| `LegacyProtoTypeAdapterFactory.Adapter::readSingleFieldValue` | `proto/.../LegacyProtoTypeAdapterFactory.java` | 19 | 33 |

`JsonReader` dominates: 8 of the top-15 complexity methods live in that one file (271 PMD hits, the 2nd
largest non-test file by tokens). The date-parsing block is the clearest complexity*duplication
correlation: `ISO8601Utils::parse` (cc 31) and `UtcDateTypeAdapter::parse` (cc 18) are the two most
complex calendar methods **and** share 5 CPD duplication blocks — the same parser has effectively been
forked. Unusual LOC: `test-shrinker/.../ShrinkingIT::test` (141 LOC, cc 2) and
`TypeTokenTest::testParameterizedFactory_Invalid` (117 LOC) are large but simple; `GsonTypes::resolve`
(101 LOC, cc 24) is the core recursive type resolver.

## Knowledge graph

264 files, 156 packages, 718 types, 3,110 methods, 1,066 fields, 53,780 LOC. 3,000 edges:
`depends_on` 2,003 · `implements` 82 · `extends` 73 · `invokes` 124. **No dependency cycles** (confirmed empty).

**Hub types** (deps = types it uses, dependents = types that use it):

| Type | deps | dependents |
|---|---|---|
| `com.google.gson.TypeAdapter` | 3 | **152** |
| `com.google.gson.Gson` | 3 | **147** |
| `com.google.gson.JsonElement` | 1 | 111 |
| `com.google.gson.stream.JsonReader` | 5 | 94 |
| `com.google.gson.reflect.TypeToken` | 8 | 83 |
| `com.google.gson.stream.JsonWriter` | 2 | 80 |
| `com.google.gson.JsonSerializer` | 2 | 79 |
| `com.google.gson.TypeAdapterFactory` | 2 | 76 |
| `com.google.gson.GsonBuilder` | 5 | 67 |

**Strongest package dependency edges** (from → to, weight):

```
com.google.gson.functional                 → com.google.gson                           (1819)
com.google.gson.internal.bind              → com.google.gson                           (667)
com.google.gson.functional                 → com.google.gson.common.TestTypes          (488)
com.google.gson.functional                 → com.google.gson.reflect                   (299)
com.google.gson.functional                 → *[JsonAdapterOnClasses/FieldsTest]        (163 / 150)
com.google.gson                            → com.google.gson.stream                    (113)
com.google.gson.functional                 → com.google.gson.stream                    (94)
com.google.gson.internal                   → com.google.gson.internal.LinkedTreeMap    (79)
com.google.gson.protobuf[.functional]      → com.google.gson                           (63 / 78)
```

The extractor normalizes "package" targets to a class where the package is single-file (e.g.
`com.google.gson.common.TestTypes`); treat those tail names as packages-that-are-single-types.

Largest packages by contained types: `functional` 317, `com.google.gson` 95, `internal` 64,
`internal.bind` 45, `com.example` 33, `metrics` 29. 62 entries are reported as isolated —
predominantly leaf test/benchmark/sample packages, but the list is **noisy** (it includes widely-used
types such as `com.google.gson.TypeAdapter` and `com.google.gson.annotations`), so treat individual
entries cautiously.

**Architectural takeaways**

1. **Adapter-centric plugin design.** `TypeAdapter` (152 dependents), `Gson` (147) and
   `TypeAdapterFactory` (76) are the contracts everything hangs off; the graph shows a classic
   registry + provider pattern with the JSON model (`JsonElement`/`JsonPrimitive`, 111/71 dependents)
   as the shared currency.
2. **Test volume is the graph's center of gravity.** The `functional` package holds 317 of 718 types
   and emits the heaviest edges (functional→gson alone = 1,819 of ~2k `depends_on`). Shipping 1,585
   JUnit4/Jupiter annotation mismatches shows the test surface outgrew its tooling conventions.
3. **Clean module layering, no cycles.** `gson` → `stream`/`reflect`/`internal` dependencies are
   one-directional; `proto`/`extras` sit downstream of core. None of the 156 packages cycle.
4. **Date handling is the one structural wart.** `UtcDateTypeAdapter` (extras) duplicates
   `ISO8601Utils` (core) at the package level — one forked date parser spanning two modules, visible
   in both CPD (5 blocks) and complexity (the two top date methods, cc 31/18).
5. **`JsonReader` is a hot spot worth isolating.** One file owns 8 of the top-15 complexity methods
   and is the single biggest non-test file by tokens — the lexer is the natural candidate for a
   state-machine rewrite.

## Recommendations

**Quick wins (low effort / high signal)**

1. **Fix the JUnit 4/Jupiter mismatch** — 1,585 `WrongTestAnnotation` hits (e.g. `InterceptorTest.java:47`).
   Migrate remaining `@Before/@Test/@Rule` to Jupiter or drop the JUnit-4 tests; this is the largest
   single correctable rule.
2. **Tune PMD to kill the style noise** — `LocalVariableCouldBeFinal` (4,349) + `MethodArgumentCouldBeFinal`
   (1,730) ≈ 43% of all hits. Either delete them from the ruleset or set `allowToBeFinal`/suppression
   so 14k violations stops burying the meaningful error-prone hits (2426).
3. **De-duplicate the ISO-8601 parser** — collapse `UtcDateTypeAdapter` (extras) onto core
   `ISO8601Utils` (5 CPD blocks, 257 duplicated lines). Extract one shared `java.time` formatter;
   doing so also retires `ReplaceJavaUtilDate` (105) and `ReplaceJavaUtilCalendar` (24) in one move.
4. **Triage `CloseResource` in `gson/`** — 313 hits, mostly JSON objects, but confirm real streams
   (e.g. `Gson.java:545`) and add PMD suppressions for the genuine false positives.
5. **Close the tooling gaps** — build bytecode in the scan image so SpotBugs/FindSecBugs actually
   runs, and pre-seed the NVD database (`--build-arg PRESEED_NVD=1`). Until then both security
   sections stay "no data".
6. **Javadoc for public API** — `MissingJavadocMethod` (192) + `MissingJavadocType` (94) + 158
   `SummaryJavadoc`; gson is a library whose docs are its contract.

**Structural work (more effort)**

7. **Rewrite `JsonReader` tokenizer as a state machine** — `doPeek` (cc 47 / 166 LOC), `peekNumber`
   (cc 40), and 6 more top-complexity methods live here; this is where parsing bugs and
   resource-exhaustion paths concentrate. Split number/escape/value handling into focused states.
8. **Refactor `GsonTypes::resolve` and `ReflectiveTypeAdapterFactory::getBoundFields`/`createBoundField`
   (cc 24/21/17, 100+ LOC each)** — the recursive type resolution is the riskiest generic logic;
   add a decision table + exhaustive tests rather than more branches.
9. **Replace `setAccessible()` (12 hits) with `MethodHandles`/`Lookup`** — `PostConstructAdapterFactory.java:39`
   and the reflection helpers; the repo already ships `Java17ReflectionHelper` and JPMS tests, so this
   aligns with module-path compat.
10. **Consolidate benchmark fixtures** — `BagOfPrimitivesDeserializationBenchmark` ↔
    `CollectionsDeserializationBenchmark` share 2 full CPD blocks; factor a shared data-driver.