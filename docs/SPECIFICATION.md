# SemanticX Find --- Technical Plan & LLM Agent Implementation Specification

**Target platform:** Windows 10 / Windows 11\
**Distribution:** Fully portable\
**Primary embedding model:** Google EmbeddingGemma 2\
**Default UI language:** English\
**Supported UI languages:** English, Russian, French, Spanish\
**Document languages:** English and Russian built-in user manual

------------------------------------------------------------------------

## 1. Product vision

Build a fast, modern, fully local desktop application for semantic
search across user-selected folders.

The user adds one or more directories, chooses which file extensions and
optional wildcard masks (`*`, `?`) should be indexed, and the
application creates a persistent semantic index. Later the user can
search using natural language rather than exact filenames or exact
words.

Primary example:

> "Where did I make tiled upscale with Qwen Image 2.1?"

The application should find relevant ComfyUI workflow JSON files even
when: - filenames are meaningless; - the exact query words do not appear
in the file; - the workflow expresses the concept through node structure
and parameters; - different node packs use different names for similar
operations.

The application must be useful beyond ComfyUI. The architecture should
support text, source code, structured files, images, audio and video
through pluggable extractors/indexers.

------------------------------------------------------------------------

# 2. Important architectural recommendation

Do **not** treat indexing as:

`file -> raw contents -> one embedding`

That is insufficient for large files, source code, ComfyUI workflows and
multimodal data.

Use:

`file -> specialized extractor -> semantic units/chunks -> embeddings + metadata -> local vector index`

For a ComfyUI workflow, create multiple searchable representations: 1.
whole-workflow summary; 2. node/model inventory; 3. functional
groups/subgraphs; 4. important node parameter blocks; 5. optionally raw
normalized JSON chunks.

This makes queries about one small part of a large workflow retrievable.

------------------------------------------------------------------------

# 3. Model strategy

## 3.1 EmbeddingGemma 2

Use `google/embeddinggemma-2` as the primary embedding engine.

EmbeddingGemma 2 maps text, code, images, audio and video into a shared
768-dimensional vector space. It supports Matryoshka truncation to 512,
256 and 128 dimensions.

For the initial JSON/code/text version, load **text only**: - disable
vision encoder; - disable audio encoder; - effective model size:
approximately 270M parameters; - use BF16 on supported NVIDIA GPUs; -
use FP32 on CPU or hardware where BF16 is unavailable; - do **not**
silently use FP16.

Default vector dimension recommendation: **256D**.

Provide Advanced Settings: - 768D --- maximum retrieval quality; - 512D
--- high quality; - 256D --- recommended/default; - 128D --- compact
text-only mode.

Changing embedding model or vector dimension invalidates the
corresponding old vectors. The application must detect this and offer
reindexing rather than mixing incompatible vectors.

Use the correct EmbeddingGemma task prefixes for query/document
retrieval.

## 3.2 Optional future models

The architecture must expose an `EmbeddingProvider` interface so
additional local models can be added later without changing the
indexing/search/UI layers.

Never require cloud inference.

------------------------------------------------------------------------

# 4. Portable application requirements

The application must run from an arbitrary writable directory and must
not require Conda.

Recommended application layout:

``` text
SemanticXFind/
├── SemanticXFind.exe
├── app/
├── runtime/
├── models/
│   └── embeddinggemma-2/
├── cache/
├── logs/
├── config/
│   ├── settings.json
│   └── catalogs.json
├── locales/
│   ├── en.json
│   ├── ru.json
│   ├── fr.json
│   └── es.json
├── docs/
│   ├── manual_en.html
│   └── manual_ru.html
└── temp/
```

All application-managed models, runtimes, settings, logs and temporary
data must stay inside the application directory unless the user
explicitly changes a path.

No mandatory writes to: - system Python; - Program Files; - Windows
registry; - user-wide Python packages.

Gracefully handle the application being placed in a non-writable
directory.

------------------------------------------------------------------------

# 5. Catalog and index storage

For every indexed root directory, prefer a hidden/local index directory:

``` text
<indexed-root>/
└── .semantic_index/
    ├── manifest.sqlite
    ├── vectors/
    ├── metadata/
    ├── index.json
    └── lock
```

However, not every indexed directory is writable. Support two storage
modes:

### Local index

Store `.semantic_index` inside the indexed root.

Advantages: - moves with the folder; - easy portability; - immediately
detectable when the folder is added again.

### Central index

Store under:

``` text
<Application>/indexes/<catalog-id>/
```

Use this for: - read-only folders; - network shares; - removable media
where writing is undesirable; - user preference.

The catalog record must contain a stable ID and canonical root path.

------------------------------------------------------------------------

# 6. Never rely only on "folder already indexed"

Implement file-level incremental indexing.

For every indexed file store at minimum:

``` text
canonical_path
relative_path
file_id
size
mtime_ns
fast_hash
full_hash_if_needed
extractor_version
embedding_model_id
embedding_dimension
index_schema_version
last_indexed_at
status
```

On rescan: - unchanged -\> skip; - new -\> index; - modified -\> remove
old chunks and reindex; - deleted -\> remove vectors and metadata; -
renamed/moved -\> detect when practical through hash and update
metadata; - extractor/model/schema changed -\> selectively reindex
affected files.

This is critical for large directories.

------------------------------------------------------------------------

# 7. Directory management UI

Create a dedicated **Catalogs** panel/window.

Each catalog row/card should display: - folder name; - full path; -
status; - number of indexed files; - number of semantic chunks; - index
size; - last indexed time; - selected extensions; - wildcard filters; -
model used; - index storage location.

Statuses: - green check --- Ready / indexed; - blue progress ---
Indexing; - yellow --- Changes detected / update recommended; - red ---
Error; - gray --- Offline/unavailable.

Actions: - Add folder; - Remove from application; - Rescan; - Update
index; - Rebuild index; - Pause indexing; - Open folder; - Index
settings; - Delete index; - Show errors.

Removing a catalog must **not automatically delete its index**. Ask
separately.

------------------------------------------------------------------------

# 8. Add Folder wizard

When adding a directory, show a compact wizard.

## Step 1 --- Folder

Select root directory.

Immediately detect: - existing `.semantic_index`; -
compatible/incompatible index version; - existing central index; -
writable/read-only status.

If a compatible index exists: - do not blindly reindex; - register it; -
verify manifest; - optionally scan for changes.

## Step 2 --- File types

Provide presets:

### ComfyUI

`*.json`

### Text/Documents

`*.txt, *.md, *.rst, *.html, *.htm`

### Source code

`*.py, *.js, *.ts, *.cpp, *.h, *.cs, *.java, *.rs, *.go, *.bat, *.ps1, ...`

### Images

future multimodal mode

### Audio

future multimodal mode

### Video

future multimodal mode

### Custom

User-selectable extensions.

Allow include masks:

``` text
*upscale*
qwen_*.json
workflow_??.json
```

Allow exclusion masks:

``` text
*.backup.json
*_temp*
node_modules/*
.git/*
.semantic_index/*
```

Support `*` and `?` using Windows-like glob semantics.

Never index `.semantic_index` itself.

## Step 3 --- Options

-   Recursive scan: ON by default
-   Follow symbolic links/junctions: OFF by default
-   Hidden files: OFF by default
-   Maximum file size
-   Index storage: Auto / Local / Central
-   Embedding dimension
-   Specialized parsing: Auto

Show an estimate before starting: - matching file count; - total source
size; - expected index mode.

------------------------------------------------------------------------

# 9. ComfyUI JSON specialized extractor

This is a core feature.

Do not merely embed raw JSON.

Support both common ComfyUI workflow/API JSON structures where
practical.

Extract:

### Identity

-   filename;
-   workflow title if present;
-   path;
-   created/modified dates.

### Nodes

-   node ID;
-   node type/class;
-   title;
-   properties;
-   widget values;
-   model filenames;
-   LoRA filenames;
-   ControlNet names;
-   sampler/scheduler names;
-   upscale model names;
-   relevant numeric parameters.

### Graph structure

-   incoming/outgoing connections;
-   important chains;
-   groups;
-   bypass/mute state where represented;
-   functional neighborhoods/subgraphs.

### Semantic normalization

Create a deterministic normalized description such as:

``` text
File: Qwen_arch_test_04.json
Type: ComfyUI workflow
Models: Qwen Image 2.1
Operations: image-to-image, upscale, tiled processing
Relevant nodes:
- QwenImageModelLoader
- ImageScale
- UltimateSDUpscale
- VAEDecodeTiled
Pipeline:
Load image -> Qwen processing -> tiled upscale -> tiled VAE decode -> save image
Capabilities:
high-resolution upscale; tiled processing; reduced peak VRAM usage
```

Do not invent capabilities solely from filenames. Maintain a
rule/knowledge registry mapping known node types and graph patterns to
semantic concepts.

Unknown nodes should still be indexed by their exact type, title, widget
values and graph neighborhood.

### Multiple semantic records per workflow

Generate: - workflow overview; - one record per meaningful group; - one
record per detected functional pipeline; - optional records around
important model/processing nodes.

All records reference the same source JSON and optionally node/group
IDs.

------------------------------------------------------------------------

# 10. Optional semantic enrichment

Do not make a generative LLM mandatory for v1.

First implement: - deterministic parser; - domain dictionaries/rules; -
EmbeddingGemma 2.

Design an optional `SemanticEnricher` interface for future local LLM
enrichment.

If enabled later, a local LLM may create a short workflow description
once during indexing, but: - raw structured facts remain
authoritative; - generated text must be marked as generated; - the index
must remain functional without the LLM.

This avoids making indexing slow and unnecessarily VRAM-heavy.

------------------------------------------------------------------------

# 11. Chunking

Implement extractor-specific chunking.

### Text

Use token-aware chunks with overlap.

Starting defaults: - target: \~500--900 tokens; - overlap: \~80--150
tokens; - preserve headings and paragraph boundaries.

### Source code

Chunk by semantic structure where possible: - class; - function; -
method; - module-level block.

Include symbol name and relative path in the embedding document.

### JSON

Use specialized structural chunks, not arbitrary character windows.

### Small files

If the semantic content fits comfortably, a whole-file record is allowed
in addition to specialized records.

Chunking configuration must be versioned so changes can trigger
reindexing.

------------------------------------------------------------------------

# 12. Vector/search storage

Abstract vector storage behind a `VectorStore` interface.

For a fully portable single-user desktop application, avoid requiring a
separately installed database server.

Preferred v1 design: - embedded/local ANN index; - SQLite for manifests,
metadata and FTS; - vector index stored in the catalog index directory.

Qdrant can be supported later as an optional backend, but it should not
be mandatory for the portable desktop version unless an embedded/local
distribution is proven simpler and robust.

The user should never need to start a database service manually.

------------------------------------------------------------------------

# 13. Hybrid search --- strongly recommended

Do not rely exclusively on vector similarity.

Combine:

1.  semantic vector search;
2.  exact/lexical full-text search;
3.  filename/path matching;
4.  structured metadata filters;
5.  ComfyUI entity matching.

Example query:

> "tiled upscale with Qwen 2.1"

The system should recognize: - entity/model: Qwen 2.1; - operation:
upscale; - technique: tiled.

Exact model hits and known structural evidence should increase ranking
while vector similarity captures semantic variations.

Suggested conceptual score:

``` text
final_score =
    semantic_score * W_semantic
  + lexical_score * W_lexical
  + entity_score * W_entity
  + structure_score * W_structure
  + filename_score * W_filename
```

Weights must be configurable internally and validated using real
retrieval tests.

------------------------------------------------------------------------

# 14. Search UI

The primary window should be search-first.

Suggested layout:

``` text
┌──────────────────────────────────────────────────────────────┐
│ SemanticX Find                         Settings  Help  │
├──────────────────────────────────────────────────────────────┤
│ 🔎 Search files by meaning...                               │
│ [All catalogs ▼] [All types ▼] [Filters]          [Search]  │
├──────────────────────────────────────────────────────────────┤
│  24 results • 38 ms                                         │
│                                                              │
│  96%  Qwen21_Architecture_Upscale_v4.json                   │
│       D:\Workflows\Qwen\                                     │
│       Qwen Image 2.1 • tiled upscale • architecture          │
│       [Open File] [Open Folder] [Show in Catalog]            │
│                                                              │
│  91%  qwen_tiles_test.json                                   │
│       ...                                                    │
└──────────────────────────────────────────────────────────────┘
```

Search should begin quickly and may optionally debounce while typing.

Do not overstate similarity as a scientifically meaningful percentage
unless properly calibrated. Prefer a relevance indicator or normalized
score; if percentage is shown, label it "Relevance".

------------------------------------------------------------------------

# 15. Result behavior requested by product owner

Every result must offer:

### Open file

Open using the Windows-associated application.

### Open folder

Open Windows Explorer and select/highlight the source file.

### Show in Catalog

Switch the application's file/catalog view to the corresponding catalog
and apply a temporary result filter containing the matched files.

### Clear result filter

Prominent button/chip:

`Clear search filter`

After clearing, show all files in that catalog.

Also add: - Copy full path; - Copy filename; - Copy containing folder; -
Show indexed semantic details; - Show why this matched; - Reindex this
file.

For ComfyUI JSON optionally: - Open in configured ComfyUI URL; - Copy
workflow path.

Do not depend on ComfyUI integration for core functionality.

------------------------------------------------------------------------

# 16. "Why this matched" --- recommended differentiator

Add an expandable explanation to each result.

Example:

``` text
Matched because:
✓ Model: Qwen Image 2.1
✓ Tiled processing detected
✓ Upscale pipeline detected
✓ Semantic similarity: high

Relevant workflow section:
UltimateSDUpscale -> Qwen processing -> VAEDecodeTiled
```

This is extremely valuable because semantic search otherwise feels
opaque.

------------------------------------------------------------------------

# 17. Filters

Provide filters for: - catalog; - extension/type; - modified date; -
size; - filename/path; - ComfyUI model; - ComfyUI node type; - semantic
category; - minimum relevance; - indexed status.

Active filters must be visible as removable chips.

------------------------------------------------------------------------

# 18. Model Manager

Create a dedicated **Models** page.

For each model show: - model name; - purpose; - installed/not
installed; - download size; - installed size; - version/revision; -
storage path; - verification status; - supported modalities.

Actions: - Download; - Pause/resume where supported; - Retry; -
Verify; - Delete; - Update; - Open model folder.

Requirements: - models live under `<app>/models/`; - downloads use
`.part` temporary files; - resume interrupted downloads where
possible; - verify expected files/checksums or repository metadata; -
never mark a model installed after partial download; - show download
speed/progress; - cleanly report network/authentication errors.

EmbeddingGemma 2 must be downloadable from the UI.

The program must be able to start without the model and direct the user
to Model Manager when indexing/search requires it.

------------------------------------------------------------------------

# 19. Hardware acceleration

Implement automatic backend detection.

Priority: 1. NVIDIA CUDA when available and compatible; 2. CPU fallback.

Display active backend: `NVIDIA GeForce RTX ... — CUDA — BF16` or
`CPU — FP32`.

Advanced settings: - Auto; - CUDA; - CPU; - batch size; - embedding
dimension.

Use adaptive batching. Avoid hardcoding batch size for a high-end GPU.

If CUDA initialization fails, provide a readable error and offer CPU
mode rather than crashing.

------------------------------------------------------------------------

# 20. Indexing UX

Indexing must run outside the UI thread.

Show: - current folder; - current file; - files processed / total; -
chunks embedded; - files skipped; - errors; - elapsed time; -
throughput; - ETA where stable; - Pause; - Resume; - Cancel.

Use a pipeline:

``` text
scanner -> extractor workers -> chunk queue -> embedding batches -> writer
```

Do not let parsing block GPU embedding and do not let database writes
block the UI.

Commit progress incrementally. A crash or cancellation must not corrupt
the entire index.

------------------------------------------------------------------------

# 21. File watching

Recommended optional feature:

`Watch folder for changes`

When enabled: - use Windows filesystem notifications; - debounce
bursts; - queue changed/new files; - remove deleted files; - do not
immediately reindex partially written files; - retry after file write
settles.

Also retain a manual `Scan for changes` action because filesystem
notifications are not guaranteed across every network/removable
filesystem.

------------------------------------------------------------------------

# 22. Search history and favorites

Recommended: - recent searches; - pin/favorite searches; - favorite
files; - optional search history OFF switch; - clear history.

All data remains local.

------------------------------------------------------------------------

# 23. Duplicate detection

Since embeddings and hashes already exist, add optional duplicate
tools: - exact duplicate files by hash; - near-duplicate semantic
files; - duplicate/near-duplicate ComfyUI workflows.

Do not delete automatically.

------------------------------------------------------------------------

# 24. Privacy

The default product is local-first.

Clearly state: - indexing is local; - search is local; - files are not
uploaded for inference.

Network access should be needed only for explicit actions such as
downloading/updating models or checking application updates.

No telemetry by default.

------------------------------------------------------------------------

# 25. Internationalization

Supported UI languages: - English (default) - Russian - French - Spanish

No user-visible strings should be hardcoded in widgets.

Use locale resource files with stable keys:

``` json
{
  "search.placeholder": "Search files by meaning...",
  "catalog.status.ready": "Ready"
}
```

Language switching should not require reinstalling.

Persist selection in portable settings.

------------------------------------------------------------------------

# 26. Built-in Help / Manual

Provide `Help -> User Guide`.

Languages: - English; - Russian.

Default manual follows current language when English/Russian; for
French/Spanish default to English unless translated manuals are later
added.

Manual topics: 1. What semantic search is; 2. First launch; 3.
Downloading EmbeddingGemma 2; 4. Adding a catalog; 5. File extensions;
6. `*` and `?` wildcard examples; 7. Indexing; 8. Updating an index; 9.
Searching in natural language; 10. Search filters; 11. Opening results;
12. ComfyUI workflow search; 13. Model Manager; 14. GPU/CPU modes; 15.
Index storage; 16. Backup/moving portable installation; 17.
Troubleshooting; 18. Privacy.

Manual must be viewable offline.

------------------------------------------------------------------------

# 27. Settings

### General

-   language;
-   theme: System / Light / Dark;
-   start page;
-   remember window state.

### Search

-   result count;
-   hybrid search;
-   search history;
-   default catalog scope.

### Indexing

-   default extensions;
-   chunk settings;
-   watch folders;
-   index storage policy;
-   max file size.

### Models

-   active embedding model;
-   vector dimension;
-   compute device;
-   batch size;
-   model directory.

### Advanced

-   logging level;
-   diagnostics;
-   reset UI settings;
-   rebuild search metadata.

------------------------------------------------------------------------

# 28. Modern UI requirements

Use a native-feeling Windows desktop interface.

Recommended implementation direction: **PySide6 / Qt 6** for rapid
development, strong Windows support, mature threading, localization and
a practical portable Python distribution.

Alternative: .NET 8 + WinUI/WPF with a Python/local inference worker,
but this increases packaging complexity. Do not choose it unless testing
demonstrates a clear deployment advantage.

Visual requirements: - clean spacing; - rounded but restrained
components; - dark/light themes; - high-DPI support; - keyboard
navigation; - clear empty states; - responsive resize behavior; - no
blocking modal dialogs for routine operations; - subtle progress
feedback; - accessibility-conscious contrast; - no cyberpunk/gaming
visual clutter.

Use icons consistently and provide text tooltips.

------------------------------------------------------------------------

# 29. Recommended technology stack

Initial recommendation:

``` text
UI:                 PySide6 / Qt 6
Language:           Python 3.11/3.12 portable runtime
Embedding:          sentence-transformers + transformers
Model:              google/embeddinggemma-2
GPU:                PyTorch CUDA
Metadata DB:        SQLite
Lexical search:     SQLite FTS5
Vector search:      embedded ANN backend behind abstraction
File watching:      watchdog or native Qt filesystem facilities
Config:             JSON or TOML
Logging:            rotating local logs
Packaging:          tested portable bundle
Tests:              pytest
```

Before final packaging, benchmark alternative ANN libraries on Windows
and choose based on: - reliable wheels/build; - persistence; -
incremental insert/delete; - memory mapping; - filtering strategy; -
crash recovery; - license; - startup time.

Do not lock the domain layer to a specific vector library.

------------------------------------------------------------------------

# 30. Database concept

SQLite tables may include:

``` text
catalogs
files
chunks
entities
file_entities
index_jobs
settings_metadata
errors
```

Example `files` fields:

``` text
id
catalog_id
relative_path
canonical_path
extension
size
mtime_ns
content_hash
extractor
extractor_version
status
last_indexed_at
```

Example `chunks`:

``` text
id
file_id
chunk_type
ordinal
title
text
start_locator
end_locator
vector_id
```

For ComfyUI locators store node/group IDs.

Use SQLite FTS5 for searchable chunk text and filenames.

------------------------------------------------------------------------

# 31. Index compatibility metadata

Every index must record:

``` json
{
  "schema_version": 1,
  "app_version": "...",
  "embedding_model": "google/embeddinggemma-2",
  "model_revision": "...",
  "embedding_dimension": 256,
  "normalization": "l2",
  "distance": "cosine",
  "extractor_versions": {
    "comfyui_json": 1,
    "text": 1,
    "python": 1
  }
}
```

Never silently open an incompatible index as writable.

Implement migrations where safe; otherwise offer rebuild.

------------------------------------------------------------------------

# 32. Error handling

A malformed file must not abort a catalog job.

Record per-file errors and continue.

Examples: - invalid JSON; - permission denied; - file disappeared during
scan; - unsupported encoding; - out of memory; - CUDA failure; - model
unavailable; - index locked; - disk full.

Expose an `Errors` panel with: - filename; - error summary; - retry; -
copy diagnostics.

Logs must avoid dumping full private file contents unnecessarily.

------------------------------------------------------------------------

# 33. Security and robustness

-   Treat indexed files as untrusted data.
-   Never execute code from indexed files.
-   Never evaluate JSON.
-   Avoid unsafe pickle formats for application metadata.
-   Normalize and validate paths.
-   Protect against symlink/junction recursion.
-   Use atomic writes for manifests/config.
-   Use file locks for indexes.
-   Sanitize HTML shown in help/result previews.
-   Verify downloaded model artifacts.
-   Never shell-execute a path assembled from untrusted file contents.

------------------------------------------------------------------------

# 34. Performance goals

Define measurable targets rather than vague "fast".

Suggested initial goals on a modern desktop: - UI startup without model
loading: \< 2 s target; - search UI remains responsive during
indexing; - already-loaded query embedding + ANN retrieval: interactive
latency; - cached index opens without re-embedding; - unchanged rescan
skips \>99% of files without reading entire contents where metadata is
sufficient; - batch embedding saturates available GPU reasonably; -
memory usage bounded for catalogs with hundreds of thousands of files.

Benchmark separately: - cold model load; - warm query latency; -
files/sec extraction; - chunks/sec embedding; - ANN query latency; -
index disk usage.

Do not claim specific performance until measured.

------------------------------------------------------------------------

# 35. Search quality benchmark

Create a retrieval benchmark before optimization.

For the ComfyUI dataset create queries such as:

``` text
"Where did I use tiled upscale with Qwen Image 2.1?"
"workflow with Qwen and OpenPose"
"SUPIR tiled processing"
"workflow for architectural render upscale"
"face restoration after upscale"
```

For every query manually identify relevant workflow(s).

Measure: - Recall@1; - Recall@5; - Recall@10; - MRR; - failure
categories.

Compare: 1. filename search; 2. lexical search; 3. embeddings only; 4.
hybrid search; 5. hybrid + ComfyUI structural signals.

Do not fine-tune EmbeddingGemma until this benchmark shows a real need.

------------------------------------------------------------------------

# 36. Recommended additional features

## High priority

-   drag-and-drop folder addition;
-   keyboard shortcut `Ctrl+K` / `Ctrl+F` to focus search;
-   search-as-you-type with debounce;
-   file preview/details side panel;
-   "Why matched";
-   incremental indexing;
-   folder watching;
-   index health check;
-   export/import catalog configuration.

## Medium priority

-   saved searches;
-   favorites;
-   duplicate detection;
-   tag files manually;
-   custom aliases/synonyms.

Example custom synonym dictionary:

``` text
qwen21 = Qwen Image 2.1
supir = SUPIR
tile = tiled, tiling, tiled processing
openpose = pose control, skeleton pose
```

These aliases can improve hybrid retrieval without model fine-tuning.

## Future

-   image semantic search;
-   audio/video semantic search;
-   transcript integration;
-   cross-modal search;
-   optional local reranker;
-   optional local LLM workflow summaries;
-   ComfyUI integration/API;
-   plugin/extractor SDK.

------------------------------------------------------------------------

# 37. Development phases

## Phase 0 --- Research spike

Before production UI: 1. load EmbeddingGemma 2 text-only on Windows; 2.
verify CUDA BF16 and CPU FP32; 3. index a sample of real ComfyUI JSON;
4. compare raw JSON vs normalized structural descriptions; 5. benchmark
256D vs 768D; 6. evaluate candidate embedded ANN libraries; 7. prove
persistence and incremental updates.

Deliver a short benchmark report.

## Phase 1 --- Search engine prototype

Implement: - catalog scanner; - glob filters; - file manifest; - ComfyUI
extractor; - text/code extractors; - chunking; - EmbeddingGemma; -
vector store; - SQLite FTS5; - hybrid ranking; - CLI tests.

No polished GUI yet.

Acceptance test: A natural-language query reliably retrieves known
relevant workflows.

## Phase 2 --- Desktop MVP

Implement: - main search window; - Catalogs; - Add Folder wizard; -
indexing progress; - result actions; - filters; - Model Manager; -
settings; - English UI.

## Phase 3 --- Portability and reliability

Implement: - portable packaging; - first-run flow; -
download/resume/verify models; - crash-safe indexing; - central/local
index modes; - CPU fallback; - Windows 10/11 tests; - high-DPI tests; -
long-path tests; - non-ASCII path tests.

## Phase 4 --- Localization and documentation

Add: - Russian; - French; - Spanish; - English manual; - Russian manual.

Test layouts for translated strings.

## Phase 5 --- Quality/performance

Benchmark: - large catalogs; - incremental scans; - GPU batches; - index
size; - warm/cold search; - ranking quality.

Tune only from measurements.

## Phase 6 --- Multimodal extension

Add EmbeddingGemma 2 vision/audio/video encoders as optional
downloadable/activatable capabilities.

Do not force users who only search text/JSON to load unnecessary
modality encoders.

------------------------------------------------------------------------

# 38. LLM agent implementation rules

The coding agent must follow these rules.

1.  **Do not implement the whole application as one file.**
2.  Use clear modules and interfaces.
3.  Keep UI, domain logic, inference and persistence separated.
4.  Do not block the Qt UI thread.
5.  Do not add cloud dependencies unless explicitly approved.
6.  Do not hardcode absolute development paths.
7.  Do not install dependencies into system Python.
8.  Preserve portability.
9.  Write tests alongside core logic.
10. Do not claim a feature works until it has an automated or manual
    verification step.
11. Do not replace structural ComfyUI parsing with an LLM prompt.
12. Never execute indexed source files.
13. Every schema/index format must be versioned.
14. Every long-running operation must support cancellation where
    practical.
15. Every user-visible string must be localizable.
16. Avoid premature fine-tuning.
17. Profile before optimizing.
18. Keep optional multimodal dependencies modular.
19. Maintain a changelog of architectural decisions.
20. At the end of each phase, build and run the application on a clean
    Windows portable environment.

------------------------------------------------------------------------

# 39. Suggested source tree

``` text
src/
├── app.py
├── ui/
│   ├── main_window.py
│   ├── search_page.py
│   ├── catalogs_page.py
│   ├── models_page.py
│   ├── settings_page.py
│   ├── help_viewer.py
│   ├── dialogs/
│   └── widgets/
├── domain/
│   ├── models.py
│   ├── catalog.py
│   ├── search.py
│   └── indexing.py
├── indexing/
│   ├── scanner.py
│   ├── manifest.py
│   ├── pipeline.py
│   ├── chunking.py
│   └── extractors/
│       ├── base.py
│       ├── text.py
│       ├── source_code.py
│       ├── json_generic.py
│       └── comfyui.py
├── embeddings/
│   ├── base.py
│   ├── embeddinggemma2.py
│   └── model_manager.py
├── search/
│   ├── engine.py
│   ├── lexical.py
│   ├── vector.py
│   ├── hybrid.py
│   └── explain.py
├── storage/
│   ├── sqlite.py
│   ├── vector_store.py
│   ├── migrations.py
│   └── locks.py
├── platform/
│   ├── windows.py
│   └── paths.py
├── i18n/
├── docs/
└── tests/
```

------------------------------------------------------------------------

# 40. MVP acceptance criteria

The MVP is accepted only when all of the following work:

-   App starts portably on Windows 10/11.
-   User can download EmbeddingGemma 2 from Model Manager.
-   User can add multiple directories.
-   Each directory remembers extensions and wildcard masks.
-   Existing compatible index is detected.
-   Repeated scan does not re-embed unchanged files.
-   Modified/new/deleted files are handled correctly.
-   Completed catalogs show a green Ready indicator.
-   ComfyUI JSON is parsed structurally.
-   Natural-language semantic search returns relevant JSON workflows.
-   Search spans one or all catalogs.
-   Results show filename, path and useful semantic context.
-   User can open the file.
-   User can open Explorer with the file selected.
-   User can filter catalog view to result files and clear that filter.
-   Index persists across restarts.
-   English/Russian/French/Spanish UI switching works.
-   English and Russian offline manuals open from Help.
-   CPU fallback works when CUDA is unavailable.
-   Indexing never freezes the UI.
-   Individual bad files do not abort the entire indexing job.
-   No internet connection is required after models are installed.

------------------------------------------------------------------------

# 41. Definition of Done for v1.0

Before declaring v1.0 complete:

1.  Run unit tests.
2.  Run integration tests with real ComfyUI workflows.
3.  Test at least one large catalog.
4.  Test paths containing Cyrillic, accented Latin characters, spaces
    and long paths.
5.  Test interrupted model download.
6.  Test interrupted indexing.
7.  Test index recovery/restart.
8.  Test missing/removable catalog.
9.  Test GPU and CPU modes.
10. Test clean Windows 10 and Windows 11 machines/VMs.
11. Benchmark retrieval quality.
12. Benchmark search latency.
13. Verify no unexpected writes outside the portable app/index
    directories.
14. Verify offline operation.
15. Review all four UI localizations.
16. Review both manuals.
17. Produce a portable release archive with versioned checksums.

------------------------------------------------------------------------

# 42. Key product decisions

Use these defaults unless benchmark evidence justifies changing them:

-   Product scope: universal local semantic file search with specialized
    ComfyUI support.
-   Primary model: EmbeddingGemma 2.
-   Initial modalities: text/code/JSON.
-   EmbeddingGemma configuration: text-only encoders for initial
    indexing.
-   Vector dimension: 256D default.
-   Retrieval: hybrid, not vector-only.
-   ComfyUI: structural parsing + semantic embedding.
-   Indexing: chunk-level and incremental.
-   Index storage: local `.semantic_index` with central fallback.
-   Metadata/lexical DB: SQLite + FTS5.
-   Vector backend: embedded and abstracted.
-   UI: PySide6/Qt 6.
-   Cloud: none required.
-   Fine-tuning: not part of v1.
-   Multimodal indexing: planned extension after the text/JSON engine is
    proven.

------------------------------------------------------------------------

# 43. Primary implementation objective for the coding agent

Do not begin by polishing the UI.

First prove the core retrieval hypothesis with real data:

> Given a directory containing ComfyUI workflow JSON files, the system
> must return the correct workflows for semantic natural-language
> questions such as "Where did I make tiled upscale with Qwen Image
> 2.1?" even when filenames and exact wording do not match the query.

Only after retrieval quality, incremental persistence and portable
inference are verified should the agent proceed to the full desktop
interface.

This ordering is mandatory because search quality is the product; the
GUI is the interface to it.

---

# 44. PNG-embedded ComfyUI workflow indexing (required)

The application must support ComfyUI workflows embedded in PNG metadata, not only standalone `.json` workflows.

For every indexed PNG, inspect metadata for known ComfyUI workflow/prompt payloads. If a valid embedded workflow is found:

1. extract the embedded JSON safely without executing anything;
2. preserve the original PNG as the source file;
3. pass the extracted workflow through the same specialized ComfyUI parser used for standalone JSON;
4. index workflow overview, models, nodes, widget values, groups, graph structure, functional pipelines and detected capabilities;
5. retain metadata linking every semantic record back to the PNG source;
6. expose in result details that the workflow was extracted from PNG metadata;
7. allow opening Explorer with the PNG selected and viewing extracted workflow details;
8. do not create a separate JSON file unless the user explicitly chooses an Export Workflow action.

Index both the embedded workflow and the visible PNG image as independent semantic representations when visual indexing is enabled.

A single PNG may therefore match searches for either its workflow or its visible content.

Example:

```text
result_014.png
├── visual content
│   └── photorealistic architectural render
└── PNG metadata
    └── ComfyUI workflow
        ├── Qwen Image 2.1
        ├── tiled upscale
        ├── ControlNet
        └── SaveImage
```

A query about "architectural render" may match visual content, while "Qwen 2.1 tiled upscale" may match the embedded workflow.

PNG metadata parsing must be tolerant of missing, malformed, legacy and third-party metadata. Failure to parse metadata must not prevent visual indexing of the PNG.

# 45. Multimodal visual indexing

Add optional visual semantic indexing for supported image formats.

Initial image types:
- PNG
- JPG/JPEG
- WEBP

Use the EmbeddingGemma 2 vision capability so image embeddings occupy a compatible/shared semantic space with supported query modalities.

Visual indexing must be optional per catalog. Users who only need JSON/text/code search must not be forced to download/load unnecessary visual components.

For an image containing a ComfyUI workflow in PNG metadata, create at least two independent searchable channels:

```text
IMAGE FILE
├── visual_embedding
└── workflow_metadata_embeddings
```

Do not merge these into one vector.

Store modality/type metadata for every vector so ranking can distinguish visual similarity from workflow-semantic similarity.

The UI should indicate why an image matched, for example:

```text
Matched by:
✓ Embedded ComfyUI workflow
✓ Model: Qwen Image 2.1
✓ Tiled upscale detected
○ Visual similarity: medium
```

or:

```text
Matched by:
✓ Visual similarity: high
○ No ComfyUI workflow metadata detected
```

# 46. Image-based search

The main search interface must support attaching one or more query images.

Supported input methods:
- `Attach image` button;
- drag-and-drop image onto the search area;
- paste image from clipboard (`Ctrl+V` when search area is active);
- built-in screenshot capture.

The user must be able to search with:

1. text only;
2. image only;
3. text + image.

Example combined query:

```text
[attached screenshot of a ComfyUI node]
"Where did I use this together with Qwen Image 2.1?"
```

The search engine must combine visual evidence, extracted visual text/entity evidence where available, textual query semantics, structured ComfyUI metadata and lexical/entity matches.

Do not simply average vectors blindly. Implement multimodal score fusion with independently inspectable score components.

# 47. Screenshot capture search tool

Add a built-in Windows screenshot-region tool accessible directly from the search bar.

Suggested controls:

```text
[ Search files by meaning...                     ]
[Search] [Attach Image] [Screenshot]
```

When `Screenshot` is activated:

1. temporarily hide/minimize the application as appropriate;
2. display a translucent full-screen selection overlay across available monitors;
3. let the user drag-select a rectangular region;
4. `Esc` cancels;
5. capture the selected pixels;
6. restore the application;
7. attach the capture automatically to the current search query;
8. show a removable thumbnail before search executes.

Support Windows multi-monitor configurations and DPI scaling correctly.

The screenshot should normally remain in memory or temporary application storage and should not be permanently saved unless the user chooses `Save screenshot`.

Provide keyboard shortcut configurable later; suggested default: `Ctrl+Shift+S` while the application is active.

# 48. Screenshot-of-node workflow search

A major target use case is locating ComfyUI workflows from a screenshot of a node or part of a graph.

Example:

```text
User captures:
┌────────────────────────────┐
│ Ultimate SD Upscale        │
│ upscale_by     2.0         │
│ tile_width     1024        │
│ tile_height    1024        │
│ denoise        0.25        │
└────────────────────────────┘
```

The application should attempt to find workflows containing the same or semantically equivalent node/function.

Use multiple retrieval signals:

```text
SCREENSHOT
    │
    ├── visual embedding ───────────────┐
    │                                   │
    ├── lightweight text recognition ───┤
    │                                   │
    ├── detected node/model terms ──────┤
    │                                   ▼
    └──────────────────────────── HYBRID RANKER
                                        │
                              indexed workflows/PNGs
```

Visual similarity alone is not sufficient because many ComfyUI nodes have similar visual appearance.

Extracting visible node titles/model names/parameter labels can strongly improve retrieval. Implement this as a modular `ImageQueryAnalyzer` so OCR or another local vision/text-recognition backend can be changed later.

Do not require OCR for the first visual-search prototype if it delays core image embeddings, but preserve the interface and add it before declaring screenshot-to-node search production-ready.

Any OCR/vision model used must follow the same portable model-management rules: downloadable from the application, stored under the application model directory, removable/updateable through Model Manager, and usable locally without cloud inference.

# 49. Multimodal hybrid ranking

Extend the hybrid ranking system with separate evidence channels:

- query text semantic similarity;
- query image visual similarity;
- OCR/text extracted from query image;
- exact model/entity matches;
- ComfyUI node matches;
- workflow graph/structure evidence;
- filename/path lexical evidence;
- embedded PNG workflow evidence;
- optional visual content evidence.

Conceptual model:

```text
final_score = fusion(
    text_semantic,
    image_semantic,
    query_image_text,
    exact_entities,
    node_matches,
    workflow_structure,
    lexical,
    visual_content
)
```

Do not hardcode final weights without evaluation. Create a benchmark containing text-only, image-only and text+image queries and tune from measured retrieval quality.

Result explanations must expose the strongest matching signals.

# 50. Multimodal catalog settings

Extend Add Folder / Catalog Settings with indexing capabilities:

```text
Content to index
☑ ComfyUI workflows (.json)
☑ ComfyUI workflows embedded in PNG metadata
☑ Text / source code
☑ Image visual content
☐ Audio (future)
☐ Video (future)
```

If visual indexing is enabled but required vision model components are not installed, offer:

`Download required model component`

Do not silently begin a large model download.

The catalog summary should show separate counts where useful:

```text
Files: 18,420
Standalone workflows: 3,210
PNG embedded workflows: 5,840
Visually indexed images: 9,370
Semantic records: 46,201
```

# 51. Model Manager multimodal components

Model Manager must distinguish installed capabilities rather than presenting EmbeddingGemma 2 as an all-or-nothing black box.

Show, where technically supported by the selected runtime:

```text
EmbeddingGemma 2
✓ Text / Code
✓ Vision
○ Audio
○ Video
```

If the runtime/package requires downloading a shared checkpoint containing multiple components, explain that accurately rather than pretending each component is a separate checkpoint.

The application architecture must still allow loading only the components needed for the active operation where supported.

# 52. Visual query privacy

Screenshots and attached query images are private local query material.

Default behavior:
- do not upload;
- do not permanently store;
- remove temporary captures after use/application exit;
- do not add query screenshots to indexed catalogs unless explicitly requested;
- do not include image bytes in normal logs.

# 53. Updated MVP / staged scope

To control risk, implement multimodal features in this order:

## MVP-A — workflow retrieval core
- standalone ComfyUI JSON;
- PNG-embedded ComfyUI workflow extraction;
- text/code indexing;
- EmbeddingGemma 2 text embeddings;
- hybrid lexical/entity/structural search;
- incremental persistent index.

## MVP-B — visual search
- visual image indexing;
- attach image;
- drag/drop image;
- clipboard paste;
- image-only retrieval;
- text + image fusion.

## MVP-C — screenshot-to-workflow
- region screenshot capture;
- multi-monitor/DPI correctness;
- automatic attachment;
- local text/node recognition from screenshot;
- node/entity-aware reranking;
- "Why matched" explanation.

Do not block MVP-A on screenshot/OCR engineering, but all interfaces and storage schemas must anticipate MVP-B/C so no architectural rewrite is required.

# 54. Additional multimodal acceptance criteria

The relevant phase is not complete until these tests pass:

1. A ComfyUI workflow saved only inside PNG metadata is discoverable by a natural-language workflow query.
2. Re-indexing the same PNG without changes does not regenerate embeddings.
3. Changing only PNG workflow metadata causes the workflow representation to update correctly.
4. Changing image pixels causes the visual representation to update correctly.
5. An image can be attached to the search bar.
6. An image can be pasted from clipboard.
7. A screenshot region can be captured and attached automatically.
8. Screenshot capture works on Windows scaling above 100% and on multiple monitors.
9. Image-only search returns visually/semantically relevant indexed images.
10. Text + image query can narrow a visual/node query using textual constraints.
11. A screenshot containing a recognizable ComfyUI node can retrieve workflows containing that node/function with useful Top-K quality.
12. Result details distinguish whether the match came from PNG workflow metadata, visual image content, screenshot text/node evidence, or multiple channels.
13. Query screenshots are not persisted by default.
14. Visual indexing can be disabled per catalog.
15. Text-only users are not forced to load vision components.

# 55. Updated product objective

The product should ultimately behave as a local multimodal semantic search engine for technical creative workflows.

It should answer queries such as:

```text
"Where did I use tiled upscale with Qwen Image 2.1?"

"Find workflows containing Qwen and OpenPose."

"Find PNGs whose embedded workflow uses SUPIR."

"Find images visually similar to this reference."

[attach node screenshot]
"Where did I use this node?"

[attach node screenshot]
"Where did I use this together with Qwen Image 2.1?"
```

The primary differentiator is not merely vector search. It is the fusion of:

**filesystem search + ComfyUI graph understanding + PNG workflow metadata + multimodal embeddings + screenshot-driven retrieval + local privacy + portable Windows deployment.**

---

# Product identity and branding

The official product name is:

**SemanticX Find**

The coding agent must use this name consistently in:
- application title;
- main window title;
- executable metadata;
- About dialog;
- documentation;
- first-run screens;
- Model Manager;
- error/diagnostic dialogs;
- release packages.

Do not rename the product or replace it with a generic working title.

## Application logo

Create a distinctive original logo for SemanticX Find.

The logo should communicate:
- semantic/AI search;
- connections/vectors;
- files/data;
- fast discovery.

Visual direction:
- modern;
- professional;
- minimal;
- recognizable at small sizes;
- suitable for both dark and light UI;
- avoid visual similarity to Google, Microsoft, OpenAI, ComfyUI, or other existing product logos;
- avoid overly complex AI-brain clichés.

Prepare scalable/vector source artwork where practical and exported assets for:
- application header;
- Windows executable icon;
- taskbar/window icon;
- About dialog;
- splash/first-run screen if one is later used;
- 16, 24, 32, 48, 64, 128, 256 and 512 px contexts where applicable.

The final Windows executable should contain an appropriate multi-resolution `.ico`.

## Main application header

The primary application shell must visibly identify the product without wasting excessive vertical space.

Suggested header concept:

```text
┌──────────────────────────────────────────────────────────────┐
│ [SemanticX logo]  SemanticX Find                  [—][□][×] │
├──────────────────────────────────────────────────────────────┤
```

The logo and product name should form a coherent brand lockup.

Do not place a huge decorative logo above the working area. Search remains the primary interface.

## About SemanticX Find

Add an accessible menu/action:

`Help -> About SemanticX Find`

The About dialog must contain at minimum:

```text
SemanticX Find
<application version>

Local multimodal semantic file search

Developed by OreX
Founder of StableDif

Website: stabledif.ru
YouTube: StableDif
Rutube: StableDif
```

Developer attribution is authoritative:

**OreX — Founder of StableDif**

Do not replace `OreX` with a real/legal name and do not invent additional developer/company information.

Official project links:

- Website: https://stabledif.ru/
- YouTube: https://www.youtube.com/@StableDiff/videos
- Rutube: https://rutube.ru/channel/28380669/videos/

Links in the About dialog must be clickable and open in the user's default browser.

The About dialog should also contain:
- SemanticX Find logo;
- application version;
- build/version information;
- copyright line using OreX/StableDif branding;
- license information;
- third-party/open-source licenses action;
- `Copy diagnostics` action;
- `Close` action.

Do not imply that StableDif, OreX, SemanticX Find, or this application is affiliated with Google merely because it uses EmbeddingGemma 2.

## Credits and third-party software

Provide a separate `Third-party licenses` view/file.

Clearly distinguish:
- SemanticX Find product/developer attribution;
- third-party libraries;
- AI model licensing and attribution.

EmbeddingGemma 2 attribution/licensing must follow the applicable upstream model terms at release time.

---

# Branding acceptance criteria

The release is not complete until:

- the application is named SemanticX Find everywhere visible to the user;
- the main window contains the SemanticX Find logo and name;
- the Windows executable uses the SemanticX Find icon;
- the taskbar/window icon renders correctly at common Windows DPI settings;
- the logo works on both light and dark themes;
- Help -> About SemanticX Find is present;
- About identifies `OreX — Founder of StableDif`;
- the StableDif website, YouTube and Rutube links are clickable;
- third-party licenses are accessible;
- no temporary/default Qt/Python icon remains in the release build.

