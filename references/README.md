# Reference boundary

PUBLIC: this README and public/manifest.example.json only. The template has no real records or external identifiers.

PRIVATE LOCAL: references/private/ is reserved for enterprise dictionaries, source documents, identity mappings, frozen projections/centering vectors fitted on enterprise data, fitted model artifacts and private manifests. Create it locally only. Raw records, embeddings and outputs may disclose data even without names; treat them as private by default. Use data/private/ for bulky local datasets if needed (all data/ is ignored).

Never put passwords/API tokens in references/. Use environment variables or an approved secret manager. Domain classes do not read files; a separately approved infrastructure loader validates reference versions and explicitly maps them into application contracts. This release adds no private loader or automatic upload.

BUNDLES: `scripts/export_public.py --with-private` adds references/private/ to a coordinator bundle under the same root, listed separately in the manifest. It refuses unless .gitignore ignores references/private/ (and, inside Git, `git check-ignore` agrees). Unzipping a bundle into a clone therefore leaves the private files untracked. Never publish a bundle; publish only the plain export.

.gitignore is not encryption, access control, history scrubbing, or a complete DLP system. It does not remove files already tracked. scripts/check_release.py checks the actual Git index for forbidden tracked paths when run inside Git; it also checks the filesystem and obvious disclosure patterns. scripts/export_public.py exports only a fixed allowlist and refuses symlinks/private paths. Manually review the resulting archive. Files from older package ZIPs must not be copied wholesale into a public repository.

For tracked private data: stop publication, remove it from the index, investigate repository history and rotate exposed credentials if necessary. Deleting a file from the latest commit does not remove old copies.
