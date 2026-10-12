# Extended file types — 0.3.8-alpha

The File type filter and newly created catalogs now include:

`.json`, `.png`, `.jpg`, `.jpeg`, `.webp`, `.txt`, `.md`, `.html`, `.htm`, `.pdf`, and `.py`.

- JPG, JPEG, and WEBP can receive Vision vectors when visual indexing is enabled. A filename metadata record also keeps them searchable without Vision.
- TXT is indexed as plain text.
- HTML and HTM are converted to visible text with the Python standard-library HTML parser.
- PDF text is extracted when the optional `pypdf` package is available. Without it, the PDF remains searchable by filename and is indexed without an error.
- Existing catalogs keep their configured extension list. Add the desired extensions in Catalog settings and rebuild the index before expecting those files in results.
