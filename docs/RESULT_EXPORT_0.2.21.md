# Search-result export — 0.2.21-alpha

- Search results can be exported as UTF-8 CSV or JSON.
- Exports contain ranking order, filename, full/relative paths, catalog ID, final score, size, modification time, and individual `signal_*` ranking fields.
- Full indexed document text is intentionally excluded.
- CSV uses a UTF-8 BOM for convenient Cyrillic display in spreadsheet applications.
- Output is first written to a sibling `.part` file and atomically replaced to avoid incomplete deliverables.
