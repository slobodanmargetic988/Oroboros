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
  slot_id?: string | null;
  branch_name?: string | null;
  worktree_path?: string | null;
  commit_sha?: string | null;
  parent_run_id?: string | null;
  created_by?: string | null;
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

export interface FileDiffEntry {
  path: string;
  additions: number | null;
  deletions: number | null;
  patch: string | null;
  source: string;
}

export interface ChecksSummary {
  total: number;
  passed: number;
  failed: number;
  running: number;
  pending: number;
}

export interface RunListResponse {
  items: RunItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface SlotStateItem {
  slot_id: string;
  state: string;
  run_id: string | null;
  lease_state: string | null;
  expires_at: string | null;
  heartbeat_at: string | null;
}

export interface SlotWaitingReason {
  reason: string;
  occupied_slots: string[];
  queue_behavior: string | null;
}

const artifactHintPattern = /(artifact|log|uri|url|report|output)/i;
const diffHintPattern = /(diff|patch|file|change|modified|updated)/i;
const diffPathKeyPattern = /(path|file|filename|name|target_file|old_path|new_path)/i;
const diffPatchKeyPattern = /^(patch|diff|snippet)$/i;

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

function toInteger(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.max(0, Math.floor(value));
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return Math.max(0, Math.floor(parsed));
    }
  }
  return null;
}

function looksLikePath(value: string): boolean {
  const normalized = value.trim();
  if (!normalized) {
    return false;
  }
  if (normalized.includes("\n") || normalized.includes("\r")) {
    return false;
  }
  if (normalized.startsWith("@@ ") || normalized.startsWith("diff --git ")) {
    return false;
  }
  return normalized.includes("/") || normalized.includes(".");
}

function toPathFromRecord(record: Record<string, unknown>): string | null {
  const keys = ["path", "file", "filename", "name", "target_file"];
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim() && looksLikePath(value)) {
      return value.trim();
    }
  }
  return null;
}

function toPatchFromRecord(record: Record<string, unknown>): string | null {
  const keys = ["patch", "diff", "snippet"];
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) {
      return value;
    }
  }
  return null;
}

function toDiffEntry(
  path: string,
  source: string,
  record?: Record<string, unknown>,
): FileDiffEntry {
  return {
    path,
    additions: record ? toInteger(record.additions ?? record.insertions ?? record.added_lines) : null,
    deletions: record ? toInteger(record.deletions ?? record.removed_lines) : null,
    patch: record ? toPatchFromRecord(record) : null,
    source,
  };
}

export function extractFileDiffEntries(events: RunEventItem[]): FileDiffEntry[] {
  const entries: FileDiffEntry[] = [];
  const seen = new Set<string>();

  const pushUnique = (entry: FileDiffEntry) => {
    const key = `${entry.source}:${entry.path}`;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    entries.push(entry);
  };

  const walk = (value: unknown, source: string, inheritedHint: boolean) => {
    if (Array.isArray(value)) {
      value.forEach((item) => walk(item, source, inheritedHint));
      return;
    }

    if (isRecord(value)) {
      const directPath = toPathFromRecord(value);
      if (directPath) {
        pushUnique(toDiffEntry(directPath, source, value));
      }

      Object.entries(value).forEach(([key, nested]) => {
        const hint = inheritedHint || diffHintPattern.test(key);

        if (typeof nested === "string") {
          if (diffPatchKeyPattern.test(key)) {
            return;
          }
          if (
            hint &&
            diffPathKeyPattern.test(key) &&
            looksLikePath(nested)
          ) {
            pushUnique(toDiffEntry(nested.trim(), source));
          }
          return;
        }

        walk(nested, source, hint);
      });
    }
  };

  events.forEach((event) => {
    if (!event.payload) {
      return;
    }
    walk(event.payload, `event:${event.event_type}`, false);
  });

  return entries.sort((a, b) => a.path.localeCompare(b.path));
}

export function hasMigrationWarning(entries: FileDiffEntry[]): boolean {
  return entries.some((entry) => /(alembic|migrations?|migration|\.sql$)/i.test(entry.path));
}

export function summarizeChecks(checks: ValidationCheckItem[]): ChecksSummary {
  const summary: ChecksSummary = {
    total: checks.length,
    passed: 0,
    failed: 0,
    running: 0,
    pending: 0,
  };

  checks.forEach((check) => {
    const status = check.status.toLowerCase();
    if (status.includes("fail") || status.includes("error")) {
      summary.failed += 1;
      return;
    }
    if (status.includes("pass") || status.includes("success") || status === "ok") {
      summary.passed += 1;
      return;
    }
    if (
      status.includes("run") ||
      status.includes("progress") ||
      status.includes("queued") ||
      status === "planning" ||
      status === "testing"
    ) {
      summary.running += 1;
      return;
    }
    summary.pending += 1;
  });

  return summary;
}

export function normalizeRoutePath(route: string | null | undefined): string {
  const value = (route ?? "").trim();
  if (!value) {
    return "/";
  }

  const [pathOnly] = value.split(/[?#]/, 1);
  const ensuredPrefix = pathOnly.startsWith("/") ? pathOnly : `/${pathOnly}`;
  if (ensuredPrefix.length > 1 && ensuredPrefix.endsWith("/")) {
    return ensuredPrefix.slice(0, -1);
  }
  return ensuredPrefix || "/";
}

export function getRunRoute(run: RunItem): string {
  return normalizeRoutePath(run.context?.route || run.route || "/");
}

export function isRunRelatedToRoute(runRoute: string, currentRoute: string): boolean {
  const normalizedRunRoute = normalizeRoutePath(runRoute);
  const normalizedCurrentRoute = normalizeRoutePath(currentRoute);

  if (normalizedRunRoute === normalizedCurrentRoute) {
    return true;
  }

  if (normalizedCurrentRoute.startsWith(`${normalizedRunRoute}/`)) {
    return true;
  }

  if (normalizedRunRoute.startsWith(`${normalizedCurrentRoute}/`)) {
    return true;
  }

  return false;
}

export function filterRunsByRoute(runs: RunItem[], route: string | null | undefined): RunItem[] {
  const normalizedRoute = normalizeRoutePath(route);
  return runs.filter((run) => isRunRelatedToRoute(getRunRoute(run), normalizedRoute));
}

export function extractLatestSlotWaitingReason(events: RunEventItem[]): SlotWaitingReason | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (!event || event.event_type !== "slot_waiting" || !event.payload) {
      continue;
    }

    const reason =
      typeof event.payload.reason === "string" && event.payload.reason.trim()
        ? event.payload.reason.trim()
        : "WAITING_FOR_SLOT";
    const queueBehavior =
      typeof event.payload.queue_behavior === "string" && event.payload.queue_behavior.trim()
        ? event.payload.queue_behavior.trim()
        : null;

    const occupiedSlots = Array.isArray(event.payload.occupied_slots)
      ? event.payload.occupied_slots
          .filter((value): value is string => typeof value === "string" && value.trim().length > 0)
          .map((value) => value.trim())
      : [];

    return {
      reason,
      occupied_slots: occupiedSlots,
      queue_behavior: queueBehavior,
    };
  }

  return null;
}

export function previewUrlForSlot(slotId: string): string {
  const normalized = slotId.trim().toLowerCase();
  const match = normalized.match(/preview-?(\d+)/);
  if (match?.[1]) {
    return `https://preview${match[1]}.example.com`;
  }
  return "https://app.example.com";
}
