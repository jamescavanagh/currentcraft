"""Reference (oracle) implementation for the HFGT capability graph spec.

Standalone numpy, no toolkit imports, so the developer implementation can be checked against it.
Reads a fixture in the proposed 0.9.9 shape and prints expected outputs as JSON.
Synthetic fixtures prove the translation, never a real project's process.
"""
from __future__ import annotations
import json, sys
import numpy as np

PULL_ONLY, INJECT_ONLY = {"consumes"}, {"produces"}

def key(kind, state, operand_key):
    return f"{kind}:{state}" if operand_key == "kind_state" else kind

def translate(fx):
    """Executions -> capabilities with pull/inject (operand, buffer) sets. Gaps are reported, never guessed."""
    ok = fx.get("operand_key", "kind_state")
    caps, gaps = {}, []
    resources = {b["resource_id"] for e in fx["executions"] for b in e["executed_by"]}
    objects = {i["object_id"] for e in fx["executions"] for i in e["incidence"]}
    if resources & objects:
        raise ValueError(f"resource ids cannot be object ids: {sorted(resources & objects)}")
    for e in fx["executions"]:
        if e.get("epistemic_status", "computed") != "computed":
            gaps.append((e["execution_id"], "not computed: never existence evidence")); continue
        if not e["executed_by"]:
            gaps.append((e["execution_id"], "executor unknown")); continue
        fc = set(e["process"]["function_classes"])
        rows = []  # (process_id, pulls, injects, nonconsuming)
        if fc & {"transform", "control"}:
            y = e.get("at_buffer")
            if y is None:
                gaps.append((e["execution_id"], "transform/control without at_buffer")); continue
            cls = "transform" if "transform" in fc else "control"
            pulls, injects, nc, bad = set(), set(), False, False
            for i in e["incidence"]:
                eff, sb, sa = i["effect"], i.get("state_before"), i.get("state_after")
                if eff != "produces":
                    if sb is None and ok == "kind_state":
                        gaps.append((e["execution_id"], f"{i['object_id']}: no state_before")); bad = True; continue
                    pulls.add((key(i["object_kind"], sb, ok), y))
                if eff in ("produces", "revises") or (eff == "checks" and sa):
                    injects.add((key(i["object_kind"], sa, ok), y))
                if eff == "reads" or (eff == "checks" and not sa):   # non-consuming: identity
                    injects.add((key(i["object_kind"], sb, ok), y)); nc = True
            if bad:
                continue  # no partial capabilities: the whole execution is a gap
            rows.append((f"{cls}:{e['process']['code']}@{y}", pulls, injects, nc))
        elif fc & {"hold", "transport"}:
            for i in e["incidence"]:
                if i["effect"] == "holds":
                    o = d = e.get("at_buffer")
                elif i["effect"] == "transfers":
                    o, d = i.get("origin_buffer"), i.get("destination_buffer")
                else:
                    continue
                if o is None or d is None:
                    gaps.append((e["execution_id"], f"{i['object_id']}: missing buffer")); continue
                op_in = key(i["object_kind"], i.get("state_before"), ok)
                rows.append((f"refined:hold({op_in}):{o}->{d}", {(op_in, o)},
                             {(key(i["object_kind"], i["state_after"], ok), d)}, False))
        else:
            gaps.append((e["execution_id"], f"no HFGT class for {sorted(fc)} (exchange needs an SME mapping)")); continue
        for pid, pulls, injects, nc in rows:
            for b in e["executed_by"]:
                c = caps.setdefault((pid, b["resource_id"]), {"pulls": set(), "injects": set(), "evidence": 0,
                                                             "evidenced": False, "nonconsuming": False,
                                                             "stages": set(), "fc": pid.split(":")[0]})
                c["pulls"] |= pulls; c["injects"] |= injects; c["evidence"] += 1
                c["evidenced"] |= b.get("evidence_ref") is not None; c["nonconsuming"] |= nc; c["stages"].add(e["stage"])
    return caps, gaps

def build(caps, constraints=(), mode="drop"):
    blocked = {(k["capability"]["process"], k["capability"]["resource_id"]) for k in constraints}
    unknown = blocked - set(caps)
    if unknown:
        raise ValueError(f"constraint names a capability that does not exist: {sorted(unknown)}")
    ES = sorted(c for c in caps if mode == "mask" or c not in blocked)
    L = sorted({op for c in ES for op, _ in caps[c]["pulls"] | caps[c]["injects"]})
    B = sorted({y for c in ES for _, y in caps[c]["pulls"] | caps[c]["injects"]})
    place = {(l, y): i for i, (l, y) in enumerate((l, y) for l in L for y in B)}  # row = sigma(B)*l + y
    Mm = np.zeros((len(place), len(ES)), np.int64); Mp = np.zeros_like(Mm)
    for k, c in enumerate(ES):
        for p in caps[c]["pulls"]:
            Mm[place[p], k] = 1
        for p in caps[c]["injects"]:
            Mp[place[p], k] = 1
    avail = np.array([0 if c in blocked else 1 for c in ES])
    W = Mp.T @ Mm                                   # witnesses per (a, b): real product
    A = (W > 0).astype(np.int64)                    # Boolean product
    A = A * avail[:, None] * avail[None, :]         # K_S: an unavailable capability neither feeds nor follows
    selfseq = np.diag(A).copy(); np.fill_diagonal(A, 0)
    return ES, L, B, Mm, Mp, W, A, avail, selfseq

def five_rule_oracle(caps, ES):
    """Paper section 'system sequence constraints': (I or II or III or IV) and V, with buffers standing in
    for transformation resources (the documented who-vs-where deviation)."""
    def inbuf(c):  return {y for _, y in caps[c]["pulls"]}
    def outbuf(c): return {y for _, y in caps[c]["injects"]}
    def ins(c):  return {l for l, _ in caps[c]["pulls"]}
    def outs(c): return {l for l, _ in caps[c]["injects"]}
    n = len(ES); A = np.zeros((n, n), np.int64)
    for a in range(n):
        for b in range(n):
            ca, cb = ES[a], ES[b]
            ta, tb = caps[ca]["fc"] != "refined", caps[cb]["fc"] != "refined"
            ya, yb = outbuf(ca), inbuf(cb)
            I = ta and tb and ya == yb
            II = ta and not tb and ya == yb
            III = (not ta) and tb and ya == yb
            IV = (not ta) and (not tb) and ya == yb
            V = bool(outs(ca) & ins(cb))
            A[a, b] = int((I or II or III or IV) and V)
    np.fill_diagonal(A, 0)
    return A

def reach(A, src, dst):
    seen, fr = {src}, [src]
    while fr:
        nx = [j for i in fr for j in np.nonzero(A[i])[0] if j not in seen]
        seen |= set(nx); fr = nx
    return dst in seen

def run(fx):
    caps, gaps = translate(fx)
    term = set(fx.get("terminal_operands", []))
    out = {"fixture": fx["fixture"], "synthetic": fx.get("synthetic", True), "gaps": gaps, "scenarios": []}
    for sc in fx["scenarios"]:
        for mode in ("drop", "mask"):
            ES, L, B, Mm, Mp, W, A, avail, selfseq = build(caps, sc["constraints"], mode)
            oracle = five_rule_oracle(caps, ES) * avail[:, None] * avail[None, :]
            idx = {c: i for i, c in enumerate(ES)}
            src = [i for i, c in enumerate(ES) if any(l == "equipment_kit:received" and y == "warehouse" for l, y in caps[c]["pulls"])]
            dst = [i for i, c in enumerate(ES) if any(l in term for l, _ in caps[c]["injects"])]
            dead = [f"{ES[i][0]} by {ES[i][1]}" for i in range(len(ES))
                    if avail[i] and A[i].sum() == 0 and not ({l for l, _ in caps[ES[i]]["injects"]} & term)]
            out["scenarios"].append({
                "scenario": sc["name"], "mode": mode,
                "dof_s": int(avail.sum()), "nodes": len(ES), "dof_rho": int(A.sum()),
                "operands": L, "buffers": B,
                "boolean_equals_real": bool(((W > 0).astype(int) == np.minimum(W, 1)).all() and W.max() <= 1),
                "matches_five_rule_oracle": bool((oracle == A).all()),
                "terminal_reachable": (lambda r: "reachable" if r else ("unknown: translation gaps" if gaps else
                                       ("blocked: constraints" if sc["constraints"] else "unreachable")))(
                                       bool(any(reach(A, s, d) for s in src for d in dst)) if src and dst else False),
                "dead_ends": dead,
                "edges": sorted(f"{ES[a][0]} by {ES[a][1]} -> {ES[b][0]} by {ES[b][1]}" for a, b in zip(*np.nonzero(A))),
            })
    return out

if __name__ == "__main__":
    fx = json.load(open(sys.argv[1]))
    print(json.dumps(run(fx), indent=2))
