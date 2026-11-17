"""0.9.9: simulation request digests and tensor row order do not depend on input node order (harness row M07)."""
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from app.application.simulation import contracts as C  # noqa: E402
from app.infrastructure.tensors.wiring import build_numpy_simulation  # noqa: E402


def nodes(seed=914, n=7):
    rng = random.Random(seed)
    return [C.InteractionNode(id=f"v{i}", x=rng.uniform(-1, 1), y=rng.uniform(-1, 1), strength=rng.uniform(-0.6, 0.6)) for i in range(n)]


class NodeOrder(unittest.TestCase):
    def test_shuffled_nodes_give_the_same_digest_and_results(self):
        base = nodes(3, 7)  # saddle curve (3, 4, 4, 2, 2): two collision events, so event parity is really tested
        shuffled = base[:]
        random.Random(1).shuffle(shuffled)
        sweep = C.InflowSweep(values=(0.0, 0.05, 0.1, 0.2, 0.3))
        a = C.NodeInteractionRequest(frame_id="m07", nodes=tuple(base), inflow=sweep, grid=None)
        b = C.NodeInteractionRequest(frame_id="m07", nodes=tuple(shuffled), inflow=sweep, grid=None)
        self.assertEqual(a.digest(), b.digest())
        self.assertEqual([n.id for n in a.nodes], sorted(n.id for n in base))
        service, store, _ = build_numpy_simulation()
        ra, rb = service.interactions.simulate(a), service.interactions.simulate(b)
        self.assertEqual(ra.request_digest, rb.request_digest)
        self.assertEqual(ra.saddle_curve, rb.saddle_curve)
        self.assertEqual(len(ra.events), 2)
        self.assertEqual([e.model_dump() for e in ra.events], [e.model_dump() for e in rb.events])
        self.assertEqual([s.model_dump() for s in ra.slices], [s.model_dump() for s in rb.slices])
        self.assertTrue((store.get(ra.coupling) == store.get(rb.coupling)).all())

    def test_changing_one_strength_changes_the_digest(self):
        base = nodes()
        moved = base[:]
        moved[3] = moved[3].model_copy(update={"strength": moved[3].strength + 0.01})
        sweep = C.InflowSweep(values=(0.1,))
        self.assertNotEqual(C.NodeInteractionRequest(frame_id="m07", nodes=tuple(base), inflow=sweep).digest(),
                            C.NodeInteractionRequest(frame_id="m07", nodes=tuple(moved), inflow=sweep).digest())


if __name__ == "__main__":
    unittest.main()
