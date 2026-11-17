---
title: HFGT capability graph for the GNN
version: 0.9.9
status: implemented 0.9.9 (translation, kernel, sample, tests); encoder and open decisions deferred to 0.10.0
tags: [datamesh, hfgt, gnn, process-first]
schema: datamesh-hfgt/v1 (new); datamesh-process/v1 additive; datamesh-sim/v2 unchanged
source: Farid, Thompson & Schoonenberg, "A tensor-based formulation of hetero-functional graph theory", Sci. Rep. 12:18805 (2022)
owners: developer LLM implements · Brain manages acceptance · James coordinates · mathematical reviewer and process SME unnamed
---

# HFGT capability graph for the GNN

> Give the GNN a graph whose nodes are **capabilities** ("resource does process") and whose directed edges are
> **feasible sequences** ("this capability can feed that one"), built from process records by the HFGT incidence
> product `A_rho = M+^T M-`. Constraints remove availability; they never become similarity.
> The existing vortex graph (`GraphSampleRequest`, knn / coupling) stays as the embedding lens.

## Status in 0.9.9

| Part | Status |
|---|---|
| Contracts, translation, port, numpy kernel, wiring (sections 2 to 7) | implemented |
| Golden fixtures, identities, layering, release allowlist (section 9) | implemented, CI-gated |
| `CapabilityGnnEncoderPort` | declared only; implementation in 0.10.0 |
| Content embedding columns through `TensorTransformPort` | deferred to 0.10.0 |
| Exchange mapping, control/reads semantics, who-vs-where sign-off (section 10) | open decisions; provisional extensions listed in `TranslationReport.deviations` |

Deferred work is tracked in [ROADMAP](../ROADMAP.md).

## 0. Correction to the earlier proposal

The first proposal said "add an `hfgt_sequence` edge rule to `GraphSampleRequest`". That would be wrong:
`GraphSampleRequest` nodes are vortex `InteractionNode`s (x, y, strength), and HFGT nodes are capabilities.
Putting HFGT edges on vortex nodes overloads one node set with two meanings, which is exactly the lucidity
failure HFGT exists to prevent. So this is a **separate builder and a separate sample contract** with the same
PyTorch Geometric conventions. `datamesh-sim/v2` does not change.

## 1. Goals and non-goals

Goals
- Edges mean "can follow" (directed, typed by the operand and buffer that link them), not "is near in text space".
- Constraints (K_S) change the graph: a blocked capability neither feeds nor follows.
- Separate **possible** (J_S) from **conditionally available** (A_S = J_S minus K_S). Neither is Ready; Ready needs a
  complete path plus evidence plus authority, and only a person moves work along the release ladder.
- Every record that does not translate is **reported, never guessed**. Unknown is not 0.
- Reproduce the paper's identities as tests (section 9).

Non-goals
- No training, no model weights, no torch outside `app.infrastructure`.
- No dynamics: HFGT is structure. Timing and flow stay with the simulator lens.
- No claim about any real project's process. Fixtures are synthetic until B2 mapping and B5 event history exist.

## 2. Placement and layering

| Layer | Module | Holds |
|---|---|---|
| application | `app.application.hfgt.contracts` | Pydantic only: `Buffer`, `CapabilityConstraint`, `HfgtGraphRequest`, `CapabilityRecord`, `TranslationGap`, `TranslationReport`, `CapabilityGraphSample` |
| application | `app.application.hfgt.translation` | `translate(request) -> HfgtTranslation` (records + report), plus `check_constraints`, `layers`, `buffer_graph`, `operand_network`: pure Python, no arrays |
| application | `app.application.hfgt.ports` | `HfgtGraphPort.build(request) -> CapabilityGraphSample` |
| infrastructure | `app.infrastructure.hfgt.kernels` | numpy only: incidence matrices, Boolean products, K_S masking, five-rule oracle, reachability |
| infrastructure | `app.infrastructure.hfgt.adapters` | `NumpyHfgtGraphAdapter` implements `HfgtGraphPort`; features and tensors |
| infrastructure | `app.infrastructure.hfgt.wiring` | `build_hfgt(store)` |

Done in 0.9.9: `_Frozen` lives in `app.application.common.contracts` (re-exported from `simulation.contracts` for one
release). The hfgt application slice may import only the tensor descriptors from the simulator (`TensorContract`,
`TensorSpec`, `TensorRef`); moving those to `common` is a 0.10.0 item. Layering tests:
`test_hfgt_application_uses_only_tensor_descriptors_from_the_simulator`, `test_hfgt_infrastructure_uses_numpy_only`,
`test_common_imports_no_slice`, and the splice test now forbids the simulator too.

## 3. Process contract additions (datamesh-process/v1, additive)

All optional, so every existing payload still validates.

| Field | On | Meaning |
|---|---|---|
| `at_buffer: Optional[Ident]` | `ProcessExecution` | Where a transform, control or hold happens |
| `origin_buffer: Optional[Ident]` | `ObjectIncidence` | Where a `transfers` incidence starts |
| `destination_buffer: Optional[Ident]` | `ObjectIncidence` | Where it ends |

Validators: `origin_buffer` / `destination_buffer` only on `transfers`; both or neither. Missing buffers are **not**
validation errors (ingestion must not block); they become `TranslationGap`s.

Also fix `ParticipationEdge.resource_id` description: "Participating resource" (not "resource or operand").

## 4. New contracts (datamesh-hfgt/v1)

```text
Buffer            buffer_id, kind: store | work | custody, label?, evidence_ref?
CapabilityConstraint
                  capability: {process: str, resource_id}, reason (1-200), evidence_ref?,
                  valid_from?, valid_to?          # K_S row; time-varying availability
HfgtGraphRequest  schema_version, frame_id, executions: tuple[ProcessExecution], buffers: tuple[Buffer],
                  constraints: tuple[CapabilityConstraint] = (), as_of: datetime?,
                  operand_key: kind_state | kind = kind_state,
                  existence_basis: observed = observed,
                  constraint_mode: drop | mask = mask,
                  layer_scheme: input_operand_set | output_operand_set | none = input_operand_set,
                  terminal_operands: tuple[str] = (),
                  content: Optional[TensorRef]     # optional node text embeddings, never edges
                  candidates: tuple[CandidateEdge] = ()   # splice/knn proposals, kept apart
CapabilityRecord  process_id, resource_id, function_class, pulls: tuple[(operand, buffer)],
                  injects: tuple[(operand, buffer)], evidence_count, evidenced, nonconsuming, stages
TranslationGap    execution_id, object_id?, reason
TranslationReport gaps, n_executions, n_translated, coverage = n_translated / n_executions
CapabilityGraphSample (TensorContract)  # see section 7
```

Request-level validators: resource ids and object ids disjoint across the **whole** request (people are never
operands); every constraint names an existing capability (else error: a constraint on nothing is a typo); every
buffer referenced by an execution is declared in `buffers` (else gap, not error).

## 5. Translation rules (the application-layer translation)

### 5.1 Index sets

| HFGT | Built from | Notes |
|---|---|---|
| R (resources) | `CapabilityBinding.resource_id` | People, teams, tools. Never buffers, never objects. |
| B_S (buffers) | `Buffer` | Places and containers. |
| L (operands) | `object_kind` + state (`kind_state`, default) or `object_kind` (`kind`) | Types, not instances. |
| P_mu | transform executions, keyed `transform:{code}@{at_buffer}` | |
| P_gamma x P_eta (refined transport) | hold and transport incidences, keyed `refined:hold({operand}):{origin}->{destination}` | Holding in place is origin = destination. |
| E_S (capabilities) | `(process_id, resource_id)` for each executor of a computed execution | Projected form: only existing capabilities are nodes. |

`operand_key = kind_state` is the default because with `kind` alone, `revises` and `checks` pull and inject the same
operand, which creates cycles (install could "follow" commission). State is what carries order.

### 5.2 Effects to incidence (M_LP)

| Effect | Pull (M-) | Inject (M+) | Note |
|---|---|---|---|
| `produces` | none | `kind:state_after` @ buffer | birth |
| `consumes` | `kind:state_before` @ buffer | none | death |
| `revises` | `kind:state_before` | `kind:state_after` | same buffer |
| `holds` | `kind:state_before` @ y | `kind:state_after` @ y | refined transport y->y |
| `transfers` | `kind:state_before` @ origin | `kind:state_after` @ destination | refined transport |
| `reads` | `kind:state_before` | same operand (identity) | **DataMesh extension**: non-consuming |
| `checks` | `kind:state_before` | `kind:state_after` if a decision changed it, else identity | **extension** |

### 5.3 Class mapping

| Our class | HFGT | Status |
|---|---|---|
| transform | P_mu | direct |
| hold | P_gamma | direct |
| transport | P_eta (refined with the held operand) | direct |
| control | transform at `at_buffer` with identity or state-change operand | **extension, SME decision** |
| exchange | not mapped: emitted as a gap | **open, SME decision** (candidate: transport between custody buffers) |

### 5.4 Who vs where (documented deviation)

HFGT fuses them: a transformation resource is also a buffer. We keep them apart: buffers are places, resources execute.
Capability = (process at a buffer or origin-destination pair, executing resource). The paper's 4th-order
`M_PR(L, B_S, P, R)` already separates buffer and resource; constraint types I to III then compare **buffers**.
Mathematical reviewer to confirm before 0.9.9 is tagged.

### 5.5 Existence, availability, gaps

- Existence (J_S): at least one execution with `epistemic_status = computed` and a named executor. `simulated` and
  `unknown` never count. `evidence_ref = None` keeps the capability but sets `evidenced = 0` (asserted, not evidenced).
- Availability (K_S): `CapabilityConstraint`s valid at `as_of`. `drop` removes the node; `mask` keeps it with
  `available = 0` and **no edges in or out**, so counterfactuals ("what if the truck were back?") reuse one node order.
- Gaps (never guessed): transform/control without `at_buffer`; `transfers` without both buffers; a buffer that is not
  declared (when buffers are declared); missing `state_before` under `kind_state`; unmapped class (exchange); unknown
  executor; non-computed status. An execution with any bad incidence yields **no** capability: no partial capabilities.

## 6. Kernel math (infrastructure, numpy)

```text
place(l, y)  = sigma(B_S) * index(l) + index(y)              # rows of the matricized incidence
M-[place, e] = 1  if capability e pulls operand l from buffer y
M+[place, e] = 1  if capability e injects operand l into buffer y
W            = M+^T M-                                         # witnesses per ordered pair (real product)
A_rho        = (W > 0) * a a^T                                 # Boolean product, then K_S mask (a = available)
self_seq     = diag(A_rho);  diag(A_rho) := 0                  # self-sequences become a node feature
DOF_S        = sum(a);  DOF_rho = sum(A_rho)
```

Invariants the kernel asserts: each capability injects into exactly one buffer and pulls from exactly one buffer
(then Boolean and real products agree, paper eq. 80); `A_rho` equals the five-rule construction (section 9).

Layers: `input_operand_set` layer id of a capability = the sorted set of operands it pulls. Every capability is in
exactly one layer (mutually exclusive, collectively exhaustive); `edge_type` of an edge = layer id of its **target**.

## 7. Output: CapabilityGraphSample (PyG conventions, same as GraphSample)

| Tensor | Shape | dtype | Meaning |
|---|---|---|---|
| `hfgt.x` | (N, F) | float32 | node features, order `node_feature_names` |
| `hfgt.edge_index` | (2, E) | int64 | COO, row 0 = predecessor (source), row 1 = successor (target) |
| `hfgt.edge_attr` | (E, D) | float32 | edge features, order `edge_feature_names` |
| `hfgt.edge_type` | (E,) | int64 | target's input-operand-set layer (relation type for R-GCN) |
| `hfgt.candidate_edge_index` | (2, C) | int64 | optional proposals from splice/knn; **never merged** into edge_index |

Node features (F = 12):
`fc_transform, fc_transport, fc_hold, fc_control_ext, available, evidenced, log1p_evidence, n_pull_operands,
n_inject_operands, nonconsuming, self_sequence, terminal`

Edge features (D = 5):
`n_witnesses, crosses_buffer, same_resource, crosses_stage, via_nonconsuming`

Also carried (not tensors): `node_ids` (`process_id|resource_id`), `layer_ids`, edge witness table
(`edge, operand, buffer`), `dof_s`, `dof_rho`, `report` (gaps, coverage), `readiness`:
`reachable | blocked: constraints | unknown: translation gaps | unreachable`, `existence_basis`, `as_of`,
`request_digest`. Readiness is a structural reading for a person, never a release. Sources are the capabilities that pull from
`start_operands` (operand@buffer); with none declared, every available capability with no predecessor.

Optional `content` embeddings attach as extra node columns through `TensorTransformPort`; they describe what a
capability is about and never create edges. Candidate edges carry their retrieval score and stay candidates until a
person labels them (retrieval confidence is not relation confidence).

## 8. GNN encoder

Add `CapabilityGnnEncoderPort.encode(sample, content=None) -> Mapping[str, TensorRef]` beside the existing
`GnnEncoderPort`. Recommended first model: relational GCN over `edge_type`, messages in both directions
(upstream = "what must happen first", downstream = "whose work depends on this"). Suggested training targets, all
structural and checkable against the reference: reachability to terminal operands, dead-end detection, which single
constraint breaks a path, downstream capabilities affected by a constraint.

## 9. Acceptance tests

Golden files: `tests/fixtures/hfgt/wme_rack.synthetic.json` -> `wme_rack.expected.json` and
`wme_rack_gaps.synthetic.json` -> `wme_rack_gaps.expected.json`, produced by `scripts/hfgt_reference.py`
(standalone numpy oracle). `tests/test_hfgt.py` checks the implementation against them exactly, and the adapter itself
refuses to return a sample whose A_rho differs from the five-rule construction.

| Case | DOF_S | DOF_rho | Readiness | Dead ends |
|---|---|---|---|---|
| baseline | 10 | 12 | reachable | loose kit shipped warehouse->room201 by truck |
| truck cannot carry rack | 9 | 8 | blocked: constraints | + rack held on bench |
| builder unavailable for build | 9 | 8 | blocked: constraints | + kit held on bench |
| gaps fixture | 8 | 7 | unknown: translation gaps | 3 gaps reported (simulated hold, install without buffer, exchange) |

Identities (property tests on the fixture and on random small systems):
1. `A_S = J_S * not(K_S)`; DOF_S = number of available capabilities.
2. OR over resources of the transport capabilities gives the buffer graph; per held operand it gives the
   operand-indexed network (one-to-one special case only).
3. `A_rho = M+^T M-` equals the five-rule construction (I or II or III or IV) and V.
4. Boolean and real products agree.
5. Input-operand-set layers are mutually exclusive and collectively exhaustive.
6. `mask` and `drop` give the same DOF_S, DOF_rho, readiness and dead ends.
7. Simulated or unknown executions never create a capability; a constraint on a missing capability is an error;
   resource ids that are object ids are an error.
8. Contract docs for `datamesh-hfgt/v1` are generated and CI-gated like every other domain.

## 10. Open decisions (carried to 0.10.0; 0.9.9 ships the provisional choices below, flagged as deviations)

1. Who vs where deviation (5.4): mathematical reviewer.
2. Control as identity or state-change transform; exchange mapping (5.3): process SME.
3. `reads` / `checks` as non-consuming identity (5.2): process SME.
4. Default `operand_key = kind_state` (5.1): process SME.
5. Constraint vocabulary (PTO, region, certification, authority to displace) and who may author K_S rows.
6. Whether `observed` should require `evidence_ref`, or keep asserted capabilities with `evidenced = 0` (current).
