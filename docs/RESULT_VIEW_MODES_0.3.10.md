# Result view modes — 0.3.10-alpha

The search results pane now has a **View** menu with four layouts:

- Large thumbnails
- Medium thumbnails
- Small thumbnails
- List

Thumbnail layouts display image previews in a responsive grid with the file name below each tile. The list layout retains the previous file name and relative-path presentation. The full path remains available as an item tooltip in every mode.

The selected layout is stored in `config/settings.json` as `result_view` and restored at application startup. Drag-and-drop, multi-selection, context menus, double-click opening, and the details preview use the same result list in every layout.
