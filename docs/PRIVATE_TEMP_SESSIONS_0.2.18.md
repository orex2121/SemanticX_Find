# Private temporary image sessions — 0.2.18-alpha

- Clipboard images and screenshots are stored in a unique temporary directory for the current application process.
- The session directory is protected by an inter-process file lock.
- Normal application shutdown deletes temporary captures and the session directory.
- On startup, abandoned unlocked session directories from crashes are removed.
- Locked directories belonging to another running SemanticX Find instance are preserved.
- Legacy top-level `query-*.png` captures older than 24 hours are cleaned up safely.
