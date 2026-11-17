"""The application-layer translation: process-first records -> HFGT capability records. Pure Python, no arrays.

Rules trace to docs/pipelines/HFGT_CAPABILITY_GRAPH.md section 5. Anything that does not translate becomes a
TranslationGap; nothing is guessed.
"""
from __future__ import annotations

from .contracts import CapabilityRecord, HfgtGraphRequest, HfgtTranslation, TranslationGap, TranslationReport

TRANSFORM_LIKE = ("transform", "control")
CARRY_LIKE = ("hold", "transport")


def operand(kind: str | None, state: str | None, key: str) -> str:
    """Operand type L: object kind plus state (default) or kind alone."""
    k = kind or "object"
    return f"{k}:{state}" if key == "kind_state" else k


def translate(req: HfgtGraphRequest) -> HfgtTranslation:
    """
    >>> from app.application.process.contracts import ProcessExecution, ProcessType, ObjectIncidence, CapabilityBinding
    >>> t = ProcessType(code="build", name="Build", function_classes=("transform",))
    >>> e = ProcessExecution(execution_id="x:1", process=t, stage="S", at_buffer="bench",
    ...     incidence=(ObjectIncidence(object_id="kit", object_kind="kit", effect="consumes", state_before="received"),
    ...                ObjectIncidence(object_id="rack", object_kind="rack", effect="produces", state_after="built")),
    ...     executed_by=(CapabilityBinding(resource_id="builder", resource_role="rack-builder"),))
    >>> out = translate(HfgtGraphRequest(frame_id="doc", executions=(e,)))
    >>> [(c.node_id, c.pulls, c.injects) for c in out.capabilities]
    [('transform:build@bench|builder', (('kit:received', 'bench'),), (('rack:built', 'bench'),))]
    """
    key = req.operand_key
    declared = {b.buffer_id for b in req.buffers}
    gaps: list[TranslationGap] = []
    acc: dict[tuple[str, str], dict] = {}
    translated: set[str] = set()

    def gap(ex, reason, obj=None):
        gaps.append(TranslationGap(execution_id=ex.execution_id, object_id=obj, reason=reason))

    def known(ex, y, obj=None):
        if declared and y not in declared:
            gap(ex, f"buffer {y!r} is not declared", obj)
            return False
        return True

    for ex in req.executions:
        if ex.epistemic_status != "computed":
            gap(ex, f"{ex.epistemic_status}: never existence evidence")
            continue
        if not ex.executed_by:
            gap(ex, "executor unknown")
            continue
        fc = set(ex.process.function_classes)
        rows: list[tuple[str, str, set, set, bool]] = []
        if fc & set(TRANSFORM_LIKE):
            y = ex.at_buffer
            if y is None:
                gap(ex, "transform/control without at_buffer")
                continue
            if not known(ex, y):
                continue
            cls = "transform" if "transform" in fc else "control"
            pulls, injects, nc, bad = set(), set(), False, False
            for inc in ex.incidence:
                eff, sb, sa = inc.effect, inc.state_before, inc.state_after
                if eff != "produces":
                    if sb is None and key == "kind_state":
                        gap(ex, "no state_before under operand_key kind_state", inc.object_id)
                        bad = True
                        continue
                    pulls.add((operand(inc.object_kind, sb, key), y))
                if eff in ("produces", "revises") or (eff == "checks" and sa is not None):
                    injects.add((operand(inc.object_kind, sa, key), y))
                if eff == "reads" or (eff == "checks" and sa is None):
                    injects.add((operand(inc.object_kind, sb, key), y))
                    nc = True
            if bad:
                continue
            rows.append((f"{cls}:{ex.process.code}@{y}", cls, pulls, injects, nc))
        elif fc & set(CARRY_LIKE):
            for inc in ex.incidence:
                if inc.effect == "holds":
                    o = d = ex.at_buffer
                elif inc.effect == "transfers":
                    o, d = inc.origin_buffer, inc.destination_buffer
                else:
                    continue
                if o is None or d is None:
                    gap(ex, "missing buffer", inc.object_id)
                    continue
                if not (known(ex, o, inc.object_id) and known(ex, d, inc.object_id)):
                    continue
                if inc.state_before is None and key == "kind_state":
                    gap(ex, "no state_before under operand_key kind_state", inc.object_id)
                    continue
                op_in = operand(inc.object_kind, inc.state_before, key)
                op_out = operand(inc.object_kind, inc.state_after, key)
                rows.append((f"refined:hold({op_in}):{o}->{d}", "hold" if o == d else "transport", {(op_in, o)}, {(op_out, d)}, False))
        else:
            gap(ex, f"no HFGT class for {sorted(fc)} (exchange needs an SME mapping)")
            continue
        for pid, cls, pulls, injects, nc in rows:
            translated.add(ex.execution_id)
            for b in ex.executed_by:
                a = acc.setdefault((pid, b.resource_id), {"cls": cls, "pulls": set(), "injects": set(), "n": 0,
                                                          "ev": False, "nc": False, "stages": set()})
                a["pulls"] |= pulls
                a["injects"] |= injects
                a["n"] += 1
                a["ev"] = a["ev"] or b.evidence_ref is not None
                a["nc"] = a["nc"] or nc
                a["stages"].add(ex.stage)

    caps = tuple(CapabilityRecord(process=p, resource_id=r, capability_class=a["cls"], pulls=tuple(sorted(a["pulls"])),
                                  injects=tuple(sorted(a["injects"])), evidence_count=a["n"], evidenced=a["ev"],
                                  nonconsuming=a["nc"], stages=tuple(sorted(a["stages"])))
                 for (p, r), a in sorted(acc.items(), key=lambda kv: f"{kv[0][0]}|{kv[0][1]}"))
    report = TranslationReport(gaps=tuple(gaps), n_executions=len(req.executions), n_translated=len(translated))
    return HfgtTranslation(capabilities=caps, report=report)


def check_constraints(req: HfgtGraphRequest, translation: HfgtTranslation) -> frozenset[str]:
    """Active constraint node ids. A constraint naming no existing capability is an error, not a no-op."""
    ids = {c.node_id for c in translation.capabilities}
    missing = sorted(k.capability.node_id for k in req.constraints if k.capability.node_id not in ids)
    if missing:
        raise ValueError(f"constraint names a capability that does not exist: {missing}")
    return frozenset(k.capability.node_id for k in req.constraints if k.active(req.as_of))


def layers(translation: HfgtTranslation, scheme: str) -> tuple[str, ...]:
    """Layer id per capability: its input (or output) operand set. Mutually exclusive and exhaustive by construction."""
    side = "pulls" if scheme == "input_operand_set" else "injects"
    out = []
    for c in translation.capabilities:
        ops = sorted({op for op, _ in getattr(c, side)})
        out.append(" + ".join(ops) or "(none)")
    return tuple(out)


def buffer_graph(translation: HfgtTranslation) -> frozenset[tuple[str, str]]:
    """Formal graph A_BS: OR over resources of every transport capability (paper eq. 10-11). Holding in place excluded."""
    return frozenset((c.pulls[0][1], c.injects[0][1]) for c in translation.capabilities
                     if c.capability_class == "transport")


def operand_network(translation: HfgtTranslation) -> frozenset[tuple[str, str, str]]:
    """Operand-indexed flow structure A_LBS (one-to-one holding/operand special case, paper eq. 15-17)."""
    return frozenset((c.pulls[0][0], c.pulls[0][1], c.injects[0][1]) for c in translation.capabilities
                     if c.capability_class == "transport")


__all__ = ["translate", "check_constraints", "layers", "buffer_graph", "operand_network", "operand"]
