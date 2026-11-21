---
title: Refinement and power-port harmonization (proposal)
version: 0.11.0
status: proposed
tags: [currentcraft, research, refinement, port-hamiltonian, compatibility, versioned-feature-graph]
---

# Refinement and power-port harmonization (proposal)

> [!warning] Proposal; names and definition approved, theory unproven
> This page aligns two vocabularies for safe substitution. It defines nothing in code, adds no contract and grants no authority. A refinement verdict is evidence for a human decision, never a release.

## Problem

Two literatures answer "can this version safely replace that one?" in different words:

- **Contract refinement.** An assume-guarantee contract $C = (A, G)$ states what a component assumes about its environment and what it guarantees in return. $C'$ refines $C$ when every environment of $C$ is an environment of $C'$ and every implementation of $C'$ is an implementation of $C$; for contracts in canonical form, $A \subseteq A'$ and $G' \subseteq G$ ([Incer, Benveniste and Sangiovanni-Vincentelli 2023](https://arxiv.org/abs/2309.08875)). For linear dynamical systems with inputs and outputs, see [Shali, van der Schaft and Besselink 2021](https://arxiv.org/abs/2103.12646).
- **Port-Hamiltonian interconnection.** Subsystems exchange energy only through declared power ports; a power-conserving interconnection of port-Hamiltonian systems is again port-Hamiltonian, so the dissipation inequality is kept when the storage function is bounded below ([van der Schaft 2024](https://arxiv.org/abs/2412.19673)).

A targeted arXiv search did not find a paper that defines contract refinement directly over port-Hamiltonian ports. This page proposes the alignment; it does not claim one exists in the literature.

## Vocabulary collisions in this repository

| Word | Already means here | Name for the research sense (approved 2026-11-21) |
| --- | --- | --- |
| port | array-free Protocol in the hexagonal architecture ([Docs-first](../DOCS_FIRST.md)) | **power port** |
| contract | Pydantic application contract | **behavioural contract** (assume-guarantee; the term follows Shali et al. 2021, who use Willems' behavioural approach) |
| gauge | observed, read-only state | not used; no gauge-theory reading |
| storage | persistence | **storage function** $H$, always with "function" |

## Term alignment

| Behavioural contract | Power-port reading | Shared term |
| --- | --- | --- |
| assumption $A$ | admissible environments at the power port | port assumption |
| guarantee $G$ | output law plus dissipation inequality $\dot H \le y^{\top}u$ | port guarantee |
| interface | power port $(e, f)$ with declared units | power port |
| composition $\parallel$ | power-conserving interconnection | interconnection |
| compatibility | admissible interconnection constraint | compatibility |
| violation | passivity deficit: stored energy exceeds supplied energy | violation |
| refinement $\preceq$ | passivity-preserving substitution | refinement |
| mutual refinement | contract equivalence: same environments and same implementations ([Incer et al. 2023](https://arxiv.org/abs/2309.08875)) | equivalence |

## Definition (approved as a working definition, 2026-11-21)

Version $V'$ **refines** version $V$ on power-port set $P$ when all of the following hold:

1. $V'$ exposes the same ports $P$, with the same effort and flow pairing and units.
2. $V'$ accepts every environment $V$ accepts (assumptions are no stronger).
3. Under those environments, $V'$ is passive on $P$ and its port behaviour satisfies $V$'s guarantees (guarantees are no weaker).
4. Stochastic variant: condition 3 holds as stochastic passivity (in expectation), with the tolerance and evidence recorded ([stochastic port-Hamiltonian note](../pipelines/STOCHASTIC_PORT_HAMILTONIAN.md)).
5. Symmetry: if $V$ is equivariant under a declared group (for example the A/B mirror swap of the plate), $V'$ is too.

Three outcomes per version pair: **refines**, **breaks** (a witness is recorded) or **unknown** (evidence missing; not the same as breaks).

The page stays `proposed`: the definition is approved for use in design work, but no published theorem establishes it.

## What composes

- Contract composition is monotonic with respect to refinement: refining the parts refines the composite ([Incer et al. 2023](https://arxiv.org/abs/2309.08875), Proposition 3).
- The dissipation inequality is preserved by power-conserving interconnection ([van der Schaft 2024](https://arxiv.org/abs/2412.19673)).
- Caveat: geometric composition does not always give trajectory correspondence for non-constant Dirac structures ([Kirchhoff 2026](https://arxiv.org/abs/2608.29731)). Any composed refinement claim states which case it is in.

## Recorded coordinator decisions (2026-11-21)

- The constrained spatial isosceles three-body model is retained.
- Phase space is void as a third term.
- API interaction snapshots belong in `app.infrastructure` (recorded evidence of what crossed an interface).
- Impedance matching is a domain term for L-system verbs. As a grammar verb it grows possibilities only; it releases nothing.
- "Power port" and "behavioural contract" are adopted as the names for the research senses.
- The five-condition refinement definition is adopted as a working definition; the page remains `proposed`.
- Passivity is the bridge between refinement and power ports, **not** the third term. The third term remains open.
- Whether the 0.11 versioned feature graph stores a refines / breaks / unknown verdict per version pair is deferred to the 0.11 versioned-feature-graph task.

## Open

- The third term.
- The 0.11 verdict-storage question (tracked on the 0.11 task, not here).

## Not claimed

- No published theorem establishes this definition.
- No mapping from products, features or project records to ports, energy or passivity.
- No implementation, contract, test or generated reference.
