# Multiple file type filter — 0.3.9-alpha

The search file-type filter is a checkable multi-select list. Users can select any combination of indexed extensions, select all, or clear all selections.

The selected extensions are saved in `config/settings.json` as `selected_file_types` and restored on the next application start. `null` means the initial default of all available file types; an empty list intentionally means no file types.

The search engine accepts `extensions` as a list while retaining the singular `extension` argument for compatibility.
