# Data policy

Public release is allowlisted: reusable numeric/application slices, purely synthetic fixtures embedded in test code, generated schemas, documentation, empty reference template, tests and release tooling. Excluded: original data/ and models/, frame-record fixtures, source-derived node coordinates/labels, internal URLs/task navigation, employee/customer/project identifiers, ERP/CRM adapters and configuration, original context maps, past ZIPs and bytecode.

Keep enterprise records and any reversible/derived representations (embeddings, learned projections, private dictionaries, run outputs, identifier crosswalks) outside public artifacts, preferably references/private/ and ignored data/. Do not assume an embedding or a numeric coordinate is anonymized. Never use public templates to store real enterprise records.

Validation outcomes do not establish confidentiality: automated scanning detects a limited set of suspicious patterns. Human source-rights and data-classification review remains required. A private directory on disk still needs access control and appropriate encryption/retention policy; none is provided by this Python package.

- Synthetic email addresses in tests and docs use only the reserved domain `example.invalid` (RFC 6761); the release check rejects every other address.
