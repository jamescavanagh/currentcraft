# Candidate operand profiles and vorticity compression

Status: candidate analytical representation, not approved policy or operational forecast. The analogy terms below are sourced from the USDA NRCS *Soil Survey Manual*, Chapter 3. Their use in Currentcraft is an explicit design analogy, not a claim that enterprise records are soil or physical flow.

## Currentcraft boundary

Currentcraft's canonical process model already treats objects as operands and people, teams, and tools as resources that execute processes. This slice retains that boundary. The eleven supplied contexts are Projects, Inventory, Employees and Contributors, Working Docs, Drawings, Subsystems, Product Features, Site Acceptance Testing, Commercial Orders, Clients, and Estimation/Needs Analysis. Timecards are left out. Employees, contributors, and clients may define context, but people and client parties are never operand objects.

`OperandRef`, `OperandProfile`, `ProfileLayer`, and `FormationSet` are immutable Pydantic domain value objects. They contain references and source-backed classifications only: no embedding arrays, I/O, inference, permission, lifecycle transition, or automatic interpretation. Layer classifications and common formation periods require explicit evidence. A missing profile is not evidence that no structure exists.

The soil terms are mapped only as candidates:

| Source term | Candidate Currentcraft abstraction | Limitation |
| --- | --- | --- |
| Pedon | An operand plus its contextual profile record | No physical volume or representativeness is asserted. |
| Profile | `OperandProfile` | A versioned view/reference, not the source object itself. |
| Horizon / layer | `ProfileLayer` with `pedogenic_horizon`, `inherited_layer`, or `unknown` | Source classification only; the model does not infer how a record formed. |
| Solum | `FormationSet` grouping explicitly supported process-formed layers | No group is inferred from text similarity or adjacency. |
| Structure / porosity | Existing typed process/incidence links and gauge-invariant relations | No new connectivity or pore network is fabricated. |

## Numerical infrastructure

`OperandCompressionService` adapts caller-ordered operand UUIDs to the existing `GaugeRequest` and calls `GaugeService.reduce_checked`. The infrastructure composition root reuses `build_numpy_gauge`, the shared tensor store, the existing NumPy gauge kernel, and its invariance checks. The output remains the existing `GaugeResult` TensorRefs plus the check receipt, tagged `embedding_geometry` and candidate-only. There is no second vorticity implementation, no inferred embedding projection, and no mapping of source text into coordinates. Input embedding generation remains an upstream, versioned caller responsibility.

Only callers with an explicit `EMBEDDINGS_SPEC` TensorRef can request compression. Row order must match operand order. The invariance check must pass before any reading is returned; failure raises through the existing service boundary. A candidate reading cannot release a document, approve a drawing, allocate capacity, commit spend, or change a person’s status.

## Source evidence

USDA NRCS, *Soil Survey Manual 2017, Chapter 3: Examination and Description of Soil Profiles*, https://www.nrcs.usda.gov/sites/default/files/2022-09/SSM-ch3.pdf:

- “A pedon is a three-dimensional body of soil” used to describe horizon arrangement and collect representative samples.
- “A soil profile is smaller than a pedon” and is exposed by a two-dimensional vertical cut.
- A soil horizon is distinguished by properties “produced by the soil-forming processes”; “layer” is used for inherited properties such as sedimentary strata.
- The solum consists of horizons related through the same period of pedogenesis.

These are source definitions, not an approval of the Currentcraft mapping. Every mapping remains candidate pending James's semantic review and any private enterprise vocabulary crosswalk.
