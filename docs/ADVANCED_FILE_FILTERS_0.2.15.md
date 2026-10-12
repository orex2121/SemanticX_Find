# Advanced file filters — 0.2.15-alpha

- Search can be limited by indexed file modification time: past day, 7 days, 30 days, or year.
- Search can be limited by maximum file size in megabytes; zero means any size.
- Existing path, node, model, type, and score filters remain available on a separate row.
- Filter selections survive interface rebuilds such as language/theme changes.
- Result details now display indexed file size and modification timestamp.
- Filtering uses stored index metadata and does not reread source files during search.
