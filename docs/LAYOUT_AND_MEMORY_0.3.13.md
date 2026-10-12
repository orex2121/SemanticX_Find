# Layout and model-memory controls — 0.3.13-alpha

- Catalog details and catalog files are stacked in a vertical splitter with a draggable divider.
- Vision and OCR descriptions occupy the form field column beside their switches.
- **Keep model in memory** is enabled by default. Disabling it unloads the provider and clears the CUDA cache after a background operation; it also releases the provider when settings change or the application closes.
- Model action buttons are arranged horizontally beside each model status panel.
- Search results containing no image files temporarily use List view. The preferred thumbnail size remains saved and is restored automatically when a later result set contains images.
