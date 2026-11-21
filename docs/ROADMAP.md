---
title: Roadmap
version: 0.10.0
status: release candidate; pending private vocabulary gate and coordinator release approval
tags: [datamesh, roadmap]
---

# Roadmap

## 0.10.0 document API candidate: implemented

The HTTP API beside the durable worker is implemented: shared CLI/API document
identity, local bearer auth, docs-first contracts, application prerequisites,
FastAPI shell/readiness, bounded intake/status and durable opaque receipts,
privacy-safe document/task/WBS/subject reads, required combined synthetic API
acceptance and nonroot Compose API/secret provisioning. Real text HTTP upload,
worker polling and identical retry passed on the preceding merged baseline,
before and after durable-service restart. Candidate-specific run evidence is
recorded in [the candidate record](releases/0.10.0.md), never inferred from that
baseline. The strict required HTTP gate fails on missing or skipped tests.

The repository has advanced since the 0.9.9 bundle. Version preparation does
not itself publish a release or close acceptance. Remaining candidate gates:
exact-head hosted checks, recorded server/driver/image matrix, fresh public
export/private-path checks, private vocabulary scan and coordinator release
approval. Hosted dependency-complete Python 3.11/3.12 required tests are the
approved execution criterion; local checks remain separately reported.

Scope exclusions remain deletion/restoration, OIDC, public CORS, ClickUp import,
S3, simulation and HFGT HTTP endpoints. Source occurrences are never approved
work. Existing compatibility aliases remain; their removal is not authorized
by changing this package version. Fault injection remains production follow-up.

Forward-version evidence/evaluation/ladder/drawing/challenge contracts and design
pages retain their own stated limits, not implied completed workflows. The
items below are deferred, with no new date, owner assignment or 0.11.0 promise.

## Deferred HFGT backlog (not a 0.10.0 commitment)

| # | Item | Owner of the decision |
|---|---|---|
| H1 | Implement `CapabilityGnnEncoderPort` (relational GCN over `edge_type`, messages both ways; torch only in `app.infrastructure`). Training targets: reachability, dead ends, which single constraint breaks a path, downstream impact. | developer, accepted by Brain |
| H2 | Content embedding columns: attach splice content vectors to capability nodes through `TensorTransformPort`; never as edges. | developer |
| H3 | Move `TensorContract`, `TensorSpec`, `TensorRef` to `app.application.common`, so hfgt imports nothing from the simulator. | developer |
| H4 | Who-vs-where deviation (buffers are places, resources execute). | mathematical reviewer |
| H5 | Mapping of `exchange` (today a gap), `control` as transform, and `reads` / undecided `checks` as non-consuming identities. | process SME |
| H6 | Default `operand_key = kind_state`. | process SME |
| H7 | Constraint vocabulary (PTO, region, certification, authority to displace) and who may author K_S rows. | James |
| H8 | Whether existence should require `evidence_ref`, or keep asserted capabilities with `evidenced = 0` (current). | James |
| H9 | Run HFGT on real records: needs the B2 process mapping and B5 event history; synthetic fixtures prove the translation only. | James, process SME |
| H10 | Deprecations: remove the `_Frozen` re-export and decide when the v1 `lambda_min_abs` alias goes. | James |
