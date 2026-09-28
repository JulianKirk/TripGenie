# RAG knowledge-source contributions

The shared RAG server indexes only files listed in
[`../config/sources.json`](../config/sources.json).

Feature owners may add maintained Markdown or plain-text documentation by:

1. keeping the source inside this repository;
2. checking that it contains no credentials, personal trip data, generated
   logs, database content, or unreviewed model output;
3. adding one stable `source_id`, repository-relative path, title, and feature
   tag to the manifest; and
4. rebuilding the local index and running the grounded and
   insufficient-context tests.

Do not add environment files, SQLite databases, generated indexes, PDFs, HTML,
or broad directory globs. The manifest is an allowlist, not a crawler.

