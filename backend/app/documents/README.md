# documents (Person 2)

Planned:
- `document`, `document_version`, `fact`, `ocr_run` tables (schema `doc`), content-addressed object store
- ClamAV scan, then script router: Latin -> Tesseract, Indic scripts -> Indic ONNX model
- Digit normalisation, date grammar, handwriting detection routed to a person (never guessed)
- Facts start as PROPOSED; only CONFIRMED / CORRECTED facts may anchor a deadline
- APIs: `POST /documents`, `GET /documents/{id}/facts`, `POST /facts/{id}/confirm`
- The Indic model's ownership and licence must be confirmed before submission
