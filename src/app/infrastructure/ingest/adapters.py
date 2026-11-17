"""Source adapters: the anti-corruption layer. Stdlib only; PDF uses optional pypdf. Deterministic."""

from __future__ import annotations

import email
import email.policy
import email.utils
import hashlib
import io
import json
import math
import re
import zipfile
from datetime import datetime
from html import unescape
from typing import Any, Mapping
from xml.etree import ElementTree as ET

from pydantic import BaseModel, ValidationError

from app.application.ingest.contracts import (AdapterResult, DomainObject, IngestConfig, JsonMapping, Provenance, RawItem,
                                              Rejection, ResourceRef, TypedRelation)
from app.application.process.contracts import ProcessExecution

MAX_UNZIPPED = 50 * 1024 * 1024


def pseudonym(config: IngestConfig, value: str) -> str:
    norm = value.strip().lower()
    return "res-" + hashlib.sha256(f"{config.pseudonym_salt}|{norm}".encode()).hexdigest()[:16]


def _key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:20]


class _Base:
    name = "base"
    version = "1"

    def __init__(self, blobs):
        self.blobs = blobs

    def prov(self, raw: RawItem) -> Provenance:
        return Provenance(platform=raw.platform, format=raw.format, source_id=raw.source_id,
                          content_sha256=raw.content.sha256, adapter=self.name, adapter_version=self.version,
                          received_at=raw.received_at)

    def reject(self, raw: RawItem, reason: str) -> AdapterResult:
        return AdapterResult(rejection=Rejection(topic=raw.topic, content_sha256=raw.content.sha256, adapter=self.name,
                                                 reason=reason[:500], received_at=raw.received_at))

    def parse(self, raw: RawItem, config: IngestConfig, mappings: Mapping[str, JsonMapping]) -> AdapterResult:
        try:
            data = self.blobs.get(raw.content)
            return AdapterResult(objects=tuple(self._parse(raw, data, config, mappings)))
        except _Reject as r:
            return self.reject(raw, str(r))
        except (ValueError, KeyError, TypeError, UnicodeDecodeError, zipfile.BadZipFile, ET.ParseError) as e:
            return self.reject(raw, f"{type(e).__name__}: {e}")

    def _parse(self, raw, data, config, mappings):
        raise NotImplementedError


class _Reject(Exception):
    pass


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n]


class TextAdapter(_Base):
    name, version = "text", "1"

    def _parse(self, raw, data, config, mappings):
        text = data.decode("utf-8")
        if not text.strip():
            raise _Reject("empty text")
        title = text.strip().splitlines()[0][:200]
        yield DomainObject(object_id=f"{raw.platform}:text:{_key(raw.source_id)}", kind="text", title=title,
                           text=_clip(text, config.max_text), fields={"chars": len(text)}, provenance=self.prov(raw))


class EmailAdapter(_Base):
    name, version = "email", "1"

    def _parse(self, raw, data, config, mappings):
        if not data.strip():
            raise _Reject("empty message")
        msg = email.message_from_bytes(data, policy=email.policy.default)
        if not (msg.get("From") or msg.get("Subject")):
            raise _Reject("not an RFC 5322 message: no From or Subject")
        mid = (msg.get("Message-ID") or "").strip() or raw.content.sha256
        oid = f"{raw.platform}:email:{_key(mid)}"
        body_part = msg.get_body(preferencelist=("plain", "html"))
        body = body_part.get_content() if body_part is not None else ""
        if body_part is not None and body_part.get_content_subtype() == "html":
            body = unescape(re.sub(r"<[^>]+>", " ", body))
        res = []
        for role, header in (("sender", "From"), ("recipient", "To"), ("recipient", "Cc")):
            for _, addr in email.utils.getaddresses(msg.get_all(header, [])):
                if addr:
                    res.append(ResourceRef(role=role, token=pseudonym(config, addr)))
        rels = []
        irt = (msg.get("In-Reply-To") or "").strip()
        if irt:
            rels.append(TypedRelation(type="reply_to", target_id=f"{raw.platform}:email:{_key(irt)}", evidence="In-Reply-To"))
        occurred = None
        if msg.get("Date"):
            occurred = email.utils.parsedate_to_datetime(msg["Date"])
            if occurred.tzinfo is None:
                occurred = None
        attachments = sum(1 for _ in msg.iter_attachments())
        yield DomainObject(object_id=oid, kind="email_message", title=str(msg.get("Subject") or "")[:500],
                           text=_clip(body.strip(), config.max_text), fields={"attachments": attachments, "recipients": sum(r.role == "recipient" for r in res)},
                           relations=tuple(rels), resources=tuple(dict.fromkeys(res)), occurred_at=occurred, provenance=self.prov(raw))


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CORE = {"dc": "http://purl.org/dc/elements/1.1/", "dcterms": "http://purl.org/dc/terms/",
        "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"}


class DocxAdapter(_Base):
    name, version = "docx", "1"

    def _parse(self, raw, data, config, mappings):
        z = zipfile.ZipFile(io.BytesIO(data))
        if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED:
            raise _Reject("docx expands beyond the size limit")
        if "word/document.xml" not in z.namelist():
            raise _Reject("not a docx: word/document.xml missing")
        root = ET.fromstring(z.read("word/document.xml"))
        paras = ["".join(t.text or "" for t in p.iter(W + "t")) for p in root.iter(W + "p")]
        paras = [p for p in paras if p.strip()]
        title, author, modified = None, None, None
        if "docProps/core.xml" in z.namelist():
            core = ET.fromstring(z.read("docProps/core.xml"))
            t = core.find("dc:title", CORE); a = core.find("dc:creator", CORE); m = core.find("dcterms:modified", CORE)
            title = t.text if t is not None and t.text else None
            author = a.text if a is not None and a.text else None
            if m is not None and m.text:
                modified = datetime.fromisoformat(m.text.replace("Z", "+00:00"))
        text = "\n".join(paras)
        res = (ResourceRef(role="author", token=pseudonym(config, author)),) if author else ()
        yield DomainObject(object_id=f"{raw.platform}:docx:{_key(raw.source_id)}", kind="document",
                           title=(title or (paras[0] if paras else ""))[:500], text=_clip(text, config.max_text),
                           fields={"paragraphs": len(paras), "words": len(text.split())}, resources=res,
                           occurred_at=modified if modified and modified.tzinfo else None, provenance=self.prov(raw))


class PdfAdapter(_Base):
    name, version = "pdf", "1"

    def _parse(self, raw, data, config, mappings):
        try:
            from pypdf import PdfReader  # optional extra: datamesh-agency-toolkit[pdf]
        except ImportError:
            raise _Reject("pdf extractor unavailable: install the optional 'pdf' extra (pypdf)")
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise _Reject("encrypted pdf")
        pages = [(p.extract_text() or "") for p in reader.pages]
        text = "\n".join(pages).strip()
        meta = reader.metadata or {}
        title = (meta.get("/Title") or (text.splitlines()[0] if text else ""))
        author = meta.get("/Author")
        res = (ResourceRef(role="author", token=pseudonym(config, str(author))),) if author else ()
        yield DomainObject(object_id=f"{raw.platform}:pdf:{_key(raw.source_id)}", kind="document", title=str(title)[:500],
                           text=_clip(text, config.max_text),
                           fields={"pages": len(pages), "words": len(text.split()), "text_extracted": bool(text)},
                           resources=res, provenance=self.prov(raw))


def _path(body: Any, path: str):
    cur = body
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _as_list(v):
    return [] if v is None else (v if isinstance(v, list) else [v])


class JsonAdapter(_Base):
    name, version = "json", "1"

    def _parse(self, raw, data, config, mappings):
        m = mappings.get(raw.mapping)
        if m is None:
            raise _Reject(f"unknown mapping {raw.mapping!r}")
        body = json.loads(data.decode("utf-8"))
        if not isinstance(body, dict):
            raise _Reject("json body must be an object")
        nat = _path(body, m.id_field)
        if nat is None or isinstance(nat, (dict, list)):
            raise _Reject(f"missing natural key at {m.id_field}")
        fields = {}
        for f, p in m.numeric_fields.items():
            v = _path(body, p)
            if v is None:
                continue
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise _Reject(f"field {f} at {p} is not a finite number")
            fields[f] = v
        for f, p in m.scalar_fields.items():
            v = _path(body, p)
            if isinstance(v, (dict, list)):
                raise _Reject(f"field {f} at {p} is not a scalar")
            if v is not None:
                fields[f] = v
        rels = tuple(TypedRelation(type=t, target_id=f"{raw.platform}:{v}", evidence=p)
                     for p, t in m.relation_fields.items() for v in _as_list(_path(body, p)) if isinstance(v, (str, int)))
        res = tuple(ResourceRef(role=role if role in ("sender", "recipient", "author", "assignee", "owner", "executor") else "other",
                                token=pseudonym(config, str(v)))
                    for p, role in m.resource_fields.items() for v in _as_list(_path(body, p)) if v)
        occurred = None
        if m.occurred_at_field and _path(body, m.occurred_at_field):
            occurred = datetime.fromisoformat(str(_path(body, m.occurred_at_field)).replace("Z", "+00:00"))
            if occurred.tzinfo is None:
                raise _Reject("timestamp must carry a timezone")
        text = "\n".join(str(_path(body, p)) for p in m.text_fields if _path(body, p) is not None)
        title = _path(body, m.title_field) if m.title_field else None
        yield DomainObject(object_id=f"{raw.platform}:{nat}", kind=m.kind, title=str(title or "")[:500],
                           text=_clip(text, config.max_text), fields=fields, relations=rels, resources=res,
                           occurred_at=occurred, provenance=self.prov(raw))


class DataContractAdapter(_Base):
    name, version = "data_contract", "1"

    def __init__(self, blobs, registry: Mapping[str, type[BaseModel]] | None = None):
        super().__init__(blobs)
        self.registry = dict(registry or {"ProcessExecution": ProcessExecution})

    def _parse(self, raw, data, config, mappings):
        model = self.registry.get(raw.contract_name)
        if model is None:
            raise _Reject(f"unregistered data contract {raw.contract_name!r}")
        try:
            obj = model.model_validate_json(data)
        except ValidationError as e:
            err = e.errors()[0]
            raise _Reject(f"{raw.contract_name} invalid at {'.'.join(map(str, err['loc']))}: {err['msg']}")
        prov = self.prov(raw)
        if isinstance(obj, ProcessExecution):
            yield DomainObject(
                object_id=f"{raw.platform}:pe:{obj.execution_id}", kind="process_execution", title=obj.process.name[:500],
                fields={"process_code": obj.process.code, "stage": obj.stage, "decision": obj.decision,
                        "function_classes": ",".join(obj.process.function_classes), "approved_classes": obj.process.approved,
                        "epistemic_status": obj.epistemic_status, "objects": len(obj.incidence)},
                relations=tuple(TypedRelation(type=i.effect, target_id=i.object_id, evidence="incidence") for i in obj.incidence),
                resources=tuple(ResourceRef(role="executor", token=pseudonym(config, b.resource_id), role_label=b.resource_role)
                                for b in obj.executed_by),
                occurred_at=obj.occurred_at if obj.occurred_at and obj.occurred_at.tzinfo else None, provenance=prov)
            return
        flat = {k: v for k, v in obj.model_dump(mode="json").items() if isinstance(v, (str, int, float, bool)) or v is None}
        yield DomainObject(object_id=f"{raw.platform}:{raw.contract_name}:{_key(raw.source_id)}", kind=raw.contract_name.lower(),
                           title=str(flat.get("name") or flat.get("title") or raw.source_id)[:500],
                           fields=dict(list(flat.items())[:64]), provenance=prov)


def default_adapters(blobs, contracts=None, profiles=None):
    from .xlsx import XlsxWorkbookAdapter  # local import: xlsx builds on this module's base class
    return {"text": TextAdapter(blobs), "email": EmailAdapter(blobs), "docx": DocxAdapter(blobs), "pdf": PdfAdapter(blobs),
            "json": JsonAdapter(blobs), "data_contract": DataContractAdapter(blobs, contracts),
            "xlsx": XlsxWorkbookAdapter(blobs, profiles)}
