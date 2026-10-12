# Footer and catalog memory — 0.3.6-alpha

- The top menu bar is removed.
- Help is now a menu button at the far right of the lowest application row.
- The version label is immediately to the left of Help.
- Clicking anywhere on the closed catalog selector opens its checklist, not only the arrow.
- Checked catalog IDs are saved to `config/settings.json` as `selected_catalogs`.
- The last catalog selection is restored on startup, including a deliberately empty selection.
- When no saved selection exists, all catalogs remain selected by default.
