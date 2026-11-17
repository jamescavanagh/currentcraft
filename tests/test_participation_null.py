import itertools
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from app.application.gauge import ParticipationEdge, ScoredPair, StageNullRequest  # noqa: E402
from app.infrastructure.gauge import build_numpy_gauge  # noqa: E402
from app.infrastructure.gauge import participation_kernels as PK  # noqa: E402


def world(signal, glob, seed=0, n_res=40, n_proc=10, size=4, stages=("design", "ordering", "integration"), frac=0.6):
    rng = np.random.default_rng(seed)
    z = rng.normal(size=n_res)
    edges, pairs = [], []
    for s in stages:
        order = np.argsort(z + rng.normal(scale=0.3, size=n_res))
        for p in range(n_proc):
            for r in order[p * size:(p + 1) * size]:
                edges.append(ParticipationEdge(resource_id=f"r{r}", process_id=f"{s}-p{p}", stage=s))
        for a, b in itertools.combinations(range(n_res), 2):
            if rng.random() < frac:
                d = -abs(z[a] - z[b])
                pairs.append(ScoredPair(a=f"r{a}", b=f"r{b}", stage=s, local_score=signal * d + rng.normal(scale=0.3),
                                        global_score=glob * d + rng.normal(scale=0.3)))
    return tuple(edges), tuple(pairs)


class Kernels(unittest.TestCase):
    def test_auc_with_ties(self):
        self.assertEqual(PK.auc(np.array([1.0, 1.0, 0.0, 2.0]), np.array([1, 0, 0, 1]))[0], 0.875)
        self.assertEqual(PK.auc(np.array([1.0, 2.0]), np.array([1, 1])), (0.5, 0.0))

    def test_curveball_preserves_stage_degrees_and_rewires(self):
        e, _ = world(1, 0)
        ss = {}
        for x in e:
            ss.setdefault(x.stage, {}).setdefault(x.resource_id, set()).add(x.process_id)
        rw = PK.curveball(ss, np.random.default_rng(0), 5)

        def degrees(S):
            return {s: (sorted((r, len(v)) for r, v in d.items()),
                        sorted(np.unique([p for v in d.values() for p in v], return_counts=True)[1].tolist())) for s, d in S.items()}

        self.assertEqual(degrees(ss), degrees(rw))
        self.assertGreater(sum(ss[s][r] != rw[s][r] for s in ss for r in ss[s]), 0)
        self.assertTrue(all(p.startswith(s + "-") for s in rw for v in rw[s].values() for p in v))  # no cross-stage edges


class Verdicts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc, cls.store = build_numpy_gauge()

    def run_world(self, **kw):
        e, p = world(**kw)
        return self.svc.participation_null(StageNullRequest(frame_id="test-null", participation=e, pairs=p,
                                                            n_rewires=100, n_bootstrap=200, seed=3))

    def test_local_beats_global(self):
        r = self.run_world(signal=1.0, glob=0.1)
        self.assertEqual(r.verdict, "local_beats_global")
        self.assertGreater(r.diff_ci_low, 0)
        self.assertEqual(self.store.get(r.null_auc).shape, (100, 2))

    def test_equal_scores_give_no_gain(self):
        self.assertEqual(self.run_world(signal=1.0, glob=1.0).verdict, "local_signal_no_gain")

    def test_noise_is_not_above_null(self):
        self.assertEqual(self.run_world(signal=0.0, glob=0.0).verdict, "not_above_null")


if __name__ == "__main__":
    unittest.main()
