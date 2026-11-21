---
title: Stochastic port-Hamiltonian systems (research note)
version: 0.11.0
status: research
tags: [currentcraft, research, plate, port-hamiltonian, stochastic, passivity]
---

# Stochastic port-Hamiltonian systems (research note)

> [!warning] Research lens, not implemented
> Nothing on this page is implemented. It records a literature pairing (port-Hamiltonian systems with stochastic contracts) as a reference for the [plate slice](PLATE_ISOSCELES.md). It is not a validated process equivalence, it makes no claim about products or projects, and any future result stays `epistemic_status="simulated"`.

## Purpose

The plate slice is a closed, conservative model. Its only external influence is an `ObjectMassEvent`, and today the run handles that event by resetting the energy and spin baselines. Port-Hamiltonian (pH) theory offers a different reading: an external influence is a **power port**, and the energy that crosses it is accounted for instead of reset. The stochastic extension adds uncertainty to that port, which matches inputs that come from uncertain evidence.

This page fixes the vocabulary and the known results before any contract or code is written.

## Deterministic port-Hamiltonian form

$$\dot x = (J(x) - R(x))\,\nabla H(x) + g(x)\,u, \qquad y = g(x)^{\top} \nabla H(x)$$

- $H$ is the storage function (total energy), $J = -J^{\top}$ the interconnection structure, $R = R^{\top} \succeq 0$ the dissipation.
- $(u, y)$ is a power port: $y^{\top} u$ is the power supplied through it.
- **Passivity:** $\dot H = -\nabla H^{\top} R \nabla H + y^{\top} u \le y^{\top} u$. Stored energy never grows faster than the power supplied; with $H$ bounded below, the system is passive with respect to the supply rate $y^{\top}u$.
- **Closure:** a power-conserving interconnection of pH systems is again a pH system, with energy equal to the sum of the parts, so the dissipation inequality survives composition ([van der Schaft 2024](https://arxiv.org/abs/2412.19673)).

## Stochastic extension

This page uses the Ito form:

$$dX_t = \big((J - R)\nabla H + g\,u\big)\,dt + \sigma(X_t)\, dW_t$$

The geometric theory of [Cordoni, Di Persio and Muradore 2019](https://arxiv.org/abs/1910.01901) is written in Stratonovich form; for additive noise (constant $\sigma$), the case used below, the two forms coincide.

With $Z_t = H(X_t) - \int_0^t u^{\top} y \, ds$, passivity splits into several non-equivalent notions ([Ackermann, Kruse and Tappe 2025](https://arxiv.org/abs/2512.05838)):

| Notion | Condition | Relation |
| --- | --- | --- |
| Pathwise passivity | $Z_t$ is non-increasing on every sample path | strongest |
| Passive (local) supermartingale property | $Z_t$ is a (local) supermartingale | pathwise passivity implies the local property; the supermartingale property implies stochastic passivity |
| Stochastic passivity | $t \mapsto \mathbb{E} Z_t$ is non-increasing, i.e. $\mathbb{E} H(X_t) \le \mathbb{E} H(X_0) + \mathbb{E}\int_0^t u^{\top} y \, ds$ | holds on average only |

> [!note] Not the same as "weak passivity"
> [Cordoni, Di Persio and Muradore 2022](https://arxiv.org/abs/2202.08689) use **weak passivity** for a different notion: passivity required only outside a ball around a chosen state, tied to the existence of an invariant measure. It was built for additive noise. This page does not use that notion and does not claim it holds for the plate.

Known results:

1. A power-preserving interconnection of stochastic pH systems is a stochastic pH system ([Cordoni et al. 2019](https://arxiv.org/abs/1910.01901)); for linear stochastic pH systems, energy-conserving interconnection again gives a stochastic pH system ([Ackermann et al. 2025](https://arxiv.org/abs/2512.05838)).
2. **Derived here, not quoted.** For the Ito form, the generator gives $\mathcal{L}H = -\nabla H^{\top} R \nabla H + y^{\top}u + \tfrac12 \operatorname{Tr}[\nabla^2 H\,\sigma\sigma^{\top}]$. Passivity in the generator sense $\mathcal{L}H \le y^{\top}u$ (the definition used by [Cordoni et al. 2022](https://arxiv.org/abs/2202.08689), after Florchinger) therefore holds when $2\,\nabla H^{\top} R \nabla H \ge \operatorname{Tr}[\nabla^2 H\,\sigma\sigma^{\top}]$: dissipation must dominate the energy the noise injects. That generator condition implies stochastic passivity.
3. Boundary-controlled, infinite-dimensional stochastic pH systems with additive noise are well-posed ([Lamoline and Winkin 2019](https://arxiv.org/abs/1907.04158)). Their passivity is treated in separate work not reviewed here.
4. Stochastic pH neural networks extend strong and weak passivity notions to learned, interconnected stochastic systems ([Di Persio, Ehrhardt, Outaleb and Rizzotto 2025](https://arxiv.org/abs/2509.06674)).

## Consequence for the plate slice

The plate dynamics are conservative: $R = 0$. With additive noise on the momenta, the left side of the derived condition is zero and the right side is positive, so it cannot be met. Expected energy then grows; with $H = \tfrac12 p^{\top}M^{-1}p + V(q)$ the growth rate is $\tfrac12 \operatorname{Tr}(M^{-1}\sigma\sigma^{\top})$. A stochastic plate is therefore **not stochastically passive** (in expectation, and so in no stronger sense) unless dissipation is declared explicitly. Whether the outside-a-ball weak notion of Cordoni et al. 2022 could apply is not checked. Declaring dissipation is a modelling choice for the coordinator, not a default.

| Plate concept today | pH reading | Status |
| --- | --- | --- |
| `ObjectMassEvent` (live mass change) | input event on a power port; energy supplied is recorded | not implemented |
| energy and spin baselines reset at mass events | replaced by an energy-balance account: $H(t) - H(0) - \int y^{\top}u$ | not implemented |
| uncertain load evidence | noise term $\sigma$, stochastic passivity | not implemented |
| `max_relative_energy_drift` | energy-balance residual per port segment | not implemented |
| mirror symmetry of side bodies A and B | equivariance; must be preserved by any port added | existing diagnostic only |

> [!note] Interconnection caveat
> Composing the geometric structures (Dirac structures) does not always give a one-to-one correspondence of trajectories. It does for pH ODEs and constant Dirac structures; for non-constant structures a sufficient condition is required ([Kirchhoff 2026](https://arxiv.org/abs/2608.29731)).

## Acceptance tests (if a slice is ever built)

1. With $\sigma = 0$ and no port, existing plate results are byte-identical and persisted ids unchanged.
2. With a deterministic port, the energy-balance residual is bounded and second order in `dt`.
3. With additive momentum noise and $R = 0$, Monte Carlo growth of $\mathbb{E}H$ matches $\tfrac12 \operatorname{Tr}(M^{-1}\sigma\sigma^{\top})\,t$ within a stated statistical tolerance.
4. With declared dissipation that satisfies the derived condition, stochastic passivity holds within tolerance.
5. Every result stays `simulated`; no crossing or port event releases work.

## Limits

- No mapping from business evidence to $\sigma$, $R$ or port signals is proposed. That needs the approved B2 mapping.
- Stochastic passivity is an average statement; it does not bound any single run.
- Softened gravity is a modelling choice; results from the cited papers are not assumed to transfer unchanged.

## Related

- [Plate and spatial isosceles three-body](PLATE_ISOSCELES.md)
- [Refinement and power-port harmonization](../domain/REFINEMENT_PORT_HARMONIZATION.md)
