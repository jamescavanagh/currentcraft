"""Acceptance tests for docs/architecture/INGESTION.md. Synthetic inputs only."""
import doctest
import io
import json
import sys
import unittest
import zipfile
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from app.application import ingest as IG  # noqa: E402
from app.application.ingest import (ConsumerSpec, DomainObject, IngestConfig, IngestRing, JsonMapping, Provenance,  # noqa: E402
                                    RingFull, TensorPlan)
from app.application.process import (AuthorityRef, CapabilityBinding, ObjectIncidence, ProcessExecution,  # noqa: E402
                                     ProcessType)
from app.application.simulation.tensors import TensorContractError  # noqa: E402
from app.infrastructure.ingest import build_ingest, hash_features, pseudonym, put_raw  # noqa: E402

try:
    import pypdf  # noqa: F401
    HAVE_PDF = True
except ImportError:
    HAVE_PDF = False

WHEN = datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc)
CFG = IngestConfig(pseudonym_salt="synthetic-salt-0123456789")
TASKS = JsonMapping(name="tasks", kind="work_item", id_field="id", title_field="name", text_fields=("description",),
                    numeric_fields={"points": "points"}, scalar_fields={"state": "meta.state"},
                    relation_fields={"blocks": "blocks"}, resource_fields={"assignee": "assignee"},
                    occurred_at_field="updated")

EMAIL = b"""From: Alex Example <alex@example.invalid>
To: Sam Sample <sam@example.invalid>, ops@example.invalid
Subject: Rack elevation review
Date: Thu, 12 Nov 2026 08:00:00 +0000
Message-ID: <m2@example.invalid>
In-Reply-To: <m1@example.invalid>
Content-Type: text/plain; charset=utf-8

Please review the rack elevation before the bench test.
"""


def docx_bytes(paragraphs, title="Site survey", creator="Alex Example"):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f'<w:p><w:r><w:t>{p}</w:t></w:r></w:p>' for p in paragraphs)
    doc = f'<?xml version="1.0"?><w:document xmlns:w="{w}"><w:body>{body}</w:body></w:document>'
    core = ('<?xml version="1.0"?><cp:coreProperties '
            'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/">'
            f'<dc:title>{title}</dc:title><dc:creator>{creator}</dc:creator>'
            '<dcterms:modified>2026-11-10T12:00:00Z</dcterms:modified></cp:coreProperties>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", doc)
        z.writestr("docProps/core.xml", core)
    return buf.getvalue()


def pdf_bytes(text="Commissioning checklist signed"):
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + o + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
    return out.getvalue()


def task(i, name, blocks=(), points=None, **extra):
    body = {"id": f"t{i}", "name": name, "description": "rack wire bench", "blocks": list(blocks),
            "assignee": "sam@example.invalid", "updated": "2026-11-12T08:00:00Z", "meta": {"state": "open"}}
    if points is not None:
        body["points"] = points
    body.update(extra)
    return body


def pipe_with(capacity=100, subscriptions=("raw/#",), mappings=(TASKS,)):
    return build_ingest(CFG, mappings=mappings, capacity=capacity, subscriptions=subscriptions)


def send_task(pipe, i, name, platform="tracker", when=WHEN, **kw):
    return pipe.receive(put_raw(pipe, platform=platform, fmt="json", source_id=f"t{i}", received_at=when,
                                json_body=task(i, name, **kw), mapping="tasks"))


def peek(pipe, n=100):
    """Objects currently on the ring, via a throwaway consumer."""
    pipe.ring.register("_peek")
    return [e.object for e in pipe.ring.poll("_peek", n)]


def obj(oid, kind="work_item", text="", relations=()):
    return DomainObject(object_id=oid, kind=kind, title=oid, text=text, relations=relations,
                        provenance=Provenance(platform="p", format="text", source_id=oid, content_sha256="0" * 64,
                                              adapter="t", adapter_version="1", received_at=WHEN))


class Topics(unittest.TestCase):
    def test_raw_topic_is_platform_format_source(self):
        pipe = pipe_with()
        env = send_task(pipe, 0, "Pull wire list")
        self.assertEqual(env.topic, "raw/tracker/json/t0")

    def test_hierarchical_subscriptions_select_platform_or_format(self):
        by_platform = pipe_with(subscriptions=("raw/sharepoint/#",))
        send_task(by_platform, 0, "Pull wire list", platform="tracker")
        send_task(by_platform, 1, "Bench test rack", platform="sharepoint")
        self.assertEqual([e.topic for e in by_platform.broker.replay("domain/#")], ["domain/work_item/sharepoint:t1"])
        by_format = pipe_with(subscriptions=("raw/+/text/#",))
        send_task(by_format, 0, "Pull wire list")
        by_format.receive(put_raw(by_format, platform="file", fmt="text", source_id="n1", received_at=WHEN,
                                  data=b"Site notes\nramp access is narrow"))
        self.assertEqual([e.topic.split("/")[1] for e in by_format.broker.replay("domain/#")], ["text"])

    def test_overlapping_subscriptions_process_once(self):
        pipe = pipe_with(subscriptions=("raw/#", "raw/tracker/#"))
        send_task(pipe, 0, "Pull wire list")
        self.assertEqual(len(pipe.ring), 1)
        self.assertEqual(len(pipe.broker.replay("domain/#")), 1)

    def test_content_must_be_in_the_blob_store(self):
        pipe, other = pipe_with(), pipe_with()
        raw = put_raw(other, platform="file", fmt="text", source_id="n", received_at=WHEN, data=b"hello world")
        with self.assertRaisesRegex(ValueError, "blob store"):
            pipe.receive(raw)


class Adapters(unittest.TestCase):
    def test_json_mapping(self):
        pipe = pipe_with()
        send_task(pipe, 0, "Pull wire list", blocks=["t2"], points=3)
        (o,) = peek(pipe)
        self.assertEqual((o.object_id, o.kind, o.title), ("tracker:t0", "work_item", "Pull wire list"))
        self.assertEqual(o.fields, {"points": 3, "state": "open"})
        self.assertEqual([(r.type, r.target_id) for r in o.relations], [("blocks", "tracker:t2")])
        self.assertEqual(o.occurred_at, WHEN)
        self.assertEqual(o.resources[0].role, "assignee")
        self.assertEqual(o.provenance.adapter, "json")

    def test_email_pseudonymises_people_and_links_replies(self):
        pipe = pipe_with()
        pipe.receive(put_raw(pipe, platform="outlook", fmt="email", source_id="m2", received_at=WHEN, data=EMAIL))
        (o,) = peek(pipe)
        self.assertEqual((o.kind, o.title), ("email_message", "Rack elevation review"))
        self.assertIn("rack elevation", o.text)
        self.assertEqual(sorted(r.role for r in o.resources), ["recipient", "recipient", "sender"])
        self.assertEqual(o.resources[0].token, pseudonym(CFG, "ALEX@example.invalid "))
        self.assertEqual(o.relations[0].type, "reply_to")
        self.assertEqual(o.occurred_at, WHEN)
        dumped = o.model_dump_json()
        for leak in ("alex@", "sam@", "ops@", "Alex Example", "Sam Sample"):
            self.assertNotIn(leak, dumped)

    def test_pseudonym_depends_on_salt(self):
        other = IngestConfig(pseudonym_salt="another-salt-9876543210")
        self.assertNotEqual(pseudonym(CFG, "a@example.invalid"), pseudonym(other, "a@example.invalid"))
        self.assertRegex(pseudonym(CFG, "a@example.invalid"), r"^res-[0-9a-f]{16}$")

    def test_docx(self):
        pipe = pipe_with()
        pipe.receive(put_raw(pipe, platform="sharepoint", fmt="docx", source_id="d1", received_at=WHEN,
                             data=docx_bytes(["Ceiling height 3.2 m", "Power at rack location"])))
        (o,) = peek(pipe)
        self.assertEqual((o.kind, o.title, o.fields["paragraphs"]), ("document", "Site survey", 2))
        self.assertIn("Power at rack", o.text)
        self.assertEqual(o.resources[0].role, "author")
        self.assertNotIn("Alex", o.model_dump_json())
        self.assertEqual(o.occurred_at, datetime(2026, 11, 10, 12, tzinfo=timezone.utc))

    @unittest.skipUnless(HAVE_PDF, "optional pdf extra (pypdf) not installed")
    def test_pdf(self):
        pipe = pipe_with()
        pipe.receive(put_raw(pipe, platform="sharepoint", fmt="pdf", source_id="p1", received_at=WHEN, data=pdf_bytes()))
        self.assertEqual(pipe.rejections, [])
        (o,) = peek(pipe)
        self.assertEqual((o.kind, o.fields["pages"], o.fields["text_extracted"]), ("document", 1, True))
        self.assertIn("Commissioning", o.text)

    def test_data_contract_process_execution(self):
        gate = ProcessType(code="gate", name="Readiness gate", function_classes=("control",))
        pe = ProcessExecution(execution_id="demo:gate:1", process=gate, stage="S1",
                              incidence=(ObjectIncidence(object_id="o1", effect="checks", state_after="released"),
                                         ObjectIncidence(object_id="ev", effect="reads")),
                              executed_by=(CapabilityBinding(resource_id="person-7", resource_role="approver"),),
                              decision="release", verification_evidence=("ev",),
                              authority=AuthorityRef(holder_role="approver", scope="release"), occurred_at=WHEN)
        pipe = pipe_with()
        pipe.receive(put_raw(pipe, platform="erp", fmt="data_contract", source_id="pe1", received_at=WHEN,
                             data=pe.model_dump_json().encode(), contract_name="ProcessExecution"))
        (o,) = peek(pipe)
        self.assertEqual((o.kind, o.fields["decision"], o.fields["objects"]), ("process_execution", "release", 2))
        self.assertEqual(sorted(r.type for r in o.relations), ["checks", "reads"])
        self.assertEqual(o.resources[0].role_label, "approver")
        self.assertNotIn("person-7", o.model_dump_json())

    def test_same_bytes_same_ids(self):
        a, b = pipe_with(), pipe_with()
        for p in (a, b):
            p.receive(put_raw(p, platform="outlook", fmt="email", source_id="m2", received_at=WHEN, data=EMAIL))
        (oa,), (ob,) = peek(a), peek(b)
        self.assertEqual((oa.object_id, oa.digest()), (ob.object_id, ob.digest()))


class Quarantine(unittest.TestCase):
    CASES = [
        ("json", {"json_body": {"name": "no id"}, "mapping": "tasks"}, "natural key"),
        ("json", {"json_body": {"id": "t9", "points": "lots"}, "mapping": "tasks"}, "finite number"),
        ("json", {"json_body": {"id": "t9"}, "mapping": "nope"}, "unknown mapping"),
        ("json", {"data": b"{not json", "mapping": "tasks"}, "JSONDecodeError"),
        ("email", {"data": b"\n\njust a body"}, "From or Subject"),
        ("docx", {"data": b"PK not a zip"}, "BadZipFile"),
        ("text", {"data": b"   "}, "empty"),
        ("data_contract", {"data": b'{"execution_id": "x"}', "contract_name": "ProcessExecution"}, "invalid at"),
        ("data_contract", {"data": b"{}", "contract_name": "Unknown"}, "unregistered"),
    ]

    def test_malformed_input_is_quarantined_never_partial(self):
        for fmt, kw, reason in self.CASES:
            with self.subTest(fmt=fmt, reason=reason):
                pipe = pipe_with()
                env = pipe.receive(put_raw(pipe, platform="file", fmt=fmt, source_id="bad", received_at=WHEN, **kw))
                self.assertEqual(len(pipe.ring), 0)
                (r,) = pipe.rejections
                self.assertIn(reason, r.reason)
                (q,) = pipe.broker.replay("quarantine/#")
                self.assertEqual((q.topic, q.causation_id), (f"quarantine/file/{fmt}/bad", env.event_id))
                self.assertEqual(tuple(pipe.broker.replay("domain/#")), ())

    def test_pdf_without_extra_is_quarantined(self):
        pipe = pipe_with()
        with mock.patch.dict(sys.modules, {"pypdf": None}):
            pipe.receive(put_raw(pipe, platform="file", fmt="pdf", source_id="p", received_at=WHEN, data=pdf_bytes()))
        self.assertIn("optional 'pdf' extra", pipe.rejections[0].reason)


class Ring(unittest.TestCase):
    def test_full_ring_with_uncommitted_oldest_raises(self):
        r = IngestRing(2)
        r.register("gnn")
        r.append(obj("a")); r.append(obj("b"))
        with self.assertRaises(RingFull):
            r.append(obj("c"))
        r.commit("gnn", 0)
        self.assertEqual(r.append(obj("c")), 2)
        self.assertEqual([e.object.object_id for e in r.poll("gnn", 10)], ["b", "c"])

    def test_without_consumers_nothing_is_dropped(self):
        r = IngestRing(1)
        r.append(obj("a"))
        with self.assertRaises(RingFull):
            r.append(obj("b"))

    def test_uncommitted_entries_are_redelivered(self):
        r = IngestRing(10)
        r.register("gnn")
        for k in "abc":
            r.append(obj(k))
        first = r.poll("gnn", 2)
        self.assertEqual(r.poll("gnn", 2), first)
        r.commit("gnn", first[-1].offset)
        self.assertEqual([e.object.object_id for e in r.poll("gnn", 2)], ["c"])

    def test_identical_reappend_is_noop_and_new_version_appends(self):
        r = IngestRing(10)
        self.assertEqual(r.append(obj("a")), 0)
        self.assertIsNone(r.append(obj("a")))
        self.assertEqual(r.append(obj("a", text="changed")), 1)

    def test_lag_and_kind_filters(self):
        r = IngestRing(4)
        r.register("gnn", ("work_item",))
        r.register("all")
        r.append(obj("a")); r.append(obj("m", kind="email_message")); r.append(obj("b"))
        self.assertEqual((r.lag("gnn"), r.lag("all")), (2, 3))
        r.commit("gnn", r.poll("gnn", 10)[-1].offset)
        r.commit("all", 2)
        self.assertEqual((r.lag("gnn"), r.lag("all"), r.trim(), len(r)), (0, 0, 3, 0))

    def test_filtered_consumer_never_pins_other_kinds(self):
        r = IngestRing(2)
        r.register("gnn", ("work_item",))
        for k in range(5):
            r.append(obj(f"m{k}", kind="email_message"))
        self.assertEqual(r.lag("gnn"), 0)
        self.assertLessEqual(len(r), 2)

    def test_commit_past_head_is_refused(self):
        r = IngestRing(2)
        r.register("x")
        with self.assertRaises(ValueError):
            r.commit("x", 0)


class Pipeline(unittest.TestCase):
    def test_reingest_identical_bytes_later_is_noop(self):
        pipe = pipe_with()
        send_task(pipe, 0, "Pull wire list")
        send_task(pipe, 0, "Pull wire list", when=WHEN + timedelta(hours=3))
        self.assertEqual(len(pipe.ring), 1)
        send_task(pipe, 0, "Pull wire list (rev B)", when=WHEN + timedelta(hours=4))
        self.assertEqual(len(pipe.ring), 2)
        self.assertEqual(len(pipe.broker.replay("domain/#")), 2)

    def test_backpressure_defers_and_retries_in_order(self):
        pipe = pipe_with(capacity=2)
        svc = pipe.tensors(ConsumerSpec(name="gnn", plan=TensorPlan(name="gnn", text_dim=32), batch_size=1))
        send_task(pipe, 0, "a one"); send_task(pipe, 1, "b two")
        with self.assertRaises(RingFull):
            send_task(pipe, 2, "c three")
        with self.assertRaises(RingFull):   # later intake queues behind the deferred item
            send_task(pipe, 3, "d four")
        self.assertEqual(len(pipe.deferred), 2)
        self.assertEqual(pipe.broker.dead_letters, [])
        svc.next_batch("gnn")
        self.assertEqual(pipe.retry_deferred(), 1)
        svc.next_batch("gnn")
        self.assertEqual(pipe.retry_deferred(), 1)
        ids = [e.payload["object_id"] for e in pipe.broker.replay("domain/#")]
        self.assertEqual(ids, ["tracker:t0", "tracker:t1", "tracker:t2", "tracker:t3"])

    def test_failed_build_leaves_batch_uncommitted(self):
        pipe = pipe_with()
        send_task(pipe, 0, "Pull wire list")
        svc = pipe.tensors(ConsumerSpec(name="gnn", plan=TensorPlan(name="gnn", text_dim=32)))
        original = pipe.tensorizer.build
        pipe.tensorizer.build = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
        with self.assertRaises(RuntimeError):
            svc.next_batch("gnn")
        pipe.tensorizer.build = original
        self.assertEqual(pipe.ring.lag("gnn"), 1)
        self.assertIsNotNone(svc.next_batch("gnn"))
        self.assertEqual(pipe.ring.lag("gnn"), 0)
        self.assertIsNone(svc.next_batch("gnn"))


class Tensorizer(unittest.TestCase):
    def setUp(self):
        self.pipe = pipe_with()
        send_task(self.pipe, 0, "Pull wire list", blocks=["t2", "t9"], points=1)
        send_task(self.pipe, 1, "Bench test rack")
        send_task(self.pipe, 2, "Issue construction release", blocks=["t1"], points=3)

    def batch(self, **plan):
        plan.setdefault("text_dim", 64)
        spec = ConsumerSpec(name="gnn", plan=TensorPlan(name="gnn", **plan))
        return self.pipe.tensors(spec).next_batch("gnn")

    def test_hashing_is_deterministic_and_normalised(self):
        objs = peek(self.pipe)
        a, b = hash_features(objs, 64), hash_features(objs, 64)
        self.assertTrue(np.array_equal(a, b))
        self.assertTrue(np.allclose(np.linalg.norm(a, axis=1), 1.0))

    def test_missing_numeric_is_masked_not_zero(self):
        b = self.batch(numeric_fields=("points",))
        vals, mask = self.pipe.store.get(b.numeric), self.pipe.store.get(b.numeric_mask)
        self.assertEqual(mask[:, 0].tolist(), [True, False, True])
        self.assertEqual(vals[:, 0].tolist(), [1.0, 0.0, 3.0])

    def test_edges_only_inside_the_batch(self):
        b = self.batch(relation_types=("blocks",))
        self.assertEqual(self.pipe.store.get(b.edge_index).tolist(), [[0, 2], [2, 1]])  # t9 is not in the batch
        self.assertEqual(self.pipe.store.get(b.edge_type).tolist(), [0, 0])

    def test_lineage_traces_rows_to_raw_content(self):
        b = self.batch()
        raws = {e.payload["object_id"]: e.payload["content_sha256"] for e in self.pipe.broker.replay("domain/#")}
        self.assertEqual(b.content_sha256, tuple(raws[i] for i in b.object_ids))
        self.assertEqual(b.offsets, (0, 1, 2))
        for sha, oid in zip(b.content_sha256, b.object_ids):
            src = [e for e in self.pipe.broker.replay("raw/#") if e.payload["content_sha256"] == sha]
            self.assertEqual(len(src), 1, oid)


class Projection(unittest.TestCase):
    def setUp(self):
        self.pipe = pipe_with()
        names = ["pull wire list rack", "bench test rack power", "issue construction release", "punch list closeout",
                 "rack elevation drawing", "ceiling survey power"]
        for i, n in enumerate(names):
            send_task(self.pipe, i, n)
        self.objs = tuple(peek(self.pipe))

    def test_frozen_projection_is_never_refit(self):
        proj = self.pipe.tensorizer.fit_projection("p", 64, self.objs)
        again = self.pipe.tensorizer.fit_projection("p", 64, self.objs)
        self.assertEqual(proj.digest, again.digest)
        self.assertAlmostEqual(proj.explained_share + proj.discarded_share, 1.0)
        self.assertGreater(proj.discarded_share, 0.0)
        before = self.pipe.store.get(proj.components).copy()
        spec = ConsumerSpec(name="gnn", plan=TensorPlan(name="gnn", text_dim=64, projection=proj))
        b = self.pipe.tensors(spec).next_batch("gnn")
        self.assertEqual(b.projection_digest, proj.digest)
        self.assertEqual(self.pipe.store.get(b.positions).shape, (6, 3))
        self.assertTrue(np.array_equal(before, self.pipe.store.get(proj.components)))

    def test_projection_width_must_match(self):
        proj = self.pipe.tensorizer.fit_projection("p", 64, self.objs)
        spec = ConsumerSpec(name="w", plan=TensorPlan(name="w", text_dim=128, projection=proj))
        with self.assertRaises(TensorContractError):
            self.pipe.tensors(spec).next_batch("w")

    def test_fit_needs_rank_three(self):
        with self.assertRaises(ValueError):
            self.pipe.tensorizer.fit_projection("p", 64, self.objs[:2])


class Docs(unittest.TestCase):
    def test_fields_described_and_doctest(self):
        for c in IG.CONTRACTS:
            self.assertTrue(c.__doc__, c.__name__)
            for name, f in c.model_fields.items():
                self.assertTrue(f.description, f"{c.__name__}.{name}")
        self.assertEqual(doctest.testfile(str(ROOT / "docs/architecture/INGESTION.md"), module_relative=False).failed, 0)

    def test_json_bodies_are_canonical(self):
        pipe = pipe_with()
        a = put_raw(pipe, platform="f", fmt="json", source_id="x", received_at=WHEN, json_body={"b": 1, "a": 2}, mapping="tasks")
        self.assertEqual(pipe.blobs.get(a.content), json.dumps({"a": 2, "b": 1}, sort_keys=True).encode())


if __name__ == "__main__":
    unittest.main()
