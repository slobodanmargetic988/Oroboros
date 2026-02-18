const NETWORK_FAILURE_PATTERN = /(failed to fetch|networkerror|load failed)/i;

export function toActionableRequestError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error ?? "").trim();
  if (NETWORK_FAILURE_PATTERN.test(message)) {
    return "Unable to reach backend API. Check backend availability and CORS/preflight settings for this origin.";
  }
  if (!message) {
    return "Request failed.";
  }
  return message;
}

