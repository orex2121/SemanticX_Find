# Model status panel — 0.2.9-alpha

- The Models tab displays separate status sections for EmbeddingGemma 2 and OCR.
- EmbeddingGemma status includes readiness, present/expected files, installed/expected size, verified revision, capabilities, and local path.
- OCR status includes readiness, file count, installed size, recognition language profile, and local path.
- The status refreshes automatically after download or verification jobs complete.
- Opening the tab does not hash the large checkpoints; the existing Verify action remains responsible for full checksum validation.
