---
title: Roadmap
version: 0.9.9
status: living page; updated each release
tags: [datamesh, roadmap]
---

# Roadmap

What the next release carries. Everything here is **not** implemented in 0.9.9.

## 0.10.0: FastAPI document API, rebased on 0.9.9

The 0.10.0 plan (HTTP API beside the ingestion worker, clean public repository) was written against the 0.9.6 bundle.
It now starts from the **0.9.9** coordinator bundle. Build order is unchanged:

1. Publish the public repo baseline (parallel; gates going live)
2. Decide API identity and access rules
3. Write the HTTP API design page (`docs/architecture/HTTP_API.md`, `version: 0.10.0`)
4. Add application prerequisites
5. Scaffold the FastAPI layer (`app.interfaces.http`)
6. Build intake endpoints
7. Build document and task read endpoints
8. Test the API end to end
9. Add the API to the Compose stack
10. Release 0.10.0 and run live acceptance

What changes because of 0.9.7 to 0.9.9:

| Area | Change the 0.10.0 work must respect |
|---|---|
| Baseline | Export from the 0.9.9 bundle; move `references/private/` out first (it now also holds `splice-0.9.7/` and the PEW 3.1 objects). |
| Allowlist | `src/app/application/common/`, `src/app/application/hfgt/`, `src/app/infrastructure/hfgt/` and `tests/fixtures/**/*.json` are public. `src/app/interfaces/` is added in step 5. |
| Shared base | Import `_Frozen` from `app.application.common.contracts`; the `simulation.contracts` re-export is for one release only. |
| Simulation contract | `datamesh-sim/v2`: eigenvalue key `mu_min_abs` (v1 `lambda_min_abs` read as a deprecated alias); nodes are sorted by id on validation, so digests and tensor row order are input-order independent. Any API DTO built from simulation results uses the v2 names. |
| Process contract | `datamesh-process/v1` gained optional `at_buffer`, `origin_buffer`, `destination_buffer`. Ingestion projections are byte-identical; DTOs may expose the fields as optional. |
| New contract | `datamesh-hfgt/v1` exists. Exposing it over HTTP is **out of 0.10.0 scope** unless decided in step 2. |
| Live gates | The postgres-18, jetstream and compose-smoke jobs are still waiting; nothing in 0.9.7 to 0.9.9 cleared them. |
| Scope | Still out: deletion review and delete endpoints, ClickUp import, S3 blob adapter, OIDC, public CORS. |

## 0.10.0: HFGT follow-ups deferred from 0.9.9

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
