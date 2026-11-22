---
title: Private reference-document ingestion
version: currentcraft-ref-document/v1
status: implementation candidate; source-specific acceptance pending
---

# Private reference-document ingestion

This path turns an explicitly selected private source document into an exact-text JSON snapshot, then hydrates source-literal nodes through the existing object/graph unit of work:

```text
pinned source bytes + private extraction profile
  -> read-only PDF or UTF-8 extraction
  -> document / candidate section / passage tree
  -> hash-pinned JSON under references/private/
  -> independent JSON and payload verification
  -> atomic source-object and typed-edge persistence
```

## Fractal structure, not interpretation

The root represents the source document. A private, reviewed profile may identify headings with a trusted regular expression; numbered headings form nested sections, and bounded passages retain exact offsets into the extracted page text. Unrecognized lines remain passages. There is no standards-specific vocabulary, crosswalk, rule execution, semantic mapping or automatic clause interpretation in public code. A section boundary is a parser candidate, not evidence that the source is complete, authoritative, current, applicable or approved.

The private JSON preserves extracted page text, source-relative name, source and profile digests, extractor version, node order, parent handles and Unicode-codepoint spans. The source/revision handle comes from an explicit private REF manifest; IDs are never inferred from filenames or content hashes. Graph objects preserve those spans and source hashes; each child has a typed `part_of` edge. All six-type/canonical business records remain unchanged. The graph entries are labeled `source_literal_candidate` and create no decision authority.

## Privacy and integrity boundary

- Configure the root as the local `references/private/` directory. The loader rejects any other root name, absolute or parent-traversing paths, symlinks, unsupported formats, oversize inputs and unpinned source bytes.
- Output is atomically written as a mode-0600 JSON file inside that same root. The private bundle is never placed in `references/public/`; source text and derived JSON are not fixtures, package data or public artifacts.
- Re-loading JSON requires its expected byte digest as a separate trusted input, rejects duplicate keys, verifies the closed model and canonical payload digest, then issues an independent selection receipt. A receipt embedded in JSON is not proof of verification.
- Hydration writes every object plus an idempotency record in one existing unit-of-work transaction. No filesystem path, source bytes, private labels or mappings are published to a broker or external service.
- The code does not enforce source rights, classification, retention or operating-system access control. The caller must authorize source use and protect the private volume. Hash checks prove byte identity, not trustworthiness.

## Supported extraction and limits

PDF text extraction uses the optional `pypdf` extra in strict, read-only mode; encrypted PDFs are rejected. UTF-8 text and Markdown are supported by the standard library. Scanned-PDF OCR, external links, macros, network retrieval and automatic source discovery are not supported. The exact extracted text, not binary layout, is the unit referenced by offsets.

## Six acceptance corrections

1. New REF parent relations pin `target_version`, stored as `dst_version` beside
   `src_version` by migration 006. Parents are written before children; the actual
   returned parent version is pinned. Legacy unpinned edges stay null, not guessed.
   Current traversal is not a historical snapshot traversal.
2. Current REF descendant listings, related reads, edges and traversals require their
   payload digest to match their manifest handle's current root payload, identically
   in memory and SQL. Direct lookup and history remain available. Nothing is deleted.
   Earlier command replay cannot restore old heads; failed transactions roll back.
3. The loader issues an identity-bound, weakly held process-local capability.
   Hydration checks it as well as receipt/bundle consistency. Hand-built, copied and
   JSON-round-tripped receipts cannot mint capabilities. Reload pinned files after a
   process restart. This protects against caller data, not hostile Python code in the
   same process; it is neither a digital signature nor a permission grant.
4. Profiles declare `coverage` as full, partial or unknown. Partial requires a private
   reason. Both coverage and reason propagate into JSON and every graph node. Preview
   status must be declared at intake; no filename or parser success establishes full
   coverage. Unspecified coverage stays unknown. Metadata changes bundle/profile
   digests, not source handles or node identities; the determinism golden changes.
5. `.owl` and `.rdf` accept exact UTF-8 RDF/XML source capture with a validated RDF
   root. DTD/entity declarations are rejected by structural parser callbacks; nothing dereferences
   imports or external resources. Markup is retained as bounded source-literal
   passages, not interpreted as semantic triples, class hierarchies or ownership.
   Reasoning, Turtle and OWL Functional Syntax are not implemented.
6. Full private locators up to 1,024 characters remain in `source_name`. Locators over
   500 characters use the neutral root title `Reference document` without truncating
   the locator.

All six former expected failures are required passing regressions. Store-specific
checks run against memory, DuckDB and the gated PostgreSQL acceptance class.
Synthetic correctness does not establish real-standard completeness or authority.

## Streaming RDF/XML validation (implementation candidate)

Policy `rdfxml-stream/1` uses namespace-aware Expat event callbacks, not an
ElementTree or DOM. It feeds at most 16,384 characters per call, discards element/text
events immediately, and keeps only counters. Root depth is one; the RDF root counts
toward the total. Reject depth above 128, more than 100,000 elements, more than 64
attributes on one element, or an attribute value longer than 16,384 characters.
These are fixed engine policy limits, not source-selected settings.

Decoded source character and single-page limits are checked before parser creation.
DTDs, entity declarations and external-entity callbacks fail closed; parameter-entity
parsing is disabled explicitly. Comments/CDATA mentioning declaration-like text are
ordinary source literals, not falsely rejected declarations. Malformed input raises
fixed, source-free errors without retaining parser exception chains.

This validates XML shape and resource counters, not RDF/OWL semantics. Imports,
XInclude, schema locations and stylesheet instructions remain inert literals.
Exact source text, offsets, source hashes and node identities are preserved.
OWL extractor provenance changes to `rdfxml-stream/1`; OWL payload digests therefore
change deliberately. Non-OWL bundles and profile digests remain unchanged.

No CPU deadline, OS memory ceiling, subprocess isolation, public upload route or
production hostile-input certification is added by this slice. Expat may buffer an
individual token within the prechecked source-size ceiling. Runtime Expat patch
maintenance and deployment-level resource isolation remain required separately.

## Fail-closed subprocess boundary (implementation candidate; live Linux acceptance pending)

`ingest_and_hydrate` now requires an explicit `LinuxIsolation` configuration and
accepts RDF/XML only. Missing Linux/cgroup v2 delegation, runtime, Bubblewrap,
seccomp library or usable namespace setup stops extraction; there is no automatic
in-process fallback. `build_bundle` remains a trusted low-level primitive for
synthetic tests and offline development, not a hostile-input entry point.

Fixed initial budget: source 2 MiB, decoded page 2,000,000 characters, result
16 MiB, CPU 5 seconds soft/6 hard, wall time 10 seconds, cgroup memory 256 MiB,
swap zero, one CPU rate and eight tasks including sandbox helpers. One active
extraction per coordinator process; concurrent callers receive `busy` (no queue
is added). Every job gets a fresh child cgroup and freshly exec'd interpreter.
PDF/text hostile-file isolation is unsupported and rejected, not silently routed
to the trusted primitive.

An administrator supplies a dedicated, trusted, secret-free runtime root containing
`/usr/bin/python3`, Python dependencies, `/opt/currentcraft/src`, libseccomp and an
empty `/input.json` mountpoint.
It must not be `/`, `/usr`, a REF directory or a broad host root. Runtime artifacts
and Bubblewrap are trusted deployment inputs, not made trustworthy by a checksum
of attacker-selected bytes. The sandbox binds only that runtime read-only and one
sealed request as `/input.json`; it receives no REF mount or service credentials.
Explicit user, PID, IPC, network, UTS and cgroup namespaces are mandatory, as are
disabled nested user namespaces, dropped capabilities and parent-death cleanup.
The worker applies no-new-privileges and seccomp denial of process creation,
network sockets, exec and namespace/mount manipulation before reading source data.

A trusted bootstrap joins the preconfigured job cgroup before reporting readiness.
It blocks until the parent verifies membership; only then may it exec Bubblewrap.
CPU and descriptor/core/file limits are applied before exec. The parent polls the
aggregate cgroup CPU usage, monotonic deadline and bounded output, never captures
raw stderr, kills the entire cgroup on failure/cancellation and reaps the launcher.
`memory_limit` requires an increment in the cgroup OOM-kill counter, not merely
SIGKILL. Cleanup failure is itself a failed job; no result may be published.

The parent reads one regular, no-follow-selected source with a byte ceiling, hashes
it, seals the request and treats the returned bundle as untrusted. Before atomic
publication it checks closed schema, exact source/profile/locator binding, literal
page text, deterministic identities, payload digest and bounded JSON. Existing
parent-side loader issuance and hydration remain unchanged. No child can issue
loader capabilities or commit graph records.

Unit tests cover denied prerequisites and supervision decisions. Live tests are
explicitly gated on an operator-provisioned delegated cgroup and runtime; enabling
the live gate turns absent prerequisites into failures, not skips. This environment
cannot exercise successful cgroup/Bubblewrap/seccomp enforcement. No production
security acceptance, live OOM/CPU/network/filesystem containment or deployment is
claimed until that gate runs on a configured Linux runner.

Operator acceptance command (dedicated idle delegation and trusted runtime required):

```bash
DATAMESH_REQUIRE_REF_ISOLATION=1 \
DATAMESH_REF_CGROUP_ROOT=/configured/delegation \
DATAMESH_REF_RUNTIME_ROOT=/configured/secret-free-runtime \
python -m unittest tests.test_reference_isolation.LiveLinuxIsolation -v
```

The runtime must provide current `ref_worker.py` and matching application sources,
their Pydantic/numpy dependencies (single-threaded startup), a usable
`libseccomp.so.2`, and the fixed `/usr/bin/python3` entry point. It is a trusted,
operator-provisioned artifact, not a directory assembled from input source files.
No privileged setup, cgroup delegation mutation, runtime image creation or workflow
configuration is performed automatically by this patch. The dedicated live gate
checks source roundtrip, CPU/wall/memory/output budgets, fork/network/file/write
denial, cleanup and a successful job after failures. A green ordinary CI run with
this gate disabled must never be reported as live isolation acceptance.

## Composition

`app.infrastructure.ingest.reference_documents.ingest_and_hydrate` accepts an absolute private root, explicit relative source/output paths, a manifest-supplied opaque source/revision handle, a separately configured expected source SHA-256, a reviewed `ReferenceIngestProfile`, the application's existing `UnitOfWorkFactory`, and an aware recording time. It returns the private bundle and a receipt containing opaque graph handles only. A production caller must pass its already configured durable UoW; the in-memory UoW is for tests only.

Synthetic acceptance tests exercise extraction, nested boundaries, JSON verification, path containment, repeat-safe graph writes and the in-memory UoW. They do not ingest or publish real standards. Real-source acceptance still requires approved source files and a private runtime composition.
