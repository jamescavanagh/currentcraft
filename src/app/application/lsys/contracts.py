"""L-system grammar contracts, profile loader and bounded growth (design: docs/domain/LSYS_DOMAIN_VOCABULARY.md).

Grammar proposes, evidence disposes, gates decide. Rules enforced here:

* A profile is declarative data: ``profile_version`` and a SHA-256 ``source_digest`` over its canonical
  content are required, and the digest must match. Nothing executable comes from a profile.
* Every symbol names a domain object kind from the alphabet, or the terminal ``o``. Resources are
  rejected in any position and any spelling variant. Unknown or non-canonical symbols are rejected.
* Verbs are the seven process effects plus ``impedance_match`` (exactly two arguments).
* Growth applies a production only with an evidenced count; there are no default counts. Every grown
  node is at ``possible`` and carries the profile digest. Growth never creates domain records and never
  advances the release ladder.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Mapping, Optional

from pydantic import Field, field_validator, model_validator

from app.application.common import _Frozen
from app.application.ladder import LadderMove

from .alphabet import OBJECTS, TERMINAL, GrammarVerb, is_resource, link_for

SCHEMA_VERSION = "currentcraft-lsys/v1"
MAX_NODES = 10_000
MAX_DEPTH = 32

LinkStatus = Literal["typed_link", "terminal", "gap"]
UnexpandedReason = Literal["count_not_evidenced", "depth_limit"]


def _check_symbol(symbol: str, *, allow_terminal: bool) -> str:
    if not isinstance(symbol, str):
        raise ValueError("symbol must be a string")
    if is_resource(symbol):
        raise ValueError(f"resource symbol rejected: {symbol.strip()!r} is a resource, never an object")
    if symbol == TERMINAL:
        if not allow_terminal:
            raise ValueError("the terminal o cannot be rewritten or used as the axiom")
        return symbol
    if symbol not in OBJECTS:
        raise ValueError(f"unknown symbol {symbol!r}: symbols must name an alphabet domain object exactly")
    return symbol


def _canonical(profile_version: Any, axiom: Any, productions: Any, expectations: Any) -> bytes:
    body = {"profile_version": profile_version, "axiom": axiom,
            "productions": [{"id": p["id"], "predecessor": p["predecessor"], "successor": list(p["successor"])} for p in productions],
            "expectations": [{"verb": x["verb"], "args": list(x["args"])} for x in expectations]}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def profile_digest(profile: Mapping[str, Any]) -> str:
    """SHA-256 of a profile's canonical content (version, axiom, productions, expectations); excludes the digest itself."""
    try:
        return hashlib.sha256(_canonical(profile["profile_version"], profile.get("axiom"),
                                         profile.get("productions", ()), profile.get("expectations", ()))).hexdigest()
    except (KeyError, TypeError) as exc:
        raise ValueError("profile is not in the decided shape") from exc


class Production(_Frozen):
    """One candidate rewrite: predecessor -> successor symbols. A candidate, never an accepted rule."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$", description="Profile-local production id, e.g. p1.")
    predecessor: str = Field(description="Domain object kind rewritten; never a resource or the terminal o.")
    successor: tuple[str, ...] = Field(min_length=1, max_length=16, description="Symbols grown per evidenced repetition; domain objects or o.")

    @field_validator("predecessor")
    @classmethod
    def _pred(cls, v):
        return _check_symbol(v, allow_terminal=False)

    @field_validator("successor")
    @classmethod
    def _succ(cls, v):
        return tuple(_check_symbol(s, allow_terminal=True) for s in v)


class Expectation(_Frozen):
    """An expected process effect over symbols. Only a recorded ProcessExecution makes it happen."""

    verb: GrammarVerb = Field(description="Process effect or impedance_match; gate decisions are not verbs.")
    args: tuple[str, ...] = Field(min_length=1, max_length=8, description="Symbols the verb is expected over.")

    @field_validator("args")
    @classmethod
    def _args(cls, v):
        return tuple(_check_symbol(s, allow_terminal=True) for s in v)

    @model_validator(mode="after")
    def _arity(self):
        if self.verb == "impedance_match" and len(self.args) != 2:
            raise ValueError("impedance_match proposes a connection between exactly two objects")
        return self


class ProductionLink(_Frozen):
    """How one successor symbol relates to its predecessor in the domain model."""

    production_id: str = Field(description="Production the successor belongs to.")
    successor: str = Field(description="Successor symbol.")
    status: LinkStatus = Field(description="typed_link (an existing typed field records it), terminal (object incidence) or gap.")
    link: Optional[str] = Field(default=None, description="Holder.field recording the link; empty for terminal and gap.")


class GrammarProfile(_Frozen):
    """A versioned, digest-pinned grammar profile. Loaded data, never approval of any production."""

    schema_version: Literal["currentcraft-lsys/v1"] = Field(default=SCHEMA_VERSION, description="Payload schema.")
    profile_version: str = Field(pattern=r"^\d+\.\d+\.\d+$", description="Profile semantic version (required).")
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$", description="SHA-256 of the canonical profile content (required, verified).")
    axiom: str = Field(description="Start object of growth; a domain object kind, never a resource or o.")
    productions: tuple[Production, ...] = Field(default=(), max_length=256, description="Candidate productions.")
    expectations: tuple[Expectation, ...] = Field(default=(), max_length=256, description="Expected process effects; carried, never executed.")

    @field_validator("axiom")
    @classmethod
    def _axiom(cls, v):
        return _check_symbol(v, allow_terminal=False)

    @model_validator(mode="after")
    def _consistent(self):
        ids = [p.id for p in self.productions]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate production id")
        actual = hashlib.sha256(_canonical(self.profile_version, self.axiom,
                                           [p.model_dump() for p in self.productions],
                                           [x.model_dump() for x in self.expectations])).hexdigest()
        if actual != self.source_digest:
            raise ValueError("source_digest does not match the profile content")
        return self

    def links(self) -> tuple[ProductionLink, ...]:
        """Typed-link status of every successor; gaps are reported, never given a stand-in."""
        out = []
        for p in self.productions:
            for s in p.successor:
                link = link_for(p.predecessor, s)
                status = "terminal" if s == TERMINAL else ("typed_link" if link else "gap")
                out.append(ProductionLink(production_id=p.id, successor=s, status=status, link=link))
        return tuple(out)


def load_profile(data: Mapping[str, Any]) -> GrammarProfile:
    """Validate profile data into a GrammarProfile. Raises ValueError on any rejected symbol, shape or digest."""
    if not isinstance(data, Mapping):
        raise ValueError("profile must be a mapping")
    return GrammarProfile.model_validate(dict(data))


class GrowthCount(_Frozen):
    """An evidenced repetition count for one production. Counts come from evidence, never defaults."""

    production_id: str = Field(min_length=1, max_length=32, description="Production the count applies to.")
    count: int = Field(ge=0, le=1000, strict=True, description="Repetitions of the successor group per predecessor node.")
    evidence_ids: tuple[str, ...] = Field(min_length=1, description="Evidence the count was read from; required.")


class PossibleNode(_Frozen):
    """A grown possibility. Not a record, not approved work and never above the possible rung."""

    node_id: str = Field(max_length=64, description="Deterministic id: derivation id plus breadth-first index.")
    path: str = Field(description="Growth path from the axiom: production.repetition.position segments.")
    symbol: str = Field(description="Domain object kind or o.")
    parent_id: Optional[str] = Field(default=None, description="Node this one was grown from; empty for the axiom.")
    production_id: Optional[str] = Field(default=None, description="Production that grew it; empty for the axiom.")
    depth: int = Field(ge=0, description="Rewrite depth from the axiom.")
    link_status: Optional[LinkStatus] = Field(default=None, description="Domain link status to the parent; empty for the axiom.")
    rung: Literal["possible"] = Field(default="possible", description="Always possible: growth never advances the ladder.")


class Unexpanded(_Frozen):
    """A node that has a production but was not rewritten, and why."""

    node_id: str = Field(description="Node left unexpanded.")
    production_id: str = Field(description="Production that was not applied.")
    reason: UnexpandedReason = Field(description="count_not_evidenced or depth_limit.")


class Derivation(_Frozen):
    """One bounded, deterministic growth from a profile. Possibilities only; evidence and gates decide."""

    schema_version: Literal["currentcraft-lsys/v1"] = Field(default=SCHEMA_VERSION, description="Payload schema.")
    derivation_id: str = Field(pattern=r"^drv-[0-9a-f]{16}$", description="Stable id over profile digest, counts and depth.")
    profile_version: str = Field(description="Profile version grown from.")
    profile_digest: str = Field(description="Profile source_digest; every node inherits it.")
    max_depth: int = Field(ge=0, le=MAX_DEPTH, description="Rewrite depth bound.")
    counts: tuple[GrowthCount, ...] = Field(description="Evidenced counts used.")
    nodes: tuple[PossibleNode, ...] = Field(description="Grown possibilities in breadth-first order.")
    unexpanded: tuple[Unexpanded, ...] = Field(default=(), description="Rewrites not applied, with reasons.")
    expectations: tuple[Expectation, ...] = Field(default=(), description="Carried profile expectations; unmatched.")


def grow(profile: GrammarProfile, counts: tuple[GrowthCount, ...] = (), max_depth: int = 4) -> Derivation:
    """Grow possibilities breadth-first from the axiom. Deterministic; bounded by depth and MAX_NODES."""
    if not 0 <= max_depth <= MAX_DEPTH:
        raise ValueError(f"max_depth must be between 0 and {MAX_DEPTH}")
    known = {p.id for p in profile.productions}
    by_id = {}
    for c in counts:
        if c.production_id not in known:
            raise ValueError(f"count for unknown production {c.production_id!r}")
        if c.production_id in by_id:
            raise ValueError(f"duplicate count for production {c.production_id!r}")
        by_id[c.production_id] = c
    ordered = tuple(sorted(by_id.values(), key=lambda c: c.production_id))
    seed = json.dumps({"digest": profile.source_digest, "depth": max_depth,
                       "counts": [[c.production_id, c.count, sorted(c.evidence_ids)] for c in ordered]},
                      sort_keys=True, separators=(",", ":"))
    derivation_id = "drv-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    rules: dict[str, list[Production]] = {}
    for p in profile.productions:
        rules.setdefault(p.predecessor, []).append(p)
    root = PossibleNode(node_id=f"{derivation_id}:0", path="0", symbol=profile.axiom, depth=0)
    nodes, unexpanded, frontier = [root], [], [root]
    while frontier:
        nxt = []
        for node in frontier:
            for rule in rules.get(node.symbol, ()):
                if node.depth >= max_depth:
                    unexpanded.append(Unexpanded(node_id=node.node_id, production_id=rule.id, reason="depth_limit"))
                    continue
                c = by_id.get(rule.id)
                if c is None:
                    unexpanded.append(Unexpanded(node_id=node.node_id, production_id=rule.id, reason="count_not_evidenced"))
                    continue
                for rep in range(c.count):
                    for pos, sym in enumerate(rule.successor):
                        if len(nodes) >= MAX_NODES:
                            raise ValueError(f"growth exceeds {MAX_NODES} nodes; lower counts or depth")
                        link = link_for(rule.predecessor, sym)
                        child = PossibleNode(node_id=f"{derivation_id}:{len(nodes)}", path=f"{node.path}.{rule.id}.{rep}.{pos}", symbol=sym,
                                             parent_id=node.node_id, production_id=rule.id, depth=node.depth + 1,
                                             link_status="terminal" if sym == TERMINAL else ("typed_link" if link else "gap"))
                        nodes.append(child)
                        if sym != TERMINAL:
                            nxt.append(child)
        frontier = nxt
    return Derivation(derivation_id=derivation_id, profile_version=profile.profile_version,
                      profile_digest=profile.source_digest, max_depth=max_depth, counts=ordered,
                      nodes=tuple(nodes), unexpanded=tuple(unexpanded), expectations=profile.expectations)


def ladder_moves(derivation: Derivation) -> tuple[LadderMove, ...]:
    """The only ladder moves growth may emit: one grammar_growth ``grow`` per node, landing at possible."""
    return tuple(LadderMove(work_package_id=n.node_id, verb="grow", origin="grammar_growth",
                            derivation_id=derivation.derivation_id) for n in derivation.nodes)


CONTRACTS = (Production, Expectation, ProductionLink, GrammarProfile, GrowthCount, PossibleNode, Unexpanded, Derivation)
