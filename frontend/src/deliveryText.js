// Plain-language meaning of delivery states and failure categories. Codes come from the notification worker
// (backend/app/platform/notifier.py, providers.py); unknown codes are shown as they are.

export const STATUS = {
  PENDING: { tone: "warn", text: "Waiting to be sent, or waiting before a retry" },
  SENDING: { tone: "warn", text: "A worker is sending it now" },
  DELIVERED: { tone: "ok", text: "Handed to every recipient (email and SMS: at least once)" },
  DEAD: { tone: "bad", text: "Stopped; needs a person to look at it" },
};

const ERRORS = {
  NOT_CONFIGURED: "The mail server is not configured for this deployment",
  NO_RECIPIENT: "Nobody holds this role yet (vacant post)",
  NO_PROVIDER_FOR_CHANNEL: "No delivery channel is set up for this kind of message",
  UNKNOWN_TEMPLATE: "The message template is unknown",
  RECIPIENT_REFUSED: "The mail server refused the recipient",
  SOME_RECIPIENTS_REFUSED: "Delivered to some recipients; others were refused",
  ALL_RECIPIENTS_REFUSED: "Every recipient was refused",
  ATTEMPTS_EXHAUSTED: "Gave up after the maximum number of attempts",
  CONNECTION_FAILED: "Could not reach the provider",
  TIMEOUT_OR_DISCONNECT: "The provider stopped responding; it may or may not have received the message",
  PROVIDER_ERROR: "Unexpected provider error; it may or may not have received the message",
  LEASE_LOST: "Another worker took over this message",
};

export function errorText(code) {
  if (!code) return null;
  if (ERRORS[code]) return ERRORS[code];
  if (/^SMTP_5\d\d$/.test(code)) return `The mail server rejected the message (${code.slice(5)})`;
  if (/^SMTP_4\d\d$/.test(code)) return `The mail server asked to try later (${code.slice(5)})`;
  return code;
}

export function outcomeText(outcome) {
  if (outcome?.endsWith("_LEASE_LOST")) return "Superseded: another worker had taken over";
  return {
    DELIVERED: "Delivered",
    TRANSIENT: "Temporary failure, will retry",
    AMBIGUOUS: "Unclear result, will retry (may repeat)",
    PERMANENT: "Permanent failure",
  }[outcome] ?? outcome;
}
