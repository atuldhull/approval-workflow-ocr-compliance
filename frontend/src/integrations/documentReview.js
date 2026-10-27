// Adapter for Person 2's document review API (not built yet). The UI talks only to this interface, so connecting
// the real backend means replacing `fixtureAdapter` with an HTTP implementation - the screens stay the same.
// What the backend must provide is specified in docs/handoffs/PERSON2_FROM_P3.md.
//
// Commit-before-reveal is part of the interface, not just the UI: loadReview() returns NO machine output,
// and a field's suggestion is only obtainable through commitReading(), after the officer's own value is recorded.

import { FACSIMILE } from "../fixtures/facsimile.js";

/**
 * @typedef {Object} DocumentPage
 * @property {string} imageUrl    the ORIGINAL page image (or a clearly labelled synthetic facsimile)
 * @property {number} width
 * @property {number} height
 *
 * @typedef {Object} FieldToReview
 * @property {string} key         e.g. "lease_end"
 * @property {string} label       e.g. "Lease end date"
 * @property {string} format      e.g. "YYYY-MM-DD"
 *
 * @typedef {Object} Review
 * @property {string} documentId
 * @property {string} title
 * @property {boolean} synthetic  true for demo facsimiles; the UI labels them
 * @property {DocumentPage[]} pages
 * @property {FieldToReview[]} fields   no suggestions, no confidence, no locations
 *
 * @typedef {Object} Suggestion       returned only after the officer commits
 * @property {string|null} value
 * @property {number|null} confidence  uncalibrated unless the backend says otherwise
 * @property {{page:number,x:number,y:number,w:number,h:number}|null} box
 * @property {string|null} sourceText  what OCR read at that location
 *
 * @typedef {Object} FactDecision      one per field, sent together once every field has a committed reading
 * @property {string} fieldKey
 * @property {string} value           the value the officer stands behind
 * @property {"OFFICER"|"MACHINE"} source   kept their own reading, or adopted the machine reading after seeing it
 *
 * @typedef {Object} ConfirmResult
 * @property {{fieldKey: string, factId: string}[]} confirmed   must list EVERY submitted field, or the UI treats
 *                                                              the confirmation as failed
 *
 * @typedef {Object} DocumentReviewAdapter
 * @property {boolean} live           false while backed by fixtures
 * @property {(documentId: string) => Promise<Review>} loadReview
 * @property {(documentId: string, fieldKey: string, value: string) => Promise<Suggestion>} commitReading
 * @property {null | ((documentId: string, decisions: FactDecision[]) => Promise<ConfirmResult>)} confirmFacts
 *           all-or-nothing on the server; null while the API does not exist (the button stays disabled)
 */

// True only if the server confirmed exactly the fields that were sent.
export function confirmedAll(decisions, result) {
  const got = new Set((result?.confirmed ?? []).filter((c) => c && c.factId).map((c) => c.fieldKey));
  return decisions.length > 0 && decisions.every((d) => got.has(d.fieldKey)) && got.size === decisions.length;
}

/** @type {DocumentReviewAdapter} */
export const fixtureAdapter = {
  live: false,
  async loadReview() {
    return {
      documentId: FACSIMILE.documentId,
      title: FACSIMILE.title,
      synthetic: true,
      pages: [FACSIMILE.page],
      fields: FACSIMILE.fields.map(({ key, label, format }) => ({ key, label, format })),
    };
  },
  async commitReading(documentId, fieldKey, value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error("Enter the date as YYYY-MM-DD before revealing.");
    const f = FACSIMILE.fields.find((x) => x.key === fieldKey);
    return { value: f.suggestion, confidence: f.confidence, box: f.box, sourceText: f.sourceText };
  },
  confirmFacts: null, // needs Person 2's fact-confirmation API; the UI keeps the button disabled while null
};
