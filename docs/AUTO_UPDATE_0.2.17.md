# Automatic incremental index updates — 0.2.17-alpha

- Settings include an opt-in automatic index update toggle and a 15–3600 second interval.
- Automatic updates run through the existing background worker and keep the UI responsive.
- The normal incremental indexer skips unchanged files and processes additions, modifications, and deletions.
- All registered catalogs are checked in sequence.
- Offline catalogs are reported and preserved rather than purged.
- A timer tick is ignored while another search, indexing, download, or verification job is running.
- Automatic updating is disabled by default.
