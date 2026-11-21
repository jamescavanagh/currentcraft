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

$$dX_t = b(X_t,u_t)\,dt + \sigma(X_t) \circ dW_t, \qquad b=(J-R)\nabla H+g\,u$$

Here $W_t$ is standard $m$-dimensional Brownian motion and $\sigma_k$ is column $k$ of $\sigma$. This is a **Stratonovich** equation, matching the geometric theory of [Cordoni, Di Persio and Muradore 2019](https://arxiv.org/abs/1910.01901), with deterministic-time supplied energy $\int_0^t u_s^{\top}y_s\,ds$. Noise is an unaccounted disturbance in this model, not an additional credited supply port. A stochastic supply port would need a separately declared supply integral.

For the supply convention above, define $S_t=H(X_t)-\int_0^t u_s^{\top}y_s\,ds$. Passivity splits into several non-equivalent notions; the names follow [Ackermann, Kruse and Tappe 2025](https://arxiv.org/abs/2512.05838):

| Notion | Condition | Relation |
| --- | --- | --- |
| Pathwise passivity | $S_t$ is non-increasing on every sample path | strongest; not implied by a generator inequality |
| Passive (local) supermartingale property | $\mathbb{E}[S_t\mid\mathcal F_s]\le S_s$ for $s\le t$ (locally, for the local property) | pathwise passivity implies the local property; the supermartingale property implies stochastic passivity when integrable |
| Stochastic passivity | $t \mapsto \mathbb{E}S_t$ is non-increasing | average bound only |

> [!note] Not the same as "weak passivity"
> [Cordoni, Di Persio and Muradore 2022](https://arxiv.org/abs/2202.08689) use **weak passivity** for a different notion: passivity required only outside a ball around a chosen state, tied to the existence of an invariant measure. It was built for additive noise. This page does not use that notion and does not claim it holds for the plate.

### Full generator condition

Derived here, not quoted from a source. Assume $H\in C^2$ and sufficiently regular coefficients for a well-defined, non-explosive solution on the stated domain and horizon. The equivalent Ito drift includes the Stratonovich correction:

$$b_{\mathrm{Ito}}=b+\frac12\sum_{k=1}^{m}(D\sigma_k)\,\sigma_k.$$

Consequently, for each admissible input,

$$\mathcal L^u H
= -\nabla H^{\top}R\nabla H+y^{\top}u
+\frac12\sum_k\nabla H^{\top}(D\sigma_k)\sigma_k
+\frac12\operatorname{Tr}[\sigma\sigma^{\top}\nabla^2H].$$

A pointwise sufficient **generator condition** is therefore

$$\boxed{\nabla H^{\top}R\nabla H\ \ge\
\frac12\sum_k\nabla H^{\top}(D\sigma_k)\sigma_k
+\frac12\operatorname{Tr}[\sigma\sigma^{\top}\nabla^2H]}.$$

This gives $\mathcal L^uH\le y^{\top}u$, the generator form of stochastic passivity used by [Cordoni et al. 2022](https://arxiv.org/abs/2202.08689) after Florchinger. Ito's formula gives a nonpositive drift for $S_t$, plus the local martingale $\int_0^t\nabla H(X_s)^{\top}\sigma(X_s)\,dW_s$. It yields stochastic passivity and the supermartingale statement only with the required integrability (for example, integrable initial storage and supplied energy/drift, and a square-integrable martingale integrand on the finite horizon). Otherwise state only the localized result; a local martingale or local supermartingale is not automatically a true one. Use a nonnegative storage function, or a justified constant shift of a lower-bounded energy, for a standard passivity claim.

For **constant additive noise**, $D\sigma_k=0$, so the condition reduces to

$$2\,\nabla H^{\top}R\nabla H\ge\operatorname{Tr}[\nabla^2H\,\sigma\sigma^{\top}].$$

The same reduced expression applies when the displayed drift is specified as an Ito drift from the outset; that is a different drift convention, not permission to drop the correction from the Stratonovich model above. The Hessian-only condition must not be used for general state-dependent Stratonovich noise. For example, $dX=X\circ dW$, $H=X^2/2$ has $\mathcal LH=X^2$: the correction and Hessian contributions are each $X^2/2$.

### Related literature and scope limits

1. A power-preserving interconnection of stochastic pH systems is a stochastic pH system in the setting of [Cordoni et al. 2019](https://arxiv.org/abs/1910.01901); for linear stochastic pH systems, energy-conserving interconnection again gives a stochastic pH system ([Ackermann et al. 2025](https://arxiv.org/abs/2512.05838)). Structural closure alone is not a passivity certificate for this disturbance/supply convention.
2. [Cordoni et al. 2022](https://arxiv.org/abs/2202.08689) provides related stochastic pH results; applying any passivity result requires matching its drift convention, supply, storage and regularity assumptions. The generator calculation above states the condition used in this note explicitly.
3. Boundary-controlled, infinite-dimensional stochastic pH systems with additive noise are well-posed ([Lamoline and Winkin 2019](https://arxiv.org/abs/1907.04158)). Their passivity is treated in separate work not reviewed here.
4. Stochastic pH neural networks extend strong and weak passivity notions to learned, interconnected stochastic systems ([Di Persio, Ehrhardt, Outaleb and Rizzotto 2025](https://arxiv.org/abs/2509.06674)).

## Consequence for the plate slice

The plate dynamics are conservative: $R=0$. Consider a fixed-mass segment with $X=(q,p)$, $H(q,p)=\tfrac12p^{\top}M^{-1}p+V(q)$, constant positive-definite $M$, no deterministic input, and **constant additive momentum noise** $\sigma=\begin{pmatrix}0\\B\end{pmatrix}$ with $B\ne0$. Then $D\sigma_k=0$ and

$$\mathcal LH=\frac12\operatorname{Tr}(M^{-1}BB^{\top})>0.$$

Under the stated integrability assumptions, $\mathbb EH(X_t)=\mathbb EH(X_0)+\tfrac12\operatorname{Tr}(M^{-1}BB^{\top})t$. Thus this particular noisy conservative plate is **not stochastically passive relative to the deterministic power supply alone**, and so not passive in any stronger sense. This is a direct positive-generator calculation, not a conclusion drawn merely from failure of a sufficient condition. Declared dissipation would have to dominate the noise contribution pointwise to satisfy the generator condition; adding some dissipation is not by itself sufficient. Whether the outside-a-ball weak notion of Cordoni et al. 2022 could apply is not checked. Changing the model or the credited supply is a coordinator decision, not a default.

This conclusion does not cover arbitrary multiplicative noise, noise tangent to energy level sets, or mass-change jumps. State-dependent noise requires the full generator calculation; mass events require separate jump-energy accounting.

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
3. On a fixed-mass segment with constant additive momentum noise $B$, no input and $R=0$, Monte Carlo growth of $\mathbb EH$ matches $\tfrac12\operatorname{Tr}(M^{-1}BB^{\top})t$ within a stated statistical tolerance.
4. With declared dissipation, verify the full generator inequality (including $D\sigma_k$ for state-dependent Stratonovich noise), solution/storage/integrability assumptions, and stochastic passivity within a stated statistical tolerance. Simulation alone is not a proof.
5. Every result stays `simulated`; no crossing or port event releases work.
6. A multiplicative-noise control $dX=X\circ dW$, $H=X^2/2$ yields $\mathcal LH=X^2$, not $X^2/2$; a constant-noise control has zero Stratonovich correction. Reject an implementation that silently drops the correction.

## Limits

- No mapping from business evidence to $\sigma$, $R$ or port signals is proposed. That needs the approved B2 mapping.
- Stochastic passivity is an average statement; it does not bound any single run.
- The generator condition is sufficient, not an equivalence in general; its failure alone does not establish nonpassivity.
- Softened gravity is a modelling choice; results from the cited papers are not assumed to transfer unchanged.

## Related

- [Plate and spatial isosceles three-body](PLATE_ISOSCELES.md)
- [Refinement and power-port harmonization](../domain/REFINEMENT_PORT_HARMONIZATION.md)
