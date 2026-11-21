import itertools
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pydantic import ValidationError  # noqa: E402

from app.application.ladder import (  # noqa: E402
    LADDER_SCHEMA, TRANSITIONS, LadderMove, LadderViolation, ReadinessReading, apply_move, replay,
)

WP = "wp-synthetic-1"


def grow(wp=WP):
    return LadderMove(work_package_id=wp, verb="grow", origin="grammar_growth", derivation_id="drv-1")


def hil(verb, wp=WP, **kw):
    return LadderMove(work_package_id=wp, verb=verb, origin="hil", label_event_id=f"lbl-{verb}", **kw)


def ready_reading(blocking=0, status="computed"):
    return ReadinessReading(evaluation_id="ev-1", criteria_evaluated=4, blocking=blocking, epistemic_status=status)


def release_to_executable(**kw):
    base = dict(authority_ref="auth-1", authority_scope="release", verification_evidence_ids=("ev-a",),
                epistemic_status="computed")
    base.update(kw)
    return hil("release", **base)


class HappyPath(unittest.TestCase):
    def test_full_climb(self):
        moves = [grow(), hil("release"), hil("release", readiness=ready_reading()), release_to_executable()]
        self.assertEqual(replay(moves), {WP: "executable"})

    def test_schema_prefix(self):
        self.assertEqual(LADDER_SCHEMA, "currentcraft-ladder/v1")
        self.assertEqual(grow().schema_version, LADDER_SCHEMA)

    def test_hold_never_moves(self):
        for rung in ("possible", "conditional", "ready", "executable"):
            self.assertEqual(apply_move(rung, hil("hold")), rung)

    def test_rework_can_reenter_at_possible(self):
        moves = [grow(), hil("return", disposition="rework", reason="scope changed"), hil("reenter")]
        self.assertEqual(replay(moves), {WP: "possible"})


class GrowthNeverAdvances(unittest.TestCase):
    def test_growth_only_creates(self):
        for rung in ("possible", "conditional", "ready", "executable", "returned"):
            with self.assertRaises(LadderViolation) as cm:
                apply_move(rung, grow())
            self.assertEqual(cm.exception.code, "growth_cannot_advance")

    def test_growth_cannot_come_from_a_gate(self):
        with self.assertRaises(ValidationError):
            LadderMove(work_package_id=WP, verb="grow", origin="hil", label_event_id="lbl")

    def test_grammar_growth_cites_derivation(self):
        with self.assertRaises(ValidationError):
            LadderMove(work_package_id=WP, verb="grow", origin="grammar_growth")

    def test_intake_growth_needs_no_derivation(self):
        m = LadderMove(work_package_id=WP, verb="grow", origin="intake")
        self.assertEqual(apply_move(None, m), "possible")


class HilOnly(unittest.TestCase):
    def test_non_hil_moves_rejected(self):
        for verb in ("hold", "release", "reenter"):
            for origin in ("grammar_growth", "intake"):
                with self.assertRaises(ValidationError):
                    LadderMove(work_package_id=WP, verb=verb, origin=origin, derivation_id="d")

    def test_hil_move_needs_label_event(self):
        with self.assertRaises(ValidationError):
            LadderMove(work_package_id=WP, verb="release", origin="hil")

    def test_cannot_move_uncreated_work(self):
        with self.assertRaises(LadderViolation) as cm:
            apply_move(None, hil("release"))
        self.assertEqual(cm.exception.code, "not_created")


class Readiness(unittest.TestCase):
    def test_ready_needs_reading(self):
        with self.assertRaises(LadderViolation) as cm:
            apply_move("conditional", hil("release"))
        self.assertEqual(cm.exception.code, "readiness_missing")

    def test_ready_blocked(self):
        with self.assertRaises(LadderViolation) as cm:
            apply_move("conditional", hil("release", readiness=ready_reading(blocking=1)))
        self.assertEqual(cm.exception.code, "readiness_blocked")

    def test_simulated_readiness_cannot_reach_ready(self):
        with self.assertRaises(LadderViolation) as cm:
            apply_move("conditional", hil("release", readiness=ready_reading(status="simulated")))
        self.assertEqual(cm.exception.code, "readiness_not_computed")

    def test_blocking_bounded(self):
        with self.assertRaises(ValidationError):
            ReadinessReading(evaluation_id="e", criteria_evaluated=1, blocking=2, epistemic_status="computed")

    def test_readiness_alone_never_reaches_executable(self):
        with self.assertRaises(LadderViolation) as cm:
            apply_move("ready", hil("release", readiness=ready_reading()))
        self.assertEqual(cm.exception.code, "authority_missing")


class Executable(unittest.TestCase):
    def test_needs_release_scope_authority(self):
        with self.assertRaises(LadderViolation) as cm:
            apply_move("ready", release_to_executable(authority_scope=None))
        self.assertEqual(cm.exception.code, "authority_missing")

    def test_needs_verification(self):
        with self.assertRaises(LadderViolation) as cm:
            apply_move("ready", release_to_executable(verification_evidence_ids=()))
        self.assertEqual(cm.exception.code, "verification_missing")

    def test_simulated_or_unknown_never_executable(self):
        for status in ("simulated", "unknown"):
            with self.assertRaises(LadderViolation) as cm:
                apply_move("ready", release_to_executable(epistemic_status=status))
            self.assertEqual(cm.exception.code, "not_computed")

    def test_nothing_above_executable(self):
        with self.assertRaises(LadderViolation) as cm:
            apply_move("executable", release_to_executable())
        self.assertEqual(cm.exception.code, "no_rung_above")


class NoSkipping(unittest.TestCase):
    def test_only_adjacent_releases(self):
        releases = {k: v for k, v in TRANSITIONS.items() if k[1] == "release"}
        order = ["possible", "conditional", "ready", "executable"]
        for (src, _), dst in releases.items():
            self.assertEqual(order.index(dst), order.index(src) + 1)

    def test_every_rung_reachable_and_returned_reachable_from_all_active(self):
        for rung in ("possible", "conditional", "ready", "executable"):
            self.assertEqual(TRANSITIONS[(rung, "return")], "returned")
            self.assertEqual(TRANSITIONS[(rung, "reject")], "returned")


class Returns(unittest.TestCase):
    def test_return_needs_rework_and_reason(self):
        with self.assertRaises(ValidationError):
            hil("return", disposition="rejected", reason="x")
        with self.assertRaises(ValidationError):
            hil("return", disposition="rework")

    def test_reject_is_terminal(self):
        moves = [grow(), hil("reject", disposition="rejected", reason="out of scope"), hil("reenter")]
        with self.assertRaises(LadderViolation) as cm:
            replay(moves)
        self.assertEqual(cm.exception.code, "rejected_is_terminal")

    def test_disposition_only_on_return_or_reject(self):
        with self.assertRaises(ValidationError):
            hil("hold", disposition="rework")


class Exhaustive(unittest.TestCase):
    def test_no_path_reaches_executable_without_authority(self):
        """Property: across every sequence of up to five non-authority moves, executable is unreachable."""
        moves = [hil("hold"), hil("release"), hil("release", readiness=ready_reading()),
                 hil("return", disposition="rework", reason="r"), hil("reenter")]
        for n in range(1, 6):
            for seq in itertools.product(moves, repeat=n):
                rung = "possible"
                disp = None
                for m in seq:
                    try:
                        rung = apply_move(rung, m, returned_disposition=disp)
                    except LadderViolation:
                        break
                    disp = m.disposition if rung == "returned" else None
                self.assertNotEqual(rung, "executable")


class Layering(unittest.TestCase):
    def test_slice_is_pure_python_and_imports_only_common(self):
        import ast
        heavy = {"numpy", "torch", "scipy", "pandas", "sklearn"}
        files = sorted((ROOT / "src" / "app" / "application" / "ladder").glob("*.py"))
        self.assertTrue(files)
        for f in files:
            tree = ast.parse(f.read_text(encoding="utf-8"))
            mods = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods |= {a.name for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    mods.add(node.module)
            self.assertFalse({m for m in mods if m.split(".")[0] in heavy}, f.name)
            app = {m for m in mods if m.startswith("app.")}
            self.assertFalse(app - {"app.application.common"}, f.name)


if __name__ == "__main__":
    unittest.main()
