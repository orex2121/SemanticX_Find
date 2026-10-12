# External file drag-and-drop — 0.2.16-alpha

- Files can be dragged from Search results, Catalog files, and Favorites into other Windows applications.
- Drag payloads contain standard local-file URLs plus plain-text paths for broad application compatibility.
- The advertised operation is Copy, allowing Explorer folders to copy the source file instead of moving it.
- Multiple selected files can be dragged together.
- Missing files are excluded from the drag payload.
- Destination behavior is controlled by the receiving application: it may copy, attach, import, or open the dropped file.
