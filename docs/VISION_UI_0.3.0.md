# Vision UI foundation — 0.3.0-alpha

- Search displays an explicit Vision status badge: disabled, ready, or model unavailable.
- The badge tooltip shows how many catalogs have visual indexing enabled.
- Settings explain Vision and only allow enabling it with the Gemma search engine.
- Existing catalogs now have an editable settings dialog.
- Catalog settings include extensions, include/exclude masks, recursion, hidden files, size limit, and visual indexing.
- Changing visual indexing saves the catalog configuration and explicitly marks that a rebuild is required; no expensive rebuild starts silently.
