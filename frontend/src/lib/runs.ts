export type RunStatus =
  | "queued"
  | "planning"
  | "editing"
  | "testing"
  | "preview_ready"
  | "needs_approval"
  | "approved"
  | "merging"
  | "deploying"
  | "merged"
  | "failed"
  | "canceled"
  | "expired"
  | string;

export interface RunContext {
  route?: string | null;
  page_title?: string | null;
  element_hint?: string | null;
  note?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface RunItem {
  id: string;
  title: string;
  prompt: string;
  status: RunStatus;
  route?: string | null;
  created_at: string;
  updated_at: string;
  context?: RunContext | null;
}

export interface RunEventItem {
  id: number;
  run_id: string;
  event_type: string;
  status_from: string | null;
  status_to: string | null;
  payload: Record<string, unknown> | null;
  created_at: string;
}

export interface ValidationCheckItem {
  id: number;
  run_id: string;
  check_name: string;
  status: string;
  started_at: string | null;
  ended_at: string | null;
  artifact_uri: string | null;
}

export interface ArtifactLink {
  label: string;
  uri: string;
  source: string;
}

export interface RunListResponse {
  items: RunItem[];
  total: number;
  limit: number;
  offset: number;
}

const artifactHintPattern = /(artifact|log|uri|url|report|output)/i;

export function statusChipClass(status: RunStatus): string {
  const normalized = status.toLowerCase();
  if (["failed", "canceled", "expired"].includes(normalized)) {
    return "chip chip-danger";
  }
  if (["merged", "approved", "preview_ready"].includes(normalized)) {
    return "chip chip-success";
  }
  if (["needs_approval", "testing", "merging", "deploying"].includes(normalized)) {
    return "chip chip-warn";
  }
  return "chip chip-neutral";
}

export function makeRunTitle(prompt: string): string {
  const text = prompt.trim().replace(/\s+/g, " ");
  if (!text) {
    return "Untitled run";
  }
  if (text.length <= 72) {
    return text;
  }
  return `${text.slice(0, 69)}...`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isLikelyUri(value: string): boolean {
  return (
    value.startsWith("http://") ||
    value.startsWith("https://") ||
    value.startsWith("s3://") ||
    value.startsWith("file://") ||
    value.startsWith("/")
  );
}

function walkArtifactCandidates(
  value: unknown,
  source: string,
  path: string[],
  inheritedHint: boolean,
  add: (link: ArtifactLink) => void,
): void {
  if (typeof value === "string") {
    const key = path[path.length - 1] ?? "";
    if ((inheritedHint || artifactHintPattern.test(key)) && isLikelyUri(value)) {
      add({
        label: path.join("."),
        uri: value,
        source,
      });
    }
    return;
  }

  if (Array.isArray(value)) {
    value.forEach((item, index) => {
      walkArtifactCandidates(item, source, [...path, String(index)], inheritedHint, add);
    });
    return;
  }

  if (isRecord(value)) {
    Object.entries(value).forEach(([key, nested]) => {
      const shouldHint = inheritedHint || artifactHintPattern.test(key);
      walkArtifactCandidates(nested, source, [...path, key], shouldHint, add);
    });
  }
}

export function extractArtifactLinks(
  checks: ValidationCheckItem[],
  events: RunEventItem[],
): ArtifactLink[] {
  const links: ArtifactLink[] = [];
  const seen = new Set<string>();

  const addLink = (link: ArtifactLink) => {
    if (!link.uri || seen.has(link.uri)) {
      return;
    }
    seen.add(link.uri);
    links.push(link);
  };

  checks.forEach((check) => {
    if (!check.artifact_uri) {
      return;
    }
    addLink({
      label: `${check.check_name} artifact`,
      uri: check.artifact_uri,
      source: `check:${check.status}`,
    });
  });

  events.forEach((event) => {
    if (!event.payload) {
      return;
    }
    walkArtifactCandidates(
      event.payload,
      `event:${event.event_type}`,
      ["payload"],
      false,
      addLink,
    );
  });

  return links;
}

export function extractFailureReasons(
  events: RunEventItem[],
  checks: ValidationCheckItem[],
): string[] {
  const reasons = new Set<string>();

  events.forEach((event) => {
    const payload = event.payload ?? {};
    const failureReasonCode =
      typeof payload.failure_reason_code === "string" ? payload.failure_reason_code : null;
    const reason = typeof payload.reason === "string" ? payload.reason : null;

    if (failureReasonCode && reason) {
      reasons.add(`${failureReasonCode}: ${reason}`);
      return;
    }
    if (failureReasonCode) {
      reasons.add(failureReasonCode);
      return;
    }
    if (reason) {
      reasons.add(reason);
      return;
    }
    if (event.status_to === "failed") {
      reasons.add("Run transitioned to failed without a detailed reason payload.");
    }
  });

  checks.forEach((check) => {
    if (check.status.toLowerCase() === "failed") {
      reasons.add(`Validation check failed: ${check.check_name}`);
    }
  });

  return [...reasons];
}
