"""Release-ladder contracts: where a work package stands and the only legal ways it moves.

Pure contracts, no persistence, no policy. Rules:

* Growth (grammar derivation or intake) may only *create* work at ``possible``; it never advances it.
* Every move after creation needs a human-in-the-loop label event. Entering a gate is not approval.
* ``ready`` needs a computed readiness reading with zero blocking criteria. Readiness never reaches
  ``executable`` on its own.
* ``executable`` needs a release-scope authority reference, verification evidence and computed
  (never simulated or unknown) epistemic status.
* No rung may be skipped. ``returned`` records a disposition: ``rework`` (may re-enter at
  ``possible``) or ``rejected`` (terminal).

Authority references and label events are opaque here; verifying them against identity and policy
belongs to the decision API (0.15.0). Positive operational release stays fail-closed until an
enterprise release policy is approved.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, model_validator

from app.application.common import _Frozen

LADDER_SCHEMA = "currentcraft-ladder/v1"

Rung = Literal["possible", "conditional", "ready", "executable", "returned"]
Verb = Literal["grow", "hold", "release", "return", "reject", "reenter"]
Origin = Literal["grammar_growth", "intake", "hil"]
Epistemic = Literal["computed", "simulated", "unknown"]
Disposition = Literal["rework", "rejected"]

Ident = Field(min_length=1, max_length=200)

# (from_rung, verb) -> to_rung. ``None`` as from_rung means the work package does not exist yet.
TRANSITIONS: dict[tuple[Optional[str], str], str] = {
    (None, "grow"): "possible",
    ("possible", "release"): "conditional",
    ("conditional", "release"): "ready",
    ("ready", "release"): "executable",
    ("possible", "hold"): "possible",
    ("conditional", "hold"): "conditional",
    ("ready", "hold"): "ready",
    ("executable", "hold"): "executable",
    ("possible", "return"): "returned",
    ("conditional", "return"): "returned",
    ("ready", "return"): "returned",
    ("executable", "return"): "returned",
    ("possible", "reject"): "returned",
    ("conditional", "reject"): "returned",
    ("ready", "reject"): "returned",
    ("executable", "reject"): "returned",
    ("returned", "reenter"): "possible",
}


class LadderViolation(ValueError):
    """A move the ladder does not permit. ``code`` is stable for tests and API errors."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


class ReadinessReading(_Frozen):
    """A readiness evaluation at the moment of the move. Structural reading, never a release."""

    evaluation_id: str = Ident
    criteria_evaluated: int = Field(ge=0)
    blocking: int = Field(ge=0)
    epistemic_status: Epistemic

    @model_validator(mode="after")
    def _blocking_within_evaluated(self):
        if self.blocking > self.criteria_evaluated:
            raise ValueError("blocking criteria cannot exceed evaluated criteria")
        return self


class LadderMove(_Frozen):
    """One requested move for one work package."""

    schema_version: Literal["currentcraft-ladder/v1"] = LADDER_SCHEMA
    work_package_id: str = Ident
    verb: Verb
    origin: Origin
    derivation_id: Optional[str] = Field(default=None, min_length=1, max_length=200)
    label_event_id: Optional[str] = Field(default=None, min_length=1, max_length=200)
    authority_ref: Optional[str] = Field(default=None, min_length=1, max_length=200)
    authority_scope: Optional[Literal["release"]] = None
    verification_evidence_ids: tuple[str, ...] = ()
    readiness: Optional[ReadinessReading] = None
    epistemic_status: Epistemic = "unknown"
    disposition: Optional[Disposition] = None
    reason: Optional[str] = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def _shape(self):
        if self.verb == "grow":
            if self.origin == "hil":
                raise ValueError("growth is created by grammar_growth or intake, not by a gate decision")
            if self.origin == "grammar_growth" and self.derivation_id is None:
                raise ValueError("grammar growth must cite its derivation")
        else:
            if self.origin != "hil":
                raise ValueError("only a human-in-the-loop decision moves work after creation")
            if self.label_event_id is None:
                raise ValueError("a HIL move needs a label event")
        if self.verb in ("return", "reject"):
            expected = "rework" if self.verb == "return" else "rejected"
            if self.disposition != expected:
                raise ValueError(f"{self.verb} requires disposition {expected!r}")
            if self.reason is None:
                raise ValueError(f"{self.verb} requires a reason")
        elif self.disposition is not None:
            raise ValueError("disposition applies only to return and reject")
        if any(not e for e in self.verification_evidence_ids):
            raise ValueError("evidence ids must be non-empty")
        return self


_TERMINAL_RETURNED = "rejected"


def apply_move(current: Optional[str], move: LadderMove, *, returned_disposition: Optional[str] = None) -> str:
    """Return the rung after ``move`` or raise :class:`LadderViolation`.

    ``returned_disposition`` is the disposition recorded when the package entered ``returned``;
    ``replay`` tracks it. A rejected package cannot re-enter.
    """
    key = (current, move.verb)
    if key not in TRANSITIONS:
        if current is None:
            raise LadderViolation("not_created", "work must be grown at possible before it can move")
        if move.verb == "grow":
            raise LadderViolation("growth_cannot_advance", "growth creates possible work; it never moves existing work")
        if move.verb == "release" and current in ("executable", "returned"):
            raise LadderViolation("no_rung_above", f"nothing to release from {current}")
        raise LadderViolation("illegal_transition", f"{move.verb} is not allowed from {current}")

    target = TRANSITIONS[key]

    if move.verb == "reenter" and returned_disposition == _TERMINAL_RETURNED:
        raise LadderViolation("rejected_is_terminal", "rejected work cannot re-enter; grow a new work package")

    if target == "ready" and move.verb == "release":
        r = move.readiness
        if r is None:
            raise LadderViolation("readiness_missing", "ready needs a readiness reading")
        if r.epistemic_status != "computed":
            raise LadderViolation("readiness_not_computed", "ready needs a computed readiness reading")
        if r.blocking:
            raise LadderViolation("readiness_blocked", f"{r.blocking} blocking criteria remain")

    if target == "executable" and move.verb == "release":
        if move.authority_ref is None or move.authority_scope != "release":
            raise LadderViolation("authority_missing", "executable needs a release-scope authority reference")
        if not move.verification_evidence_ids:
            raise LadderViolation("verification_missing", "executable needs verification evidence")
        if move.epistemic_status != "computed":
            raise LadderViolation("not_computed", "simulated or unknown work can never become executable")
    return target


def replay(moves: list[LadderMove]) -> dict[str, str]:
    """Replay moves in order; returns the final rung per work package. Raises on the first violation."""
    rung: dict[str, Optional[str]] = {}
    disposition: dict[str, Optional[str]] = {}
    for m in moves:
        cur = rung.get(m.work_package_id)
        new = apply_move(cur, m, returned_disposition=disposition.get(m.work_package_id))
        rung[m.work_package_id] = new
        if new == "returned":
            disposition[m.work_package_id] = m.disposition
        elif m.verb == "reenter":
            disposition[m.work_package_id] = None
    return {k: v for k, v in rung.items() if v is not None}
