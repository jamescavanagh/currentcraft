---
title: Challenge and appeal route
version: 0.15.0
status: proposed design only; implementation and policy approval pending
tags: [currentcraft, agency, challenge, appeal, authority]
---

# Challenge and appeal route

> [!important] Status and purpose
> Design only. People must be able to understand and influence decisions, not merely observe them.
> This page proposes a review route for gate decisions, human labels and releases. It implements no
> contracts, endpoints, persistence, identity provider, authority checks or operational policy.
> The prerequisites below may be delivered before this feature; their current absence does not block
> design. Their unresolved choices do block activation of authoritative challenge outcomes.

## Existing foundations and implementation prerequisites

The inspected baseline is `8c3f3b8442b400d7ca730d56e23d33aa228cc364`.

- Reuse `app.domain.quality.GateDecision`, defined in `src/app/domain/quality/gate_decision.py`.
  It already captures actor, effect, scope, purpose, authority evidence, evaluation, execution and
  exact target/transition versions. It is not a missing concept to recreate.
- [P4 design](../domain/P4_DESIGN_CONTRACTS.md) requires independent authority/evidence resolution
  and identifies `CommittedGateDecisionRef` as a read view, not an approval or proof of commitment.
  Canonical loading, the decision's originating view and application integration remain prerequisites.
- [Release ladder](../domain/RELEASE_LADDER.md) implements contracts, transitions and replay, not
  identity/policy verification, durable history or gate-to-ladder mapping. Reuse it, do not invent a
  second ladder or treat a domain record as an operational grant.
- [HTTP API](HTTP_API.md) and [shared source identity](HTTP_IDENTITY.md) distinguish possession of
  the shared bearer secret from a person's identity or approval authority. Source identity is not
  human identity. A future per-person identity choice must serve this feature too.
- Follow the existing [P4 integration plan](P4_INTEGRATION.md) and
  [persistence design](PERSISTENCE.md) when implementation is authorized. No parallel history store
  or challenge-specific transaction machinery is selected here.

## Participation and the visible route

Proposed standing includes the original decision-maker, a participant whose work or resources are
 affected, an affected downstream participant, and an authorized representative acting for one of them.
A person may contest an incorrect label or release even if they did not create it. Filing does not
require the authority to release work or overturn the original decision. It requires an attributable
person and a recorded connection to the affected scope; the identity and standing policy is open.
People are participants/resources, never the objects processed by the work.

Review authority is separate from filing standing. A reviewer must hold verifiable authority for the
contested scope and requested remedy. Merely holding a role string, owning a queue or filing a
challenge grants none. Proposed independence: the original decision-maker may supply evidence but
must not be the sole adjudicator of their own decision. Conflicts and delegated representation must
be disclosed; an alternative reviewer/escalation route must be visible.

Alongside each decision or label, show a discoverable route containing:

- What may be contested, who may file and what evidence is needed.
- The accountable reviewer role, its scope and authority-verification status, plus the next
  escalation authority if that reviewer is conflicted, unavailable or challenged.
- How to submit, acknowledge, track, supplement, withdraw and appeal, with accessible alternatives
  to the primary interface.
- The current challenge state, receipt and latest response; policy-defined acknowledgment/review
  targets and an overdue escalation path. No response-time guarantee is invented here.
- Whether the work is disputed, held or continuing; the exact affected scope and who can change it.
- Proposed remedies, alternatives and effects on other work, reserved capacity and decision rights.

Do not show a fictitious reviewer or active submission route while configuration is unresolved.
Show "review authority not configured" and the configured escalation contact if one exists.
Visibility of a route must not expose private evidence or identities to unauthorized readers.
These are future read/UI requirements, not new endpoints in this pass.

## Proposed information model

These are semantic requirements for later contracts, not a new canonical schema.

**Challenge.** An opaque identity, attributable challenger, standing/representation context, grounds,
requested remedy, filed time, current review state, assigned reviewer role and scope, and a versioned
history. Record submission/acknowledgment/review/outcome/withdrawal times separately with timezone
and timestamp provenance. A requested reviewer is not a verified authority.

**Contested act.** Kind (gate decision, label or release), exact record identity and version, affected
work-package/target version, execution/run where applicable, and the original actor/effect. A release
challenge cites its originating gate decision and ladder move; a label challenge cites the label event
and candidate/evaluation versions. Do not coerce a label into a GateDecision. If legacy linkage cannot
be resolved, retain the reported reference as unresolved and prohibit authoritative resolution until
the exact act can be verified.

**Decision view.** Cite the immutable view identity/version or equivalent reproducible snapshot used
by the original actor, its run, target/evaluation/graph versions, policy/configuration versions,
visibility/pruning context and known omissions. Preserve the challenger's observed view separately.
Do not silently replace either with the latest view. If the original view was not captured, record
that gap; reconstruction is explicitly a reconstruction with evidence and limits, not the original.

**Evidence.** Cite exact evidence references/versions, source and capture-time provenance, relevant
facts, supporting and conflicting material, and the basis for the claimed error. Restricted evidence
uses opaque handles with controlled access, not copied source text. Allow a person to cite a missing
or inaccessible record and request its review rather than manufacture evidence. Such a filing is
marked incomplete, not treated as proof that a release is safe.

**Review and effects.** Record reviewer identity, verified authority and evidence, independence
assessment, reasoned outcome, evidence actually reviewed, review-time view/version, interim
hold/continuation decision, affected scope, alternatives and capacity consequences. Link any
replacement decision, label event, reevaluation or ladder move explicitly.

## Review states and appeals

The review-state vocabulary is exactly `filed`, `acknowledged`, `under review`, `upheld`,
`overturned`, `withdrawn`. It is separate from the ladder and gate-effect vocabularies.

1. Filing creates `filed` with a receipt and immutable submission context. Filing is not admission
   of the claim, reviewer acceptance, a hold or an approval.
2. `filed -> acknowledged` records receipt by the accountable review lane, assigned route and
   evidence gaps. Acknowledgment does not validate the contested act.
3. `acknowledged -> under review` records the verified reviewer and authority, conflicts check,
   evidence examined and an explicit interim work disposition.
4. `under review -> upheld` means the contested act stands, with reasons. It never means the
   challenge was upheld. `under review -> overturned` means the contested act is not sustained,
   with reasons and explicit remedial links. Both require a scoped, attributable human review.
5. `filed`, `acknowledged` or `under review -> withdrawn` records the challenger's attributable
   withdrawal and reason if supplied. Withdrawal does not erase the filing, prove the act correct,
   or automatically remove an independently imposed hold.
6. Supplementing evidence appends to the same case without rewriting prior submissions.
   Terminal cases are not silently reopened. A further appeal creates a new linked challenge
   citing the previous outcome, grounds and the next competent authority.

An appeal against an outcome preserves both the original contested act and the preceding review's
decision/view/evidence context. A separate competent reviewer considers the appeal under the approved
independence policy. Exhaustion, time limits, new-evidence requirements and exceptional reopening
are policy choices for James, not assumed limits on agency.

`return` remains a gate effect and `Returned` a ladder disposition, not a seventh review state.
An overturned decision may lead to a new authorized `return` for rework, linked to that outcome.

## Work disposition and capacity

Proposed default: filing marks work as disputed but does not itself move a rung, reserve capacity,
cancel a release or grant a stop-work power. A request for an urgent hold is recorded separately.
The authorized review/operational lane must explicitly decide the interim scope and rationale;
policy may require a protective hold, but this page does not activate such policy.

Keep dispute state, current rung, hold status and effective permission to execute separately visible.
A `hold` does not move the work down the ladder. A `return` or `reject` follows the existing ladder
rules, including reasons, rework re-entry and terminal rejection. A challenge never skips rungs.

- **Possible or Conditional:** filing creates no allocation or commitment. Further progression
  still requires recorded HIL evidence and authority.
- **Ready:** a dispute does not become release evidence. An unresolved blocking criterion, stale
  view or unavailable authority verification prevents a new positive release; do not equate every
  open challenge with a blocking criterion without an approved policy.
- **Executable:** filing does not retroactively undo performed work or cancel commitments.
  A verified, scoped hold can suspend further affected execution without falsifying the historical
  rung/release. Execution-enforcement integration must be designed before claiming this is effective.
- **Returned:** a challenge does not resurrect rejected work or bypass rework/re-entry rules.

If reviewer/authority verification is unavailable, no authoritative overturn, new release or
capacity displacement may be inferred. Preserve any existing valid hold. Do not pretend an
automatic system-wide stop was issued; surface the gap and use the configured escalation route.

Before a hold, continuation or remedy is authorized, present affected work/dependencies, affected
resource roles, existing reservations, displacement scope and duration/expiry, feasible alternatives,
uncertainty and who bears the delay. Unknown capacity impacts remain unknown. Review authority does
not automatically include `displace_allocation` or spend authority. A separate verified decision is
needed when the remedy changes those commitments. Record notifications and access-limited views
without leaking other participants' private details.

Upholding does not clear a hold automatically or reuse stale release evidence. Overturning does not
itself release or roll back work. For a gate decision, an overturn links to a new GateDecision with
fresh scoped authority/evidence and current-version checks; the original is immutable. For a label,
append a superseding label event and reevaluate affected outputs rather than editing past labels.
Any consequential release still uses a new GateDecision and the normal ladder checks. An outcome
without its required remedial links is visibly incomplete, never presented as an effective remedy.

## Audit, staleness and safe projections

Preserve the full chain: original act/version -> original view -> challenge/submissions/evidence ->
acknowledgment -> reviewer/authority verification -> interim work decisions -> reasoned outcome ->
replacement act/reevaluation -> consequent ladder/capacity decisions -> any further appeal.
Every change records actor, time, reason and exact version references. Reconstruct history without
re-executing work. No deletion or silent mutation of a challenged decision or earlier outcome.

Compare the contested historical view with the current review-time view; explain changed facts.
A stale historical act remains challengeable. Applying a remedy requires fresh target/run/view
checks; a concurrent change must prevent an obsolete effect, not erase the challenge.
Retries must not duplicate outcomes or work effects; different content under one retry key must
conflict. Durable atomicity, concurrency and request-key representation follow later integration
design, not a new store defined here.

Public projections use opaque references and allowlisted reasons/statuses. Keep private evidence,
source identifiers, personal contact data and raw exceptions out of public payloads and logs.
Redaction must not disguise a blocker or falsely imply complete evidence; show a restricted/missing
evidence marker and a review route. Public examples and eventual tests must be synthetic.

## Open decisions for James before implementation acceptance

1. **Per-person identity and standing:** select the identity mechanism and binding to human actor,
   representative, reviewer and role. Decide service-identity limits and access policy. The shared
   bearer secret is not a substitute. No provider or role mapping is selected by this page.
2. **Authority verification:** approve the verification/evidence source, delegation, revocation,
   scope, reviewer independence, substitute authority and escalation rules. Decide who may impose
   urgent holds, authorize continuation and displace capacity. No operating authority is granted here.
3. **Canonical GateDecision integration:** reuse the existing domain record; decide its canonical
   loading/commitment path, originating-view reference and links to challenge outcomes, label
   supersession and ladder moves. The old "record not found" description is a discovery question
   resolved by the inspected code, not grounds for inventing a replacement.
4. **Review/hold policy:** approve or revise the proposed standing, transition/appeal rules,
   response targets, protective-hold triggers, expiry/review/escalation and execution enforcement.
   Decide how incomplete remedies and unavailable reviewers are surfaced without implying approval.

These are future implementation/activation dependencies, not prerequisites to submitting this
design page for review. Recheck the application at implementation time: prerequisites may already
have landed and must be reused rather than reimplemented.

## Acceptance scenarios for later implementation

No executable tests are added or claimed in this design-only slice.

- AC-01: affected participants and representatives can file against each supported act kind;
  filing standing does not grant review/release authority.
- AC-02: original act/version, original view and evidence are pinned; missing original views or
  inaccessible evidence remain explicit gaps. A later view cannot rewrite the original context.
- AC-03: all six states and legal transitions above retain actor/time/reasons; invalid transitions
  fail, withdrawal retains history and appeal creates a linked case with independent review.
- AC-04: identity/authority absence, revocation, wrong scope or reviewer conflict prevents an
  authoritative outcome; a shared token alone cannot adjudicate or release.
- AC-05: filing on every ladder rung preserves that rung and makes the dispute visible; authorized
  hold/return/reject and any protective policy are distinct and do not skip ladder checks.
- AC-06: an unresolved blocker, stale view or missing authority cannot release Ready work.
  Executable work is not retroactively undone; an enforced hold requires proven integration.
- AC-07: both outcomes retain full lineage; overturning a gate decision creates a linked new
  GateDecision, while label correction appends a superseding event and reevaluates.
- AC-08: capacity consequences and unknowns are visible; review authority alone cannot spend,
  reserve or displace resources. Withdrawal/upholding never silently clears an independent hold.
- AC-09: concurrent changes and identical/conflicting retries cannot produce stale or duplicate
  work effects. Historical challenges remain readable even when the target advances.
- AC-10: route, competent authority, status, alternatives and escalation are discoverable;
  redaction hides private content without hiding a blocker or implying configured authority.

## Delivery limits

Only this design page and its docs index row belong to this slice. No changes to `src/`,
generated contracts/OpenAPI, `deploy/`, persistence or endpoints. No version bump of the application,
no claim that release 0.15.0 is implemented, no merge, license, deployment or operational acceptance.
