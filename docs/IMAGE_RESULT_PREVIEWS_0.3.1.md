# Image result previews — 0.3.1-alpha

- Image results show a 72×72 thumbnail in the results list.
- The selected image is shown in a larger preview above its details.
- Clicking the large preview expands it over the application workspace.
- Clicking the expanded image closes it and returns to the search view.
- Non-image results hide the preview while keeping the normal text details.

Thumbnails are decoded close to their display size with `QImageReader`, avoiding the memory cost of loading every source image at full resolution.
