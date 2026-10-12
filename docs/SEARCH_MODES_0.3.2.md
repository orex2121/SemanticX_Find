# Search modes — 0.3.2-alpha

The search toolbar contains a mode selector before search history:

- **Vision only** searches visual image embeddings and ignores embedded PNG text and workflow metadata.
- **Text only** searches filenames, extracted text, metadata, workflow data, and OCR while excluding visual vectors.
- **Vision first, then text** runs Vision first and uses text only when Vision returns no result after all active filters and the minimum-score threshold. This is the default.
- **Text first, then Vision** uses the same fallback rule with text as the primary source.

The priority modes do not merge the two result sets. This prevents weak metadata associations from displacing visually relevant images when Vision already has results.
