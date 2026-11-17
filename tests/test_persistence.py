"""Acceptance tests for docs/architecture/PERSISTENCE.md.

One contract suite runs against every unit-of-work implementation:
- memory: always;
- DuckDB stand-in: when duckdb is installed. Same SQL text as PostgreSQL; proves statements and semantics, NOT compatibility;
- PostgreSQL 18: only when DATAMESH_PG_DSN is set and psycopg 3 is installed. Python unit tests alone do not satisfy
  database compatibility; run this class against a real server before claiming it.
"""
import importlib.util
import os
import sys
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pydantic import BaseModel  # noqa: E402

from app.application.ingest.contracts import DomainObject, Provenance, TypedRelation  # noqa: E402
from app.application.messaging.contracts import make_event  # noqa: E402
from app.application.persistence import (EmbeddingRecord, EmbeddingSpace, InsufficientStock, Reservation,  # noqa: E402
                                         StockPosition, VersionConflict, documents_for, load_aggregate, persist_objects,
                                         relay_outbox, reserve_stock, run_once, save_aggregate, tasks_of)
from app.infrastructure.messaging.memory import InMemoryBroker  # noqa: E402
from app.infrastructure.persistence import (DUCKDB_STANDIN, POSTGRES, build_duckdb_standin, build_memory,  # noqa: E402
                                            dense_literal, migrate, parse_sparse, render_ddl, sparse_literal)
from tests.test_simulation_layering import HEAVY, imports, py_files  # noqa: E402

T0 = datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc)
SHA = "0" * 64
HAS_DUCKDB = importlib.util.find_spec("duckdb") is not None
PG_DSN = os.environ.get("DATAMESH_PG_DSN")
HAS_PSYCOPG = importlib.util.find_spec("psycopg") is not None


def obj(oid, kind="work_item", rels=(), title="", **fields):
    return DomainObject(object_id=oid, kind=kind, title=title, fields=fields,
                        relations=tuple(TypedRelation(type=t, target_id=d, evidence="test") for t, d in rels),
                        provenance=Provenance(platform="file", format="json", source_id=oid.replace(":", "-"), content_sha256=SHA,
                                              adapter="test", adapter_version="0", received_at=T0))


class Money(BaseModel):
    label: str
    amount: Decimal
    hours: Decimal


class PersistenceContract:
    """Mixin: subclasses set self.uow (a unit-of-work factory) in setUp."""

    def make(self):
        raise NotImplementedError

    def setUp(self):
        self.uow = self.make()

    # source occurrences
    def test_put_is_idempotent_and_versions_changes(self):
        a = obj("t:1", title="first")
        r1, r2 = persist_objects(self.uow, [a, a], T0)
        self.assertEqual((r1.version_no, r1.stored, r2.stored), (1, True, False))
        r3, = persist_objects(self.uow, [obj("t:1", title="second")], T0)
        self.assertEqual((r3.version_no, r3.stored), (2, True))
        with self.uow() as u:
            self.assertEqual([o.title for o in u.objects.history("t:1")], ["first", "second"])
            self.assertEqual(u.objects.get("t:1").title, "second")
            self.assertIsNone(u.objects.get("t:none"))
            self.assertEqual(u.objects.get("t:1"), obj("t:1", title="second"))

    def test_edges_follow_the_current_version_only(self):
        persist_objects(self.uow, [obj("a", rels=[("blocks", "b"), ("blocks", "c")]), obj("b", rels=[("blocks", "d")])], T0)
        persist_objects(self.uow, [obj("a", rels=[("blocks", "c")])], T0)    # a no longer blocks b
        with self.uow() as u:
            self.assertEqual([(e.dst_id, e.src_version) for e in u.graph.edges("a")], [("c", 2)])
            self.assertEqual([e.src_id for e in u.graph.edges("c", "in")], ["a"])
            self.assertEqual(u.graph.edges("b", "in"), ())
            walk = u.graph.traverse("b", ("blocks",), 3)
            self.assertEqual([(e.dst_id, e.depth) for e in walk], [("d", 1)])
            with self.assertRaises(ValueError):
                u.graph.traverse("a", max_depth=99)

    def test_traverse_reports_shortest_depth_and_survives_cycles(self):
        persist_objects(self.uow, [obj("a", rels=[("dep", "b"), ("dep", "c")]), obj("b", rels=[("dep", "c")]),
                                   obj("c", rels=[("dep", "a")])], T0)
        with self.uow() as u:
            got = {(e.src_id, e.dst_id): e.depth for e in u.graph.traverse("a", ("dep",), 4)}
        self.assertEqual(got, {("a", "b"): 1, ("a", "c"): 1, ("b", "c"): 2, ("c", "a"): 2})

    def test_by_kind_and_related(self):
        persist_objects(self.uow, [obj("p", "project_reference"), obj("x", "wbs_task", rels=[("child_of", "p")]),
                                   obj("y", "note", rels=[("child_of", "p")])], T0)
        with self.uow() as u:
            self.assertEqual([o.object_id for o in u.objects.by_kind("wbs_task")], ["x"])
            self.assertEqual([o.object_id for o in u.objects.related("p", "child_of", "in")], ["x", "y"])
            self.assertEqual([o.object_id for o in u.objects.related("p", "child_of", "in", kind="note")], ["y"])
            self.assertEqual([o.object_id for o in u.objects.related("x", direction="out")], ["p"])

    def test_project_document_and_tasks_of_current_revision(self):
        ref, doc = "erp:project:PRJ-1", "file:xlsx:project_document:d1"
        r1, r2 = "file:xlsx:rev:r1", "file:xlsx:rev:r2"
        persist_objects(self.uow, [
            obj(ref, "project_reference"),
            obj(doc, "project_document", rels=[("document_of", ref), ("current_revision", r1)]),
            obj(r1, "workbook_revision", rels=[("revision_of", doc)]),
            obj("task:r1:a", "wbs_task", rels=[("extracted_from", doc), ("in_revision", r1)]),
        ], T0)
        self.assertEqual([d.object_id for d in documents_for(self.uow, ref)], [doc])
        self.assertEqual([t.object_id for t in tasks_of(self.uow, doc)], ["task:r1:a"])
        persist_objects(self.uow, [   # Round 2 arrives: same document identity, new revision
            obj(doc, "project_document", rels=[("document_of", ref), ("current_revision", r2)]),
            obj(r2, "workbook_revision", rels=[("revision_of", doc)]),
            obj("task:r2:a", "wbs_task", rels=[("extracted_from", doc), ("in_revision", r2)]),
            obj("task:r2:b", "wbs_task", rels=[("extracted_from", doc), ("in_revision", r2)]),
        ], T0)
        self.assertEqual([t.object_id for t in tasks_of(self.uow, doc)], ["task:r2:a", "task:r2:b"])
        self.assertEqual(len(tasks_of(self.uow, doc, all_revisions=True)), 3)

    def test_real_pew_pipeline_output_persists(self):
        from tests.test_xlsx_workbook import by, run, workbook
        objs = run(workbook())[2].objects
        persist_objects(self.uow, objs, T0)
        again = persist_objects(self.uow, objs, T0)
        self.assertFalse(any(r.stored for r in again))
        doc, = by(objs, "project_document")
        ref, = by(objs, "project_reference")
        self.assertEqual([d.object_id for d in documents_for(self.uow, ref.object_id)], [doc.object_id])
        self.assertEqual({t.object_id for t in tasks_of(self.uow, doc.object_id)}, {t.object_id for t in by(objs, "wbs_task")})
        with self.uow() as u:
            for t in by(objs, "wbs_task")[:5]:
                self.assertEqual(u.objects.get(t.object_id), t)

    # aggregates
    def test_aggregate_compare_and_swap_and_exact_decimals(self):
        aid = uuid.uuid4()
        m = Money(label="Install", amount=Decimal("1234567890.123456789012"), hours=Decimal("0.1"))
        r1 = save_aggregate(self.uow, "work_package", aid, m, None, T0, command_id="c1")
        self.assertEqual(r1.version, 1)
        got, v = load_aggregate(self.uow, "work_package", aid, Money)
        self.assertEqual((got, v), (m, 1))
        self.assertEqual(got.amount + got.hours * 2, Decimal("1234567890.323456789012"))
        with self.assertRaises(VersionConflict):
            save_aggregate(self.uow, "work_package", aid, m, None, T0)              # create twice
        r2 = save_aggregate(self.uow, "work_package", aid, m.model_copy(update={"label": "B"}), 1, T0)
        self.assertEqual(r2.version, 2)
        with self.assertRaises(VersionConflict):
            save_aggregate(self.uow, "work_package", aid, m, 1, T0)                 # stale writer loses
        with self.uow() as u:
            self.assertEqual([h.version for h in u.aggregates.history("work_package", aid)], [1, 2])
            self.assertEqual(u.aggregates.get("work_package", aid).recorded_at, T0)
            self.assertIsNone(u.aggregates.get("work_package", uuid.uuid4()))

    # commands
    def test_run_once_applies_a_command_once(self):
        calls = []

        def act(u):
            calls.append(1)
            u.objects.put(obj("made:1"))
            return "made:1"

        a = run_once(self.uow, "cmd-1", "make", T0, act)
        b = run_once(self.uow, "cmd-1", "make", T0 + timedelta(hours=1), act)
        self.assertEqual((len(calls), a, b.recorded_at), (1, b, T0))
        with self.uow() as u:
            self.assertEqual(len(u.objects.history("made:1")), 1)

    def test_failed_command_leaves_nothing(self):
        def boom(u):
            u.objects.put(obj("half:1"))
            raise RuntimeError("fail midway")

        with self.assertRaises(RuntimeError):
            run_once(self.uow, "cmd-x", "make", T0, boom)
        with self.uow() as u:
            self.assertIsNone(u.objects.get("half:1"))
            self.assertIsNone(u.commands.get("cmd-x"))

    # stock
    def _stock(self, qty="10"):
        with self.uow() as u:
            u.stock.put_position(StockPosition(stock_id="stk-1", item_ref="item:cable-cat6", uom="FT", on_hand=Decimal(qty)))
            u.commit()

    def _res(self, qty, cmd):
        return Reservation(reservation_id=uuid.uuid4(), stock_id="stk-1", claimant_ref="wp-1", quantity=Decimal(qty),
                           command_id=cmd, created_at=T0)

    def test_reservations_never_overcommit(self):
        self._stock("10")
        reserve_stock(self.uow, self._res("6.5", "r1"))
        with self.assertRaises(InsufficientStock):
            reserve_stock(self.uow, self._res("3.5000000001", "r2"))
        reserve_stock(self.uow, self._res("3.5", "r3"))
        with self.uow() as u:
            p = u.stock.get_position("stk-1")
            self.assertEqual((p.reserved, p.available), (Decimal("10"), Decimal("0")))
            self.assertEqual(len(u.stock.reservations("stk-1")), 2)
            with self.assertRaises(InsufficientStock):
                u.stock.put_position(StockPosition(stock_id="stk-1", item_ref="item:cable-cat6", uom="FT", on_hand=Decimal("9")))

    def test_competing_reservations_do_not_overcommit(self):
        self._stock("5")
        errors, ok = [], []

        def worker(i):
            try:
                ok.append(reserve_stock(self.uow, self._res("1", f"c{i}")))
            except (InsufficientStock, VersionConflict) as e:
                errors.append(e)

        ts = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        with self.uow() as u:
            p = u.stock.get_position("stk-1")
        self.assertEqual(len(ok), 5)
        self.assertEqual(p.reserved, Decimal("5"))
        self.assertLessEqual(p.reserved, p.on_hand)

    def test_reserve_and_release_are_idempotent(self):
        self._stock("4")
        r = self._res("3", "same-cmd")
        a = reserve_stock(self.uow, r)
        b = reserve_stock(self.uow, r.model_copy(update={"reservation_id": uuid.uuid4()}))   # retried command
        self.assertEqual(a.reservation_id, b.reservation_id)
        with self.uow() as u:
            u.stock.release(a.reservation_id, "rel-1", T0)
            u.stock.release(a.reservation_id, "rel-1", T0)
            u.commit()
        with self.uow() as u:
            self.assertEqual(u.stock.get_position("stk-1").reserved, Decimal("0"))
            self.assertEqual([x.status for x in u.stock.reservations("stk-1", None)], ["released"])

    # embeddings
    def test_embedding_round_trip_with_mask_and_sparse(self):
        sp = EmbeddingSpace(model_name="synthetic-embed", model_version="1", dim=6)
        rec = EmbeddingRecord(object_id="t:1", space=sp, dense=(0.1, -2.5, 3.25e-7, 0.0, 1.0, 7.0),
                              dense_mask=(True, True, True, False, True, True), sparse_indices=(0, 5), sparse_values=(0.5, 1.5),
                              recorded_at=T0)
        with self.uow() as u:
            u.embeddings.put(rec)
            u.embeddings.put(rec)
            u.commit()
        with self.uow() as u:
            got = u.embeddings.get("t:1", sp)
            self.assertIsNone(u.embeddings.get("t:1", sp.model_copy(update={"model_version": "2"})))
            with self.assertRaises(ValueError):
                u.embeddings.get("t:1", sp.model_copy(update={"dim": 7}))
        self.assertEqual(got.dense_mask, rec.dense_mask)
        self.assertEqual(got.sparse_indices, (0, 5))
        for a, b in zip(got.dense + got.sparse_values, rec.dense + rec.sparse_values):
            self.assertLessEqual(abs(a - b), rec.tolerance * max(1.0, abs(b)))

    # outbox
    def test_outbox_is_transactional_and_relay_dedups(self):
        persist_objects(self.uow, [obj("t:1"), obj("t:2")], T0)
        broker = InMemoryBroker()
        self.assertEqual(relay_outbox(self.uow, broker, T0), 2)
        self.assertEqual(relay_outbox(self.uow, broker, T0), 0)
        self.assertEqual(len(broker.log), 2)
        with self.uow() as u:
            ev = make_event(topic="x/y", kind="domain.stored", source="persistence", epistemic_status="computed", occurred_at=T0)
            self.assertTrue(u.outbox.add(ev, T0))
            self.assertFalse(u.outbox.add(ev, T0))
            # no commit: discarded
        with self.uow() as u:
            self.assertEqual(u.outbox.pending(), ())

    def test_uncommitted_work_rolls_back(self):
        with self.uow() as u:
            u.objects.put(obj("gone"))
            u.rollback()
        with self.uow() as u:
            u.objects.put(obj("gone"))
        with self.uow() as u:
            self.assertIsNone(u.objects.get("gone"))

    def test_naive_timestamps_are_refused(self):
        with self.assertRaises(ValueError):
            EmbeddingRecord(object_id="x", space=EmbeddingSpace(model_name="m", model_version="1", dim=1), dense=(1.0,),
                            recorded_at=datetime(2026, 1, 1))


class MemoryContract(PersistenceContract, unittest.TestCase):
    def make(self):
        return build_memory()


@unittest.skipUnless(HAS_DUCKDB, "duckdb not installed")
class DuckDbStandInContract(PersistenceContract, unittest.TestCase):
    def make(self):
        return build_duckdb_standin()

    def test_migrations_are_idempotent(self):
        ex = self.uow.executor()
        try:
            self.assertEqual(migrate(ex), [])
            self.assertEqual([r["version"] for r in ex.rows("SELECT version FROM dm_schema_migrations ORDER BY version")], [1, 2, 3, 4, 5])
        finally:
            self.uow._close(ex.conn)


@unittest.skipUnless(PG_DSN and HAS_PSYCOPG, "set DATAMESH_PG_DSN and install psycopg 3 to run against PostgreSQL 18")
class PostgresContract(PersistenceContract, unittest.TestCase):
    """Runs in a throwaway schema per test; drops it afterwards."""

    def make(self):
        import psycopg
        from app.infrastructure.persistence import SqlUnitOfWorkFactory
        self.schema = "dm_test_" + uuid.uuid4().hex[:12]
        with psycopg.connect(PG_DSN, autocommit=True) as c:
            c.execute(f'CREATE SCHEMA "{self.schema}"')

        def connect():
            c = psycopg.connect(PG_DSN, autocommit=True)
            c.execute(f'SET search_path TO "{self.schema}", public')
            return c

        f = SqlUnitOfWorkFactory(connect, POSTGRES, close=lambda c: c.close())
        f.migrate()
        return f

    def tearDown(self):
        import psycopg
        with psycopg.connect(PG_DSN, autocommit=True) as c:
            c.execute(f'DROP SCHEMA "{self.schema}" CASCADE')

    def test_server_is_postgresql_18_or_later(self):
        ex = self.uow.executor()
        v = int(ex.rows("SHOW server_version_num")[0]["server_version_num"])
        ex.conn.close()
        self.assertGreaterEqual(v, 180000)


class VectorsAndSchema(unittest.TestCase):
    def test_sparse_indices_shift_to_one_based_and_back(self):
        lit = sparse_literal((0, 4), (0.5, -1.25), 5)
        self.assertEqual(lit, "{1:0.5,5:-1.25}/5")
        self.assertEqual(parse_sparse(lit), ((0, 4), (0.5, -1.25), 5))
        for bad in ((5,), (-1,)):
            with self.assertRaises(ValueError):
                sparse_literal(bad, (1.0,), 5)
        with self.assertRaises(ValueError):
            parse_sparse("{0:1.0}/3")
        with self.assertRaises(ValueError):
            dense_literal((float("nan"),))

    def test_postgres_ddl_uses_exact_and_native_types(self):
        ddl = render_ddl(POSTGRES)
        for token in ("NUMERIC(38,12)", "TIMESTAMPTZ", "JSONB", "UUID", "DOUBLE PRECISION[]", "sparsevec",
                      "REFERENCES dm_stock_positions", "CHECK (reserved <= on_hand)"):
            self.assertIn(token, ddl)
        self.assertNotIn("{", ddl.replace("{JSON", ""))
        self.assertNotIn("vector", render_ddl(DUCKDB_STANDIN))
        self.assertNotRegex(ddl, r"(on_hand|reserved|quantity) (REAL|DOUBLE|FLOAT)")

    def test_layering(self):
        drivers = {"psycopg", "psycopg2", "duckdb", "sqlite3", "sqlalchemy", "asyncpg", "json"}
        for f in py_files("application/persistence"):
            mods = {m.split(".")[0] for m in imports(f)}
            self.assertFalse(mods & (drivers | HEAVY), f.name)
            self.assertFalse({m for m in imports(f) if m.startswith("app.infrastructure")}, f.name)
        for f in py_files("infrastructure/persistence"):
            self.assertFalse({m.split(".")[0] for m in imports(f)} & HEAVY, f.name)
        for f in py_files("domain"):
            self.assertFalse({m for m in imports(f) if "persistence" in m}, f.name)


if __name__ == "__main__":
    unittest.main()
