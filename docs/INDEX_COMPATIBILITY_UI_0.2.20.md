# Index compatibility UI — 0.2.20-alpha

- Catalog summaries display whether an index is ready, missing, or requires a rebuild.
- Incompatible identity fields are shown without exposing raw JSON.
- The identity check covers schema, extractor version, embedding provider/dimension/revision, and visual-indexing mode.
- Clicking Update on an incompatible index offers a safe rebuild while preserving all source files.
- Automatic updates skip incompatible indexes instead of failing the whole multi-catalog pass.
- Search still refuses to mix incompatible vectors and chunks.
