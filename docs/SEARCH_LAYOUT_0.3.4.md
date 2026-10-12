# Search layout clarity — 0.3.4-alpha

The search page now follows the order in which a search is configured:

1. Choose one or more search catalogs.
2. Choose the Vision/text priority and, optionally, a previous query.
3. Enter the query and press **Search**.
4. Optionally attach reference images.
5. Narrow results with clearly labelled filters.

Every input has a short explanation above it. The former **Vision: ready** badge was removed from the search toolbar; detailed model readiness remains available on the Models tab.

The three advanced text filters mean:

- **Folder or path fragment** — only paths containing the entered text remain.
- **ComfyUI node** — only workflows containing a node type such as `KSampler` remain.
- **ComfyUI model** — only workflows referencing a matching checkpoint, LoRA, UNet, or VAE remain.
