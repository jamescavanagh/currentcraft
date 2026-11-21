---
title: L-system domain vocabulary
version: 0.1.1
status: proposed
tags: [currentcraft, domain, lsys, grammar, vocabulary]
---

# L-system domain vocabulary

> [!warning] Status: proposed, every symbol a candidate
> This page names the alphabet the expectation grammar may use, written **only in domain objects** from [V1_DOMAIN.md](V1_DOMAIN.md), [DOMAIN_SCAFFOLD.md](DOMAIN_SCAFFOLD.md) and [PROCESS_FIRST.md](PROCESS_FIRST.md). No symbol, production or mapping here is accepted until the coordinator labels it. No grammar code ships with this page.

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

**`impedance_match`** (candidate grammar verb): proposes that two expected objects could connect through compatible interfaces. It grows a possibility only. It is not a power-port connection, a behavioural contract or a compatibility verdict (see [Refinement and power-port harmonization](REFINEMENT_PORT_HARMONIZATION.md), proposed separately).

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
| Subsystems | `Subsystem` | nonterminal under `Project` | no extra hierarchy imposed |
| Product Features | none | none | 0.11 versioned feature graph |
| Site Acceptance Testing | none (a test would be a control-class `ProcessExecution` that `checks` objects) | none | no test-basis, result or acceptance objects |
| Commercial Orders | `Order` | nonterminal, independent of `Document` | `Contract` remains a scaffold |
| Clients | `Client` on `Party` | context only; never rewritten into work | relationship records beyond classification |
| Estimation / Needs Analysis | none (workbook occurrence edges are source evidence, not entities) | none | no estimate or need objects |
| Timecards (cross-cutting) | `TimeCard` (scaffold) | not a domain and not a symbol; time consumed by executions | definition pending |

## Candidate productions, read as domain objects

The private register holds five evidenced productions. Their public reading:

| Rule | Domain-object reading | Mapping status |
| --- | --- | --- |
| `p1: Project → F[Location] × n` | a project decomposes into locations | `Location` exists as an unreviewed scaffold; no project link yet |
| `p2: Location → F[Subsystem] × k` | a location decomposes into subsystems | `Subsystem` has a project link only; location link absent |
| `p3: Subsystem → F[o] × m` | a subsystem holds objects | `o` must be a non-resource object |
| `p4: Need → Document` | a need produces a scope document | `Need` has no domain object; gap |
| `p5: Document → BOM + Scope` | a scope document produces a BOM and a labor/service scope | `BOM` exists; `Scope` has no domain object; gap |

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
| `app.application.lsys.load_profile` raises `ValueError` on every reject case and accepts every accept case | skipped until the loader exists |

Proposed profile shape used by the fixture: `axiom`, `productions` (`id`, `predecessor`, `successor` list) and optional `expectations` (`verb`, `args`). Symbol matching trims and case-folds, so spelling variants of a resource are rejected too.

## Not claimed

- No grammar implementation, profile format or production engine exists in the repo.
- No production is accepted; productions with gaps cannot be implemented until their domain objects exist.
- Mapping a source concept to a domain object here is a proposal, not an approved field authority.
- Readout symbols carry no process meaning.
