---
title: L-system domain vocabulary
version: 0.2.0
status: implemented (loader and bounded growth); every production a candidate
tags: [currentcraft, domain, lsys, grammar, vocabulary]
---

# L-system domain vocabulary

> [!warning] Status: loader and bounded growth implemented; every production a candidate
> This page names the alphabet the expectation grammar may use, written **only in domain objects** from [V1_DOMAIN.md](V1_DOMAIN.md), [DOMAIN_SCAFFOLD.md](DOMAIN_SCAFFOLD.md), [PROCESS_FIRST.md](PROCESS_FIRST.md) and [NEEDS_AND_SCOPE.md](NEEDS_AND_SCOPE.md). `app.application.lsys` implements the alphabet, the digest-pinned profile loader and bounded growth to *Possible* ([Loader and growth](#loader-and-growth)). No production or mapping is accepted until the coordinator labels it; loading a profile is not approval.

## The rule

**Grammar proposes, evidence disposes, gates decide.** The L-system grows *possible* structure. It never creates records, never moves an object's lifecycle and never climbs the [release ladder](RELEASE_LADDER.md) past *Possible*. Evidence (`Fact`, `QualityEvidence`) decides whether a grown possibility matches anything real; a control-class `ProcessExecution` with an `AuthorityRef` decides whether it may proceed.

The grammar sits beside infrastructure as a pure expectation generator. Grammar profiles are versioned, digest-pinned reference data loaded by infrastructure and mapped by the application into allowlisted objects. Nothing executable comes from a profile.

## Abstraction from source vocabulary

Source material (decks, workbooks, price books, schedules) uses its own words. The public grammar never does.

| Rule | Meaning |
| --- | --- |
| Symbols are domain object kinds | a symbol names a class from `app.domain` or an application contract, never a company term, code, file name or part number |
| Source spellings stay private | observed forms and their evidence live in the private register; the public tree keeps only the domain-object reading |
| Source keys are `ExternalReference` | a business number is `ExternalReference(namespace, key)`, never a symbol and never an ID |
| Unmapped means unmapped | a source concept with no domain object is listed as a gap, not given a public stand-in |

## Alphabet

### Symbol kinds

| Kind | What it may name | Example symbol |
| --- | --- | --- |
| axiom | the start object of a growth | `Project` |
| nonterminal | an object kind that can be rewritten into parts | `Subsystem`, `BOM`, `Document` |
| terminal | an object (operand) that is not rewritten further | `o` (any object id in an `ObjectIncidence`) |
| parameter | a typed value carried by a symbol | `k` (child count), `stage` |
| condition | a guard read from evidence, never from the grammar | `Fact.epistemic_status`, `missing_reason` |
| state | a readout carried for exploration only | see [Readout symbols](#readout-symbols) |

**Objects are things, never people.** `Employee`, `Contributor` and `Agent` are resources. They are never axioms, nonterminals or terminals; they appear only through `CapabilityBinding` on an execution. A production that rewrites a resource is invalid.

### Verbs

L-system verbs are the process effects already defined in [PROCESS_FIRST.md](PROCESS_FIRST.md). The grammar may *expect* them; only a recorded `ProcessExecution` makes them happen.

| Verb | Function classes that allow it | Lifecycle meaning |
| --- | --- | --- |
| `produces` | transform, exchange | birth |
| `consumes` | transform, exchange | death |
| `reads` | all | none |
| `revises` | transform | state change |
| `holds` | hold | state change (time only) |
| `transfers` | transport, exchange | state change (location or custody) |
| `checks` | control | state change only with a gate decision |

Gate decisions (`hold`, `release`, `reject`, `return`) are not grammar verbs. The grammar may expect that a gate will be entered; entering a gate is not approval.

**`impedance_match`** (candidate grammar verb): proposes that two expected objects could connect through compatible interfaces. It grows a possibility only. It is not a power-port connection, a behavioural contract or a compatibility verdict (see [Refinement and power-port harmonization](REFINEMENT_PORT_HARMONIZATION.md)).

### Relations the grammar may expect

Only links that already exist as typed fields on domain objects.

| From | Link | To |
| --- | --- | --- |
| `Phase`, `WBS`, `Task`, `Subsystem` | project | `Project` |
| `Task` | optional subsystem / phase / WBS facts | `Subsystem`, `Phase`, `WBS` |
| `AssetInstance` | product, project | `ProductDefinition`, `Project` |
| `BOMLine` | BOM, product | `BOM`, `ProductDefinition` |
| `ShipmentLine` | shipment; product quantity **or** asset | `Shipment`, `ProductDefinition` / `AssetInstance` |
| `Document` | project | `Project` |
| `Order` | project, counterparty, document references | `Project`, `Party`, `Document` |
| `Client`, `Vendor` | party | `Party` |
| `ProcessExecution` | incidence (verb) | any object |
| `ProcessExecution` | executed_by | `CapabilityBinding` → resource |

No hierarchy beyond these links is inferred. WBS, task and phase nesting stay explicit optional links.

## Domains in domain objects

Eleven domains plus one cross-cutting concern. A domain with no object yet is a gap: the grammar may not grow symbols for it.

| Domain | Domain objects | Grammar role | Gap |
| --- | --- | --- | --- |
| Projects | `Project`, `Phase`, `WBS`, `Task` | `Project` is the axiom; `Phase` is lifecycle only, never the simulator's physics phase | stage mapping is explicit application data (`StageMapping`) |
| Inventory | `ProductDefinition`, `AssetInstance`, `BOM`, `BOMLine`, `Shipment`, `ShipmentLine` | nonterminals and terminals; catalog identity distinct from physical identity | custody and holding workflow unresolved |
| Employees and Contributors | `Employee`, `Contributor` (resources), `CapabilityAssertion` | **not in the alphabet**; resources bind to executions only | permissions and authority model pending |
| Working Docs | `Document` | nonterminal; revisions and workbook occurrences are evidence about it | lifecycle transitions fail closed |
| Drawings | `Drawing` (separate aggregate, scaffold) | none yet | controlled-release fields proposed, not implemented |
| Subsystems | `Subsystem` | nonterminal under `Project` or `Location` | optional explicit `location_id`; no extra hierarchy imposed |
| Product Features | none | none | 0.11 versioned feature graph |
| Site Acceptance Testing | none (a test would be a control-class `ProcessExecution` that `checks` objects) | none | no test-basis, result or acceptance objects |
| Commercial Orders | `Order` | nonterminal, independent of `Document` | `Contract` remains a scaffold |
| Clients | `Client` on `Party` | context only; never rewritten into work | relationship records beyond classification |
| Estimation / Needs Analysis | `Need`, `Scope` ([NEEDS_AND_SCOPE.md](NEEDS_AND_SCOPE.md)); workbook occurrence edges stay source evidence | `Need` nonterminal (p4); `Scope` produced from a `Document` (p5) | no estimate, price or approval objects |
| Timecards (cross-cutting) | `TimeCard` (scaffold) | not a domain and not a symbol; time consumed by executions | definition pending |

## Candidate productions, read as domain objects

The private register holds five evidenced productions. Their public reading:

| Rule | Domain-object reading | Mapping status |
| --- | --- | --- |
| `p1: Project → F[Location] × n` | a project decomposes into locations | candidate; typed link `Location.project_id` |
| `p2: Location → F[Subsystem] × k` | a location decomposes into subsystems | candidate; typed link `Subsystem.location_id` (optional fact) |
| `p3: Subsystem → F[o] × m` | a subsystem holds objects | candidate; terminal `o`, a non-resource object in an `ObjectIncidence` |
| `p4: Need → Document` | a need produces a scope document | candidate; typed link `Need.document_ids` |
| `p5: Document → BOM + Scope` | a scope document produces a BOM and a labor/service scope | candidate; `Scope.document_id` is typed, `Document` to `BOM` is a reported gap |

`F[...] × n` means "grow up to n bracketed children". Counts are parameters from evidence, not defaults. Every production output is *Possible*, carries the grammar profile digest, and is discarded or matched by evidence.

## Readout symbols

Nine physics symbols in the register (vorticity, divergence, flow compression, dilation, the vorticity dilation term, polar coordinates, radial and angular velocity, polar vorticity) are **state readouts**, not domain objects. Today they correspond only to the `datamesh-sim/v2` field channels (`vorticity`, `divergence`), which are `embedding_geometry`, not physical encodings of object meaning. Polar terms are not a first-class contract input. They may annotate a grown possibility for exploration; they never become conditions for growth or release.

## Acceptance: resources are rejected

[`tests/test_lsys_resource_symbols.py`](../../tests/test_lsys_resource_symbols.py) with the synthetic cases in [`tests/fixtures/lsys/resource_symbol_cases.json`](../../tests/fixtures/lsys/resource_symbol_cases.json):

| Check | Runs now |
| --- | --- |
| Resources are discovered as `Resource` subclasses from the domain; the set must equal Employee, Contributor, Agent until reviewed | yes |
| The alphabet tables on this page name no resource class | yes |
| Every reject case (axiom, predecessor, successor terminal, verb argument, incidence object, the `Resource` base, case and whitespace variants) is caught; every accept case is clean and names real domain classes | yes |
| `ProcessExecution` rejects a resource id used as an object id | yes |
| `app.application.lsys.load_profile` raises `ValueError` naming the resource on every reject case and accepts every accept case | yes; `ci_public.sh` fails if it skips |

Profile shape: `profile_version` and `source_digest` (both required), `axiom`, `productions` (`id`, `predecessor`, `successor` list) and optional `expectations` (`verb`, `args`). Every fixture case carries both fields with a matching digest. Resource matching trims and case-folds, so spelling variants of a resource are rejected too.

## Loader and growth

Implemented in `app.application.lsys` (contracts in [READINESS_CONTRACTS.md](../contracts/READINESS_CONTRACTS.md)) with the file adapter `app.infrastructure.lsys.read_profile`. Tests: [`tests/test_lsys_grammar.py`](../../tests/test_lsys_grammar.py), [`tests/test_lsys_resource_symbols.py`](../../tests/test_lsys_resource_symbols.py), [`tests/domain/test_needs_and_scope.py`](../../tests/domain/test_needs_and_scope.py); all three run without skips in `scripts/ci_public.sh`.

| # | Rule | Enforced by |
| --- | --- | --- |
| L1 | `profile_version` (semantic version) and `source_digest` are required; the digest is SHA-256 of the canonical content (version, axiom, productions, expectations) and must match | `GrammarProfile` |
| L2 | A symbol is an alphabet domain object spelled exactly, or the terminal `o`; anything else is rejected. `Drawing`, `TimeCard` and other scaffolds are not symbols | `OBJECTS`, `Production`, `Expectation` |
| L3 | A resource in any position or spelling is rejected with `resource symbol rejected` | `is_resource` |
| L4 | `o` is never rewritten and never the axiom; production ids are unique | `GrammarProfile` |
| L5 | Verbs are the seven process effects plus `impedance_match`, which takes exactly two objects | `Expectation` |
| L6 | Every successor reports `typed_link` (an existing typed field), `terminal` or `gap`; gaps are never given a stand-in | `GrammarProfile.links`, `LINKS` |
| L7 | A production is applied only with an evidenced `GrowthCount`; no count means `count_not_evidenced`, the depth bound means `depth_limit`; growth stops past 10,000 nodes | `grow` |
| L8 | Every grown node is `possible`, carries the profile digest and is an application value, never a domain record; the only ladder move growth emits is a `grammar_growth` `grow` | `PossibleNode`, `ladder_moves` |
| L9 | Growth is deterministic: the same digest, counts and depth give the same derivation id and nodes | `grow` |
| L10 | The file adapter loads a profile only if its bytes match a pinned SHA-256, caps size at 1 MiB and never echoes content in errors | `read_profile` |

```python
>>> from app.application.lsys import GrowthCount, grow, load_profile, profile_digest
>>> data = {"profile_version": "0.1.0", "axiom": "Project",
...         "productions": [{"id": "p1", "predecessor": "Project", "successor": ["Location"]}]}
>>> data["source_digest"] = profile_digest(data)
>>> d = grow(load_profile(data), (GrowthCount(production_id="p1", count=2, evidence_ids=("ev-1",)),))
>>> [(n.symbol, n.rung) for n in d.nodes]
[('Project', 'possible'), ('Location', 'possible'), ('Location', 'possible')]
>>> grow(load_profile(data)).unexpanded[0].reason
'count_not_evidenced'

```

## Coordinator decisions (2026-11-21)

| # | Decision |
| --- | --- |
| 1 | The `Location` to `Project` link is recognized as needed. It is a domain change and is not made in this page; p1 and p2 stay candidate until it exists. |
| 2 | p4 and p5 are kept and marked blocked until `Need` and `Scope` domain objects exist. They are not dropped. |
| 3 | Resources stay out of the alphabet entirely; the acceptance tests enforce it. |
| 4 | `impedance_match` is confirmed as the grammar verb name. It grows possibilities only. |
| 5 | `app.application.lsys.load_profile` is confirmed as the loader name. Profiles must carry `profile_version` and `source_digest`. |
| 6 | Make the L-system first class with option B: loader and growth engine plus `Need`, `Scope` and the `Subsystem` to `Location` link. |
| 7 | Correction to decision 1: `Location.project_id` already existed in the domain; this page was stale. p1 now cites it. |
| 8 | The `Document` to `BOM` link stays a reported gap; `BOM` is not changed in this slice. |

## Not claimed

- No production is accepted. Loading a profile, growing it or emitting a `grow` move approves nothing and advances nothing past *Possible*.
- Not the 0.13.0 expectation grammar: no context sensitivity, held-open alternatives, negative application conditions, evidence matching, absence states or seed grammars. Expectations are carried, never matched.
- `Need` and `Scope` are capture proposals; they are not in the enterprise snapshot record set yet.
- Mapping a source concept to a domain object here is a proposal, not an approved field authority.
- Readout symbols carry no process meaning.
