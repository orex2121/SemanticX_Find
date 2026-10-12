# Token-aware semantic chunking — 0.2.19-alpha

- The extractor no longer splits documents at a fixed character count.
- Chunks use a deterministic token-like budget suitable for offline lexical and embedding modes.
- Boundaries prefer paragraphs, then lines, then sentence endings.
- A token overlap keeps concepts visible when they cross a chunk boundary.
- Extremely long unbroken values are subdivided to prevent oversized model input.
- The extractor identity is now `6-token-aware`; existing indexes must be rebuilt so old and new chunk representations are never mixed.
