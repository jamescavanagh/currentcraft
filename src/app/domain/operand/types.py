"""Six candidate domain extensions, composed over canonical entities. Rules: docs/domain/SIX_DOMAIN_TYPES.md.

Canonical entities stay authoritative. An extension never subclasses or re-serializes a canonical record:
it has its own identity/version and holds exact, kind-tagged references to canonical records. Whether
those references are real, current at the stated version and owned correctly is decided outside the
domain, by an explicit resolution port and a pinned ownership profile from the referenced standard.
"""
import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import Text
from app.domain.shared.quantities import Quantity
from app.domain.shared.versioning import VersionRef
from .feature_graph import Digest, Timestamp
from .profile import FrozenValue

SCHEMA_VERSION = "currentcraft-six-extensions/v1"
Revision = Annotated[int, Field(ge=1, strict=True)]
ExtensionSchema = Literal["currentcraft-six-extensions/v1"]
CanonicalKind = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]{1,63}$")]
Outcome = Literal["not_run", "pass", "fail", "inconclusive"]
OwnerExpectation = Literal["subject"]


class CanonicalRef(FrozenValue):
    """Exact canonical record reference: declared kind, opaque identity and record version."""
    kind: CanonicalKind = Field(description="Declared canonical entity kind; checked against the resolved record, never trusted alone.")
    identity: UUID = Field(description="Canonical entity identity; never a filename, label or source key.")
    version: Revision = Field(description="Exact canonical record version; no latest-version substitution.")

    def version_ref(self) -> VersionRef:
        return VersionRef(identity=self.identity, version=self.version)


class ReferenceUse(FrozenValue):
    """One place an extension points at a canonical record, with what resolution must establish."""
    role: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_.\[\]]*$", description="Field path of the reference inside the extension.")
    reference: CanonicalRef = Field(description="The exact canonical reference used.")
    required: bool = Field(description="True when the extension is meaningless without it; unresolved required references block.")
    same_project: bool = Field(default=True, description="Project-owned records must belong to the extension's project.")
    expect_owner: OwnerExpectation | None = Field(default=None, description="When set, a non-project owner from the ownership profile must equal the extension subject.")


def distinct_refs(values, label):
    identities = [ref.identity for ref in values]
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate_or_conflicting_" + label)


def require_kind(ref, kinds, label):
    if ref is not None and ref.kind not in kinds:
        raise ValueError(label + "_kind_not_allowed")


def selection_digest(selected) -> str:
    encoded = json.dumps(sorted(str(key) for key in selected), separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


EVIDENCE_KINDS = frozenset({"quality_evidence", "revision"})
DECISION_KINDS = frozenset({"gate_decision"})
COMPONENT_KINDS = frozenset({"asset_instance", "product_definition", "subsystem"})
WORK_PACKAGE_KINDS = frozenset({"wbs", "task", "work_item"})


class ExtensionRecord(FrozenValue):
    """Extension identity and version, independent of any canonical record's identity and version."""
    schema_version: ExtensionSchema = Field(default=SCHEMA_VERSION, description="Extension wire family; canonical payloads are never re-serialized here.")
    definition_status: Literal["v1-proposal"] = Field(default="v1-proposal", description="Candidate definition; not an accepted domain type.")
    extension_id: UUID = Field(description="Opaque extension identity; must differ from every referenced canonical identity.")
    extension_version: Revision = Field(description="Extension record version; changes when the extension changes, not the canonical record.")
    project: CanonicalRef = Field(description="Exact canonical project this extension belongs to.")

    @model_validator(mode="after")
    def extension_integrity(self):
        require_kind(self.project, {"project"}, "project")
        if any(use.reference.identity == self.extension_id for use in self.references()):
            raise ValueError("extension_shadows_canonical_identity")
        return self

    def ref(self) -> VersionRef:
        return VersionRef(identity=self.extension_id, version=self.extension_version)

    def references(self) -> tuple[ReferenceUse, ...]:
        return (ReferenceUse(role="project", reference=self.project, required=True),)

    def require_accepted_definition(self) -> None:
        raise NotImplementedError(f"{type(self).__name__}: candidate extension has not received semantic acceptance")


def _uses(role, refs, required=False, **flags):
    return tuple(ReferenceUse(role=f"{role}[{i}]", reference=r, required=required, **flags) for i, r in enumerate(refs))


def _fact_use(role, fact, **flags):
    return (ReferenceUse(role=role, reference=fact.value, required=False, **flags),) if fact.value is not None else ()


class ConfigurationBinding(FrozenValue):
    """Exact configuration extension and model pin, not permission or compatibility proof."""
    configuration: VersionRef = Field(description="Exact feature-configuration extension identity and version.")
    graph_id: UUID = Field(description="Exact feature-model graph identity.")
    graph_revision: Revision = Field(description="Exact selected graph revision.")
    graph_digest: Digest = Field(description="Exact selected graph content digest.")
    selection_digest: Digest = Field(description="Canonical selected-feature identity digest, not source text.")


class RevisionAuthorization(FrozenValue):
    """Sourced authorization assertion; actor authority must be resolved separately."""
    revision: CanonicalRef = Field(description="Exact canonical revision this assertion concerns.")
    decision: CanonicalRef = Field(description="Exact canonical decision record, not generated by any receipt.")
    evidence: tuple[CanonicalRef, ...] = Field(min_length=1, description="Exact supporting canonical evidence.")

    @model_validator(mode="after")
    def evidence_integrity(self):
        require_kind(self.revision, {"revision"}, "authorization_revision")
        require_kind(self.decision, DECISION_KINDS, "authorization_decision")
        for ref in self.evidence:
            require_kind(ref, EVIDENCE_KINDS, "authorization_evidence")
        distinct_refs(self.evidence, "authorization_evidence")
        return self


class ProjectExtension(ExtensionRecord):
    """Project scope and baseline beside, not inside, the canonical project."""
    scope: Fact[Text] = Field(default_factory=unknown, description="Sourced scope or explicit unknown; not an executable work authorization.")
    lifecycle_phase: Fact[Text] = Field(default_factory=unknown, description="Sourced phase label as written; no universal phase list imposed.")
    phase: Fact[CanonicalRef] = Field(default_factory=unknown, description="Exact canonical phase record, when the source names one.")
    work_packages: tuple[CanonicalRef, ...] = Field(default=(), description="Exact canonical work-package records; empty does not establish that none exist.")
    dependencies: tuple[CanonicalRef, ...] = Field(default=(), description="Explicit exact project dependencies, not inferred from sequence.")
    configuration_baseline: Fact[ConfigurationBinding] = Field(default_factory=unknown, description="Selected exact baseline or explicit unknown, not approval.")

    @model_validator(mode="after")
    def project_integrity(self):
        require_kind(self.phase.value, {"phase"}, "phase")
        for ref in self.work_packages:
            require_kind(ref, WORK_PACKAGE_KINDS, "work_package")
        for ref in self.dependencies:
            require_kind(ref, {"project"}, "dependency")
        for label in ("work_packages", "dependencies"):
            values = getattr(self, label)
            distinct_refs(values, label)
            if any(ref.identity == self.project.identity for ref in values):
                raise ValueError("project_self_reference")
        return self

    def references(self):
        return (super().references() + _fact_use("phase", self.phase)
                + _uses("work_packages", self.work_packages)
                + _uses("dependencies", self.dependencies, same_project=False))


class WorkingDocumentExtension(ExtensionRecord):
    """Working-document revision lineage; receipt and authorization stay independent."""
    document: CanonicalRef = Field(description="Exact canonical document this extension describes.")
    captured_revision: CanonicalRef = Field(description="Exact canonical revision represented by this snapshot.")
    configuration: Fact[ConfigurationBinding] = Field(default_factory=unknown, description="Configuration evidenced by this revision, or explicit unknown.")
    derived_from: tuple[CanonicalRef, ...] = Field(default=(), description="Exact canonical revisions used to derive this revision; may belong to other documents.")
    supersedes: Fact[CanonicalRef] = Field(default_factory=unknown, description="Sourced superseded revision of the same document, not inferred from dates or names.")
    latest_received_revision: Fact[CanonicalRef] = Field(default_factory=unknown, description="Latest evidenced receipt of the same document; does not replace authorization.")
    authorization: Fact[RevisionAuthorization] = Field(default_factory=unknown, description="Independent sourced release assertion; not authority verification.")

    @model_validator(mode="after")
    def document_integrity(self):
        require_kind(self.document, {"document"}, "document")
        for ref in (self.captured_revision, *self.derived_from, self.supersedes.value, self.latest_received_revision.value):
            require_kind(ref, {"revision"}, "revision")
        distinct_refs(self.derived_from, "derivation")
        if self.captured_revision in self.derived_from or self.supersedes.value == self.captured_revision:
            raise ValueError("document_revision_self_reference")
        return self

    def references(self):
        auth = self.authorization.value
        auth_uses = () if auth is None else (
            (ReferenceUse(role="authorization.revision", reference=auth.revision, required=False, expect_owner="subject"),
             ReferenceUse(role="authorization.decision", reference=auth.decision, required=False))
            + _uses("authorization.evidence", auth.evidence, same_project=False))
        return (super().references()
                + (ReferenceUse(role="document", reference=self.document, required=True),
                   ReferenceUse(role="captured_revision", reference=self.captured_revision, required=True, expect_owner="subject"))
                + _uses("derived_from", self.derived_from, same_project=False)
                + _fact_use("supersedes", self.supersedes, expect_owner="subject")
                + _fact_use("latest_received_revision", self.latest_received_revision, expect_owner="subject")
                + auth_uses)

    @property
    def subject(self) -> CanonicalRef:
        return self.document


class OrderLine(FrozenValue):
    """Versioned extension-owned line; quantity and commitment remain independent assertions."""
    line: VersionRef = Field(description="Exact extension-owned line identity/version, not a row number.")
    quantity: Fact[Quantity] = Field(default_factory=unknown, description="Exact nonnegative quantity and dictionary unit, or explicit unknown.")
    requested_configuration: Fact[ConfigurationBinding] = Field(default_factory=unknown, description="Exact requested line configuration or explicit unknown.")
    commitment: Fact[CanonicalRef] = Field(default_factory=unknown, description="Sourced canonical commitment record; does not itself prove authority.")
    fulfillment: tuple[CanonicalRef, ...] = Field(default=(), description="Exact canonical fulfillment evidence, not proof of reconciliation.")

    @model_validator(mode="after")
    def line_integrity(self):
        require_kind(self.commitment.value, {"contract", "quality_evidence"}, "commitment")
        for ref in self.fulfillment:
            require_kind(ref, {"shipment", "quality_evidence"}, "fulfillment")
        distinct_refs(self.fulfillment, "fulfillment")
        return self


class CommercialOrderExtension(ExtensionRecord):
    """Commercial commitment capture beside the canonical order; distinct from shipment, invoice and payment."""
    order: CanonicalRef = Field(description="Exact canonical order this extension describes.")
    requested_configuration: Fact[ConfigurationBinding] = Field(default_factory=unknown, description="Exact requested order configuration or explicit unknown.")
    lines: tuple[OrderLine, ...] = Field(default=(), description="Explicit source lines; empty is not a claim of complete order capture.")
    commitment_evidence: tuple[CanonicalRef, ...] = Field(default=(), description="Sourced canonical commitment evidence, separate from fulfillment and authority.")

    @model_validator(mode="after")
    def order_integrity(self):
        require_kind(self.order, {"order"}, "order")
        for ref in self.commitment_evidence:
            require_kind(ref, {"contract", "quality_evidence"}, "commitment_evidence")
        distinct_refs(tuple(line.line for line in self.lines), "order_line")
        distinct_refs(self.commitment_evidence, "commitment_evidence")
        baseline = self.requested_configuration.value
        for line in self.lines:
            if baseline is not None and line.requested_configuration.value not in (None, baseline):
                raise ValueError("line_order_configuration_mismatch")
        return self

    def references(self):
        line_uses = ()
        for i, line in enumerate(self.lines):
            line_uses += _fact_use(f"lines[{i}].commitment", line.commitment) + _uses(f"lines[{i}].fulfillment", line.fulfillment)
        return (super().references() + (ReferenceUse(role="order", reference=self.order, required=True),)
                + _uses("commitment_evidence", self.commitment_evidence) + line_uses)

    @property
    def subject(self) -> CanonicalRef:
        return self.order


class SubsystemInterface(FrozenValue):
    """Sourced interface assertion, not proof of physical interoperability."""
    interface_id: UUID = Field(description="Opaque identity of this interface assertion.")
    local_component: CanonicalRef = Field(description="Exact canonical component inside this subsystem.")
    peer: CanonicalRef = Field(description="Explicit canonical peer, possibly outside the local boundary; not resolved implicitly.")
    specification: CanonicalRef = Field(description="Exact canonical interface specification revision.")
    evidence: tuple[CanonicalRef, ...] = Field(min_length=1, description="Exact canonical evidence for the interface.")

    @model_validator(mode="after")
    def interface_integrity(self):
        require_kind(self.local_component, COMPONENT_KINDS, "interface_component")
        require_kind(self.peer, COMPONENT_KINDS, "interface_peer")
        require_kind(self.specification, {"revision"}, "interface_specification")
        for ref in self.evidence:
            require_kind(ref, EVIDENCE_KINDS, "interface_evidence")
        distinct_refs(self.evidence, "interface_evidence")
        if self.local_component == self.peer:
            raise ValueError("interface_self_reference")
        return self


class FeatureRealization(FrozenValue):
    """Sourced assertion that an exact component realizes one selected feature."""
    feature_id: UUID = Field(description="Feature identity resolved against the selected graph revision.")
    component: CanonicalRef = Field(description="Exact realizing canonical component inside the subsystem.")
    evidence: tuple[CanonicalRef, ...] = Field(min_length=1, description="Canonical evidence, not inferred from co-presence or model validity.")

    @model_validator(mode="after")
    def realization_integrity(self):
        require_kind(self.component, COMPONENT_KINDS, "realization_component")
        for ref in self.evidence:
            require_kind(ref, EVIDENCE_KINDS, "realization_evidence")
        distinct_refs(self.evidence, "realization_evidence")
        return self


class SubsystemExtension(ExtensionRecord):
    """Technical boundary, exact interfaces and evidenced feature realization beside the canonical subsystem."""
    subsystem: CanonicalRef = Field(description="Exact canonical subsystem this extension describes.")
    boundary: Fact[Text] = Field(default_factory=unknown, description="Sourced boundary/concern description or explicit unknown.")
    configuration: Fact[ConfigurationBinding] = Field(default_factory=unknown, description="Mapped exact configuration or explicit unknown.")
    components: tuple[CanonicalRef, ...] = Field(default=(), description="Exact declared canonical components, not inferred parts.")
    interfaces: tuple[SubsystemInterface, ...] = Field(default=(), description="Sourced interface descriptions, not compatibility approval.")
    dependencies: tuple[CanonicalRef, ...] = Field(default=(), description="Explicit exact subsystem dependencies, not scheduling constraints.")
    realizations: tuple[FeatureRealization, ...] = Field(default=(), description="Evidence-backed selected-feature/component mappings.")

    @model_validator(mode="after")
    def subsystem_integrity(self):
        require_kind(self.subsystem, {"subsystem"}, "subsystem")
        for ref in self.components:
            require_kind(ref, COMPONENT_KINDS, "component")
        for ref in self.dependencies:
            require_kind(ref, {"subsystem"}, "subsystem_dependency")
        for label in ("components", "dependencies"):
            values = getattr(self, label)
            distinct_refs(values, label)
            if any(ref.identity == self.subsystem.identity for ref in values):
                raise ValueError("subsystem_self_reference")
        if len({i.interface_id for i in self.interfaces}) != len(self.interfaces):
            raise ValueError("duplicate_interface")
        for interface in self.interfaces:
            if interface.local_component not in self.components:
                raise ValueError("interface_component_version_mismatch")
        keys = [(r.feature_id, r.component) for r in self.realizations]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate_realization")
        if any(r.component not in self.components for r in self.realizations):
            raise ValueError("realization_component_version_mismatch")
        return self

    def references(self):
        interface_uses = ()
        for i, item in enumerate(self.interfaces):
            interface_uses += (ReferenceUse(role=f"interfaces[{i}].peer", reference=item.peer, required=True, same_project=False),
                               ReferenceUse(role=f"interfaces[{i}].specification", reference=item.specification, required=True, same_project=False))
            interface_uses += _uses(f"interfaces[{i}].evidence", item.evidence, required=True, same_project=False)
        realization_uses = ()
        for i, item in enumerate(self.realizations):
            realization_uses += _uses(f"realizations[{i}].evidence", item.evidence, required=True, same_project=False)
        return (super().references() + (ReferenceUse(role="subsystem", reference=self.subsystem, required=True),)
                + _uses("components", self.components, required=True)
                + _uses("dependencies", self.dependencies) + interface_uses + realization_uses)

    @property
    def subject(self) -> CanonicalRef:
        return self.subsystem


class TestCriterion(FrozenValue):
    """Source-reported criterion result; this slice does not interpret thresholds."""
    criterion: VersionRef = Field(description="Exact agreed criterion definition revision (extension-owned).")
    expected: Fact[Text] = Field(default_factory=unknown, description="Sourced expected result/criterion expression, or explicit unknown.")
    observed: Fact[Text] = Field(default_factory=unknown, description="Source observation or explicit unknown; not manufactured from expected.")
    result: Outcome = Field(default="not_run", description="Source-reported result, not automatically evaluated from text.")
    evidence: tuple[CanonicalRef, ...] = Field(default=(), description="Exact canonical execution evidence; required for reported pass/fail.")

    @model_validator(mode="after")
    def criterion_integrity(self):
        for ref in self.evidence:
            require_kind(ref, EVIDENCE_KINDS, "criterion_evidence")
        distinct_refs(self.evidence, "criterion_evidence")
        if self.result in ("pass", "fail") and (self.expected.value is None or self.observed.value is None or
                self.observed.epistemic_status != "observed" or not self.evidence):
            raise ValueError("determinate_criterion_requires_observations_and_evidence")
        return self


class SiteAcceptanceTestExtension(ExtensionRecord):
    """Exact test execution capture; passing never creates an acceptance decision."""
    kind: Literal["test_record"] = Field(default="test_record", description="SAT record kind in the six-domain profile; not an acceptance grant.")
    configuration: ConfigurationBinding = Field(description="Exact agreed configuration under test.")
    basis: tuple[CanonicalRef, ...] = Field(min_length=1, description="Exact canonical test-basis revisions; no latest-version substitution.")
    conditions: Fact[Text] = Field(default_factory=unknown, description="Sourced execution conditions or explicit unknown.")
    criteria: tuple[TestCriterion, ...] = Field(default=(), description="Source-reported criteria/results; empty cannot yield a test pass.")
    observed_configuration: Fact[ConfigurationBinding] = Field(default_factory=unknown, description="Exact source-observed installed/tested configuration or explicit unknown.")
    result: Fact[Outcome] = Field(default_factory=unknown, description="Source-reported aggregate outcome, independent of acceptance.")
    tested_at: Fact[Timestamp] = Field(default_factory=unknown, description="Source-observed timezone-aware execution time or explicit unknown.")
    verification_activity: Fact[CanonicalRef] = Field(default_factory=unknown, description="Optional exact canonical verification activity.")
    acceptance_decision: Fact[CanonicalRef] = Field(default_factory=unknown, description="Independent canonical decision reference; never created by pass/fail.")

    @model_validator(mode="after")
    def test_integrity(self):
        for ref in self.basis:
            require_kind(ref, {"revision"}, "test_basis")
        require_kind(self.verification_activity.value, {"verification_activity"}, "verification_activity")
        require_kind(self.acceptance_decision.value, DECISION_KINDS, "acceptance_decision")
        distinct_refs(self.basis, "test_basis")
        distinct_refs(tuple(c.criterion for c in self.criteria), "test_criterion")
        outcome = self.result.value
        if outcome in ("pass", "fail"):
            if self.conditions.value is None or self.conditions.epistemic_status != "observed":
                raise ValueError("determinate_test_requires_observed_conditions")
            if self.result.epistemic_status != "observed" or self.tested_at.value is None or self.tested_at.epistemic_status != "observed":
                raise ValueError("determinate_test_requires_observed_result_and_time")
            if self.observed_configuration.value != self.configuration or self.observed_configuration.epistemic_status != "observed":
                raise ValueError("test_observed_configuration_mismatch")
        if outcome == "pass" and (not self.criteria or any(c.result != "pass" for c in self.criteria)):
            raise ValueError("test_pass_requires_all_criteria_pass")
        if outcome == "fail" and not any(c.result == "fail" for c in self.criteria):
            raise ValueError("test_fail_requires_failed_criterion")
        if outcome == "not_run" and any(c.result != "not_run" for c in self.criteria):
            raise ValueError("unexecuted_test_has_executed_criteria")
        return self

    def references(self):
        criterion_uses = ()
        for i, c in enumerate(self.criteria):
            criterion_uses += _uses(f"criteria[{i}].evidence", c.evidence, same_project=False)
        return (super().references() + _uses("basis", self.basis, required=True)
                + _fact_use("verification_activity", self.verification_activity)
                + _fact_use("acceptance_decision", self.acceptance_decision) + criterion_uses)


class FeatureConfigurationExtension(ExtensionRecord):
    """Explicit candidate assignment, not proof of an ordered or installed product."""
    kind: Literal["feature_configuration"] = Field(default="feature_configuration", description="An exact candidate configuration identity/version.")
    graph_id: UUID = Field(description="Selected feature-model graph identity.")
    graph_revision: Revision = Field(description="Selected exact graph revision.")
    graph_digest: Digest = Field(description="Exact graph content digest; validation rejects mismatches.")
    selected: tuple[UUID, ...] = Field(description="Explicit selected feature IDs, canonicalized; not observed-product evidence.")

    @model_validator(mode="after")
    def configuration_integrity(self):
        if len(set(self.selected)) != len(self.selected):
            raise ValueError("duplicate_selected_feature")
        object.__setattr__(self, "selected", tuple(sorted(self.selected)))
        return self

    def binding(self) -> ConfigurationBinding:
        return ConfigurationBinding(configuration=self.ref(), graph_id=self.graph_id,
            graph_revision=self.graph_revision, graph_digest=self.graph_digest,
            selection_digest=selection_digest(self.selected))


def context_kind(extension: ExtensionRecord) -> str:
    """Six-domain profile kind of an extension: its canonical subject's kind, or its own kind."""
    if isinstance(extension, ProjectExtension):
        return "project"
    subject = getattr(extension, "subject", None)
    return subject.kind if subject is not None else extension.kind


DOMAIN_TYPES = (ProjectExtension, WorkingDocumentExtension, CommercialOrderExtension, SubsystemExtension,
                SiteAcceptanceTestExtension, FeatureConfigurationExtension)
CONTRACTS = (CanonicalRef, ReferenceUse, ExtensionRecord, ConfigurationBinding, RevisionAuthorization, OrderLine, SubsystemInterface,
             FeatureRealization, TestCriterion) + DOMAIN_TYPES
