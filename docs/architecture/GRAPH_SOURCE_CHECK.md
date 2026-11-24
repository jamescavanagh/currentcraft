---
title: Read-only REF graph and source integrity checker
version: 0.1.0
status: implementation candidate; private graph acceptance not run
---

# Read-only REF graph and source integrity checker

## Purpose and boundary

Compare one explicitly selected REF graph revision export with preserved source,
profile and bundle bytes. Never change a graph, rehydrate records, restore heads,
issue loader capabilities or grant authority. Integrity is not completeness,
source authenticity, source rights, semantic interpretation or recovery proof.
Only a complete declared selection can pass; unpinned legacy parent edges fail.

## Independent inputs

An operator supplies a private root, a relative manifest path and its expected
SHA-256 through an independently trusted channel. A digest stored alongside its
own untrusted file is not independent trust. The checker establishes consistency
with the operator's pins, not authenticity of those pins.

The manifest is closed JSON with `schema_version=currentcraft-graph-check/v1`,
`graph` (`path`, `sha256`, `snapshot_id`) and nonempty `documents`. Each document
contains `document_id` and `source`, `profile`, `bundle` file pins (each `path`,
`sha256`). The exact expanded profile and bundle must use the existing
`currentcraft-ref-document/v1` JSON shapes, including optional/default fields.
Source SHA-256, profile canonical digest and bundle canonical payload digest are
separate checks; the latter excludes only `payload_sha256`. Canonical JSON sorts
keys recursively, uses UTF-8 without ASCII escaping, compact separators and no
nonfinite numbers. The current contract has integer/null/string data only.

```bash
python scripts/check_graph_sources.py --root /configured/private \
  --manifest graph-check.json --manifest-sha256 "$EXPECTED_MANIFEST_SHA256"
```

Paths must stay under the explicit private root. Symlinks, traversal, nonregular
files, duplicate JSON keys, nonfinite constants and unexpected envelope fields
fail closed. Each file is bounded at 64 MiB; source JSON/text remains private.
No file writes or network/database connections are performed.

## Normalized export handoff (new, not an existing exporter)

`currentcraft-ref-graph-export/v1` is an offline comparison envelope, not a new
persistence/API contract. No existing database exporter is claimed. A private,
read-only operator export must be taken from a consistent snapshot and preserve
actual stored object and edge versions. It must not reconstruct its claimed graph
by copying the expected bundle. Export adapters and snapshot isolation acceptance
remain future work.

The closed envelope contains `schema_version`, `snapshot_id`, `documents`, `nodes`
and `edges`. `documents` is the exact list of manifest document handles. Each node
contains `object_id`, `version_no`, `kind`, `title`, `text`, `fields`, `provenance`.
`fields` is the full current REF hydration field mapping. `provenance` projects
only `source_id`, `content_sha256`, `adapter`, `adapter_version`. Each edge contains
`src_id`, `rel_type`, `dst_id`, `src_version`, `dst_version`, `evidence`.

The checker requires the exact node set for the selected bundles, literal titles
and text spans, kinds, all REF fields (including coverage and extractor version),
source provenance and exact `part_of` edge set. Positive source/target versions
must refer to the exported nodes. Duplicate, missing, foreign or extra nodes and
edges fail. It does not claim to verify unrelated graph families or compare all
historical revisions. Source-byte hashes are checked for all supported formats;
UTF-8/Markdown/RDF literal page text is additionally compared directly with source
text. PDF text re-extraction is not performed; its bundle is independently pinned.

## Output and acceptance

Exit 0: the declared selection matches the supplied independent pins. Exit 1:
a fixed failure code. Reports contain only status, a controlled code and counts;
never source paths, handles, titles, text, hashes or exception payloads. Caller
shell history/process metadata still needs operator protection. This is an
operator tool for bounded trusted/offline inputs, not a hostile-input sandbox.

Synthetic tests cover pin tampering, literal/field drift, parent/version drift,
missing/extra/duplicate records, unsupported contracts, unsafe paths, duplicate
keys, bounded files and source-free failures. No real graph, durable-store
acceptance, private-term clearance or release authorization is implied. Public
fixtures are synthetic and generated in temporary directories, never private data.
