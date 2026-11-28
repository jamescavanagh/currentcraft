---
title: Synthetic heterogeneous candidate graph
version: 0.1.0
tags: [automl, lsys, graph, small-world]
status: design only
---

# Synthetic heterogeneous candidate graph

> [!note]
> Design page only. No contract, port, adapter, rule engine, graph metric, model, viewer or live data exists for this slice. Proposed package `app.application.hetgraph`, schema `currentcraft-hetgraph/v1`. Nothing here approves, releases, assigns or confirms anything.

## Purpose

Compose bounded [L-system](../domain/LSYS_DOMAIN_VOCABULARY.md) derivations and typed cross-link rules into one heterogeneous **candidate** graph that a reviewer can read: what the grammar proposed, which cross-links a rule proposed and why, what was deferred or left unknown under load, and how the graph's clustering and path length compare with matched null graphs. Grammar proposes, evidence disposes, gates decide. See [docs-first design](../DOCS_FIRST.md) and [data policy](../../DATA_POLICY.md).

## Layers

Three layers stay separately queryable. No operation moves an edge between them.

| Layer | Source | May contain | Never |
| --- | --- | --- | --- |
| Growth | `app.application.lsys.grow` | `possible` object nodes and `grows` edges from one pinned profile digest | resources, records, ladder moves past `Possible` |
| Candidate | cross-link rules in this slice | `cross_link` candidates between growth nodes, each with rule id, rule version and inputs digest | feasible sequences, confirmed relations |
| Feasible | [HFGT capability graph](HFGT_CAPABILITY_GRAPH.md) `edge_index` | evidence-backed feasible sequences between capabilities | candidate or growth edges |

A human `LabelEvent` from the [probe](PROBE.md) seam, pinned to the candidate's reading digest, can mark a candidate `confirmed`, `rejected` or `unknown` in a separate, versioned label projection. A confirmed label is a reviewed relation, not feasibility, not authority and not a release. Conflicting labels remain a conflict.

## Node and edge types

- Node types: growth node (an alphabet object kind at `possible`), capability (process plus resource, from HFGT only) and the terminal `o`. Operands are objects, never people; resources never appear as growth or candidate nodes.
- Edge relation types: `grows` (parent to child within one derivation), `cross_link` (a rule-proposed relation between two growth nodes) and `feasible_sequence` (HFGT only). Every edge records its layer, relation type, source, version and status (`candidate`, `confirmed`, `rejected`, `unknown`, `superseded`).
- L-systems grow trees. Cross-links that make the graph heterogeneous come only from typed rules, never from extra grammar productions.

## Cross-link rules

A rule is versioned, declarative data, digest-pinned like a grammar profile:

1. **Typed endpoints.** Source and target are alphabet object kinds. The relation must be an existing typed link (`LINKS`) or the candidate verb `impedance_match` with exactly two objects. Unknown kinds, resources and the terminal `o` as a link endpoint are rejected.
2. **Application conditions.** A rule applies only within one derivation scope and only where its positive condition holds. Negative application conditions block self-links, duplicates of an existing candidate or growth edge, and any pair the rule lists as excluded. Applicability that cannot be decided from the inputs is `unknown`, never false.
3. **Bounds.** Each rule has a maximum number of proposals, each node a maximum candidate fan-out, and the run a maximum number of candidate edges. Growth bounds stay those of the grammar (10,000 nodes, depth 32). Bounds count operations, not wall time, so runs are deterministic.
4. **Output.** A rule only proposes. Every proposal carries rule id, rule version, profile digest, endpoint ids and an inputs digest. Proposals never enter HFGT `edge_index`, `candidate_edge_index` translation or feasible path counts.

## Overload accounting

Proposals pass through a bounded admission step in a deterministic order (rule id, then source id, then target id). Every proposal ends in exactly one outcome:

| Outcome | Meaning |
| --- | --- |
| `admitted` | added to the candidate layer |
| `deferred` | valid but over a rule, fan-out or run budget; reason recorded, not dropped |
| `rejected` | invalid endpoints or blocked by a negative application condition |
| `duplicate` | same endpoints and relation as an admitted or growth edge |
| `unknown` | applicability could not be decided from the inputs |

Conservation: proposals generated equal the sum of the five outcomes for every run and every rule. Nothing is silently dropped. Deferred work is reported with its reason so a reviewer can see what overload hid. These are synthetic mechanism results, not process, staffing or capacity claims.

## Small-world readout

An exploratory statistic on a declared projection, never a quality, influence or readiness score.

1. **Projection.** Declare which relation types and layers enter an undirected simple graph. Default: growth plus admitted candidates. Record the projection digest.
2. **Statistics.** Report mean local clustering, mean shortest path over reachable pairs, the unreachable fraction and global efficiency, following the existing enrichment `SmallWorldStats` readout. Compare efficiency rather than path length when reachability changes.
3. **Matched nulls.** Use a seeded ensemble of at least two null families: same node and edge count, and degree-preserving double-edge swaps. Where feasible, also preserve per-relation-type counts. Report each null's distribution, the observed value, the difference and an interval; never compare against a single random graph.
4. **Negative controls.** A ring lattice, a random graph, a star, a path and a disconnected graph must give their expected qualitative readings.
5. **Boundaries.** Labels change a statistic only through an explicit, versioned projection rule. No statistic changes the release ladder, a label, an edge's layer, authority or allocation.

## Proposed contracts

| Contract | Required meaning |
| --- | --- |
| `CrossLinkRule` | Rule id and version, endpoint kinds, relation, positive and negative conditions, budgets, source digest. |
| `CrossLinkProposal` | Rule, endpoints, inputs digest and one outcome with reason. |
| `HetGraphRequest` | Profile digest, evidenced growth counts, rule set digest, budgets, optional HFGT graph reference and projection. |
| `HetGraphResult` | Node and edge counts by layer and type, outcome counts per rule, conservation check, derivation id and output digest. |
| `NullEnsembleSpec` | Null families, ensemble size, seeds and preserved properties. |
| `SmallWorldComparison` | Observed statistics, per-family null summaries, differences, intervals and the projection digest. |

Names avoid collision with HFGT `CandidateEdge` and enrichment `SmallWorldStats`.

## Acceptance checks before implementation is accepted

- Same profile digest, counts, rule set and seeds give the same derivation id, proposals, outcomes and output digest; a changed rule digest is rejected rather than reinterpreted.
- Resources, unknown kinds, `o` as a link endpoint and malformed rules fail closed. Hostile depth, fan-out, cycles and oversized rule sets stay within bounds with an explicit reason.
- Candidate and growth edges never change HFGT feasible sequence counts; feasible counts are identical with and without the candidate layer.
- Conservation holds per rule and per run; deferred and unknown proposals are reported, not dropped.
- Small-world comparisons use matched nulls with recorded seeds and preserved properties, and the negative controls pass.
- A label, score or statistic cannot write a confirmed edge, change a layer, advance the ladder or grant authority.
- Public fixtures are synthetic with opaque ids; no enterprise vocabulary appears in payloads, logs, errors, exports or docs.

## Not claimed

- No relation is confirmed. A small-world reading is not a validated organizational or process property.
- No encoder, GNN or CNN arm consumes this graph yet. Existing [CNN/GNN ports](CNN_GNN_PIPELINE.md) remain ports.
- Real records stay blocked on validated process mapping and event history. This page does not certify a permission boundary.

## Build order

Design page (this). Next: described contracts and generated reference, then the deterministic rule engine with overload accounting on the synthetic profile `tests/fixtures/lsys/synthetic_profiles.json`, then the matched-null readout with negative controls. Port and adapter come after the pure checks pass.
