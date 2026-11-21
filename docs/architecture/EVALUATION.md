---
title: Evaluation harness
version: 0.11.0
status: contracts and metrics implemented; private labeled set and benchmark runner not implemented
tags: [currentcraft, architecture, evaluation]
---

# Evaluation harness

> [!note] Status
> Implemented: contracts and pure-Python metrics in `app.application.evaluation`, generated reference in
> [READINESS_CONTRACTS.md](../contracts/READINESS_CONTRACTS.md). Not implemented: a loader for the private
> labeled set, a benchmark runner, and any retrieval system to evaluate (0.12.0). Not claimed: that any
> score here says a relation is true or that work is ready.

## Purpose

Retrieval, grammar expectations and graph edges all need to be measured before anyone relies on them. This
slice turns human judgments and system outputs into one report per system, with enough provenance and
coverage that a reader can tell what a number means and how much of the population it covers.

## Rules

1. **Judgments come from people; runs and predictions come from systems.** Real judgment sets live in
   private references. The public tree holds synthetic fixtures only.
2. **Open world.** An unjudged prediction is unknown, never wrong. Edge precision counts only predictions
   labelled `true` or `false`; `unknown` and unjudged predictions are counted and reported separately.
3. **Omit, never zero-fill.** A metric with no judged population is absent (`None` or an empty map), not 0.
4. **Coverage travels with the score.** Every report states queries judged, scored, excluded for having
   nothing relevant, and missing a run. A scored query with no run counts as zero and is reported.
5. **Evidence envelope.** Every report carries the judgment set and its SHA-256, the system and its version,
   the configuration SHA-256, the run reference, an optional filter scope, and whether pass criteria were
   frozen before the run. Held-out claims require `criteria_frozen_before_run`.
6. **One system per report.** Runs from another system are rejected. Conflicting judgments raise.
7. **Typed metrics.** Recall and nDCG are keyed by `k`, so one report holds several cut-offs. Edge metrics
   are reported overall and per relation type, because calibration is per relation.
8. **Absence states are shared.** The seven states come from `app.application.common` and match
   [DOCUMENT_LIFECYCLE.md](../domain/DOCUMENT_LIFECYCLE.md). The confusion matrix shows, for example,
   `inaccessible` misread as `not_found_in_scope`.
9. **Deterministic.** Input order does not change a report.
10. **Not authority.** A report is a measurement. It never confirms a relation, promotes a candidate or
    releases work.

## Example

>>> from app.application.evaluation import EvaluationEnvelope, RankedRun, RelevanceJudgment, evaluate
>>> env = EvaluationEnvelope(judgment_set_id="synthetic", judgment_set_sha256="0" * 64, system_id="s",
...                          system_version="0.0.1", config_sha256="0" * 64, run_id="r1",
...                          criteria_frozen_before_run=True)
>>> judgments = [RelevanceJudgment(query_id="q1", item_id="d1", grade=2)]
>>> runs = [RankedRun(system_id="s", query_id="q1", items=("d9", "d1"))]
>>> report = evaluate(env, k_values=(1, 2), relevance=judgments, runs=runs)
>>> report.retrieval.recall_at
{1: 0.0, 2: 1.0}
>>> report.retrieval.mrr
0.5
>>> report.edges is None
True

## Acceptance tests

`tests/test_evaluation_harness.py`: recall, MRR and nDCG on a synthetic fixture; several `k` in one report;
missing runs and queries without relevant items; omitted metrics; conflicting judgments; one system per
report; envelope hash validation; open-world edge precision and per-relation breakdown; absence accuracy and
confusion; determinism; frozen reports; a description on every field; this page's example; slice layering.

## Limits

Synthetic correctness is not retrieval quality on real documents. The harness does not sample, stratify or
compute confidence intervals; those belong to the benchmark runner.
