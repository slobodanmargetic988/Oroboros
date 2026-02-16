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

export interface RunListResponse {
  items: RunItem[];
  total: number;
  limit: number;
  offset: number;
}

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
