# Document field-candidate extraction, v1

**Status:** The three canonical field keys, normalizer assignments, same-line
boundary rule, and page-text provenance convention below reflect the team's
approved v1 decisions. The only recognized labels are those canonical keys.
Additional printed-label aliases remain pending team approval. This
specification describes a tested pure extraction component; it does not enable
document processing or persistence.

**Decision owner:** Team agreement recorded in the project instructions.
**Approval:** The three v1 keys, normalizer assignments, boundary rule, and
provenance are approved. Additional aliases and confidence calibration remain
pending approval.

## Supported fields and versioned labels

The versioned source of truth is `data/field_aliases.v1.json`, loaded by
`app.documents.candidates.load_field_rules()`. The field key itself is the
only recognized label in v1. No case folding, translation, fuzzy matching, or
additional printed alias is applied.

| Field key / recognized label | Additional approved aliases | Normalizer after numeral conversion |
| --- | --- | --- |
| `lease_end_date` | None in v1 | `normalize_date_candidate` |
| `letter_issue_date` | None in v1 | `normalize_date_candidate` |
| `letter_file_number` | None in v1 | `normalize_reference_value` |

The keys and mapping are approved. New aliases or fields require review and a
new version of the data file; do not add them directly to extraction code.

## Input and output

`extract_field_candidates()` accepts the exact OCR text for one page, its
`OcrToken` sequence, a positive 1-based page number, and the `ocr_run_id` and
`document_version_id` provenance UUIDs. Empty token input produces no
candidates. A page with a recognized label/value but missing, overlapping,
wrong-page, out-of-range, or text-mismatched token provenance raises
`ValueError`; the extractor returns no partial batch.

Each frozen `FieldCandidate` contains the canonical field key, a
`NormalizedValue`, both provenance UUIDs, page number, candidate source span,
the original source tokens (including their scripts and individual OCR
confidence values), and alias-data version. It contains no aggregated
confidence. No confidence aggregation rule or threshold is approved. The
caller that constructs a `Fact` must use an explicit confidence value and the
existing `propose_fact()` validation.

## Label and value boundaries

- A label is matched exactly and case-sensitively at the start of a line or
  after whitespace. It ends before whitespace, an optional colon delimiter,
  or the line end.
- A value ends at the next recognized v1 label on that same line or the line
  end. Extraction never joins across lines and never guesses a continuation.
- Surrounding whitespace and the optional label delimiter are excluded from
  candidate text. Internal whitespace, punctuation, and codepoints are
  preserved exactly.
- Text for which OCR tokens do not provide matching source spans is not
  silently extracted. Unknown labels are ignored; no unknown-label boundary
  heuristic is applied.

No extra token-joining, fuzzy-label, or field-specific grammar is applied.

## Normalization and unresolved values

The extractor first applies `normalize_numerals()` to a temporary string, then
calls the normalizer selected by the versioned field rule. `NormalizedValue`
retains the exact original candidate text. For dates, calendar-unambiguous
values may normalize to ISO format; `03-04-2024` remains `AMBIGUOUS` with no
normalized value. Invalid and unsupported dates likewise remain unresolved.
File-number normalization performs numeral conversion only; it does not
validate a file-number grammar. No legal deadline or academic-year rule is
inferred.

Unresolved candidates are returned with their original text and normalization
status. Existing fact construction keeps them `PROPOSED`; they cannot be
confirmed as normalized values by the review helper.

## Provenance

- Page numbers are 1-based.
- Offsets are zero-based, half-open Unicode character positions `[start, end)`
  into the exact page OCR text supplied to extraction. They are not byte or
  UTF-16 offsets. Do not normalize or rewrite that text before locating spans.
- `OcrToken` text must equal the page-text slice at its span. Tokens must refer
  to the requested page, be non-overlapping, and have spans within the page.
- Each candidate retains its matching source tokens and the OCR-run and
  document-version identities. PostgreSQL still enforces that a fact refers
  to a successful OCR run for that version; the pure extractor cannot prove
  that relationship.

## Conflicts and persistence boundary

Extraction emits each matching label occurrence as a separate candidate. It
does not decide whether repeated labels refer to the same logical field
instance. Where the caller has established that multiple candidates compete
for one logical field, it may construct separate `PROPOSED` facts with the
existing `propose_fact()` helper and call `mark_conflicting_candidates()` on
the full transient batch before persistence. The helper assigns one shared
group ID only when values differ. A single ambiguous date remains one
unresolved candidate; the extractor does not invent alternative date
interpretations or fact rows. No fact is persisted or finalized here.

## Synthetic acceptance cases

`backend/tests/test_documents_candidates.py` covers:

- The three canonical keys and approved normalizer mapping; no additional
  aliases.
- Exact label delimiters, same-line extraction, next-known-label stopping,
  line ending handling, and empty/unknown input.
- Raw Unicode numeral preservation alongside normalized output.
- Unambiguous, ambiguous, invalid, and unsupported date values.
- Source-text offsets, token matching, page numbers, and OCR-run/version IDs.
- Empty, missing, malformed, overlapping, wrong-page, and out-of-range
  provenance.
- Separate proposed facts for explicitly grouped competing unresolved
  candidates, without guessed interpretations or confidence aggregation.
- Fail-closed handling of malformed versioned alias data.

These are synthetic database-free tests. They do not prove OCR accuracy,
database constraints, authorization, or end-to-end processing.

## Remaining decisions and integrations

- Additional printed-label aliases require team approval and a versioned data
  change.
- Confidence aggregation and calibration remain undefined; callers supply an
  explicit value and no threshold is applied.
- The caller must establish which repeated candidates belong to the same
  logical field before grouping them.
- Extraction remains separate from private storage reads, OCR execution,
  transactional OCR-run/fact persistence, review UI, and authorization.
