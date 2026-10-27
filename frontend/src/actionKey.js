import { useMemo, useRef } from "react";
import { newIdempotencyKey } from "./api.js";

// A refusal the server decided (a 4xx with a reason) is final for that request, so the next attempt is a new action
// with a new key. A lost answer, a server failure or "still being processed" (409 without a reason code) may have
// been applied, so the retry keeps the key and the server replays its stored answer instead of acting twice.
export const keepsKey = (err) => Boolean(err) && (!err.status || err.status >= 500 || (err.status === 409 && !err.reason));

// One Idempotency-Key per user action (docs/IDEMPOTENCY.md). `signature` names the action and its inputs: the same
// signature after a retryable failure reuses the key; anything else gets a fresh one.
export function useActionKey() {
  const held = useRef(null);
  return useMemo(() => ({
    for(signature) {
      if (!held.current || held.current.signature !== signature) held.current = { signature, key: newIdempotencyKey() };
      return held.current.key;
    },
    settle(err) {
      if (!keepsKey(err)) held.current = null;
    },
    pending(signature) {
      return held.current !== null && (signature === undefined || held.current.signature === signature);
    },
  }), []);
}
