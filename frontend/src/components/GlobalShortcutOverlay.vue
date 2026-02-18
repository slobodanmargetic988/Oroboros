<template>
  <Teleport to="body">
    <div
      v-if="isOpen"
      class="overlay-shell"
      role="dialog"
      aria-modal="true"
      aria-labelledby="quick-codex-title"
      aria-describedby="quick-codex-subhead"
    >
      <button type="button" class="overlay-backdrop" :aria-label="t('shortcuts.closePrompt')" @click="closeOverlay" />

      <section ref="overlayCardRef" class="overlay-card">
        <header class="overlay-head">
          <p class="overlay-eyebrow">{{ t("shortcuts.eyebrow") }}</p>
          <h2 id="quick-codex-title">{{ t("shortcuts.title") }}</h2>
          <p id="quick-codex-subhead" class="overlay-subhead">{{ t("shortcuts.subhead") }}</p>
        </header>

        <form class="overlay-form" @submit.prevent="submitRun">
          <label>
            {{ t("shortcuts.prompt") }}
            <textarea
              ref="promptInputRef"
              v-model="prompt"
              rows="4"
              :placeholder="t('shortcuts.promptPlaceholder')"
              required
            />
          </label>

          <div class="overlay-row">
            <label>
              {{ t("shortcuts.route") }}
              <input :value="currentRoutePath" type="text" readonly />
            </label>
            <label>
              {{ t("shortcuts.optionalNote") }}
              <input v-model="note" type="text" :placeholder="t('shortcuts.notePlaceholder')" />
            </label>
          </div>

          <div class="overlay-actions">
            <button :disabled="submitting" type="submit">
              {{ submitting ? t("common.submitting") : t("shortcuts.createRun") }}
            </button>
            <button :disabled="submitting" type="button" class="secondary" @click="closeOverlay">{{ t("common.cancel") }}</button>
          </div>

          <p v-if="submitError" class="overlay-error" role="alert">{{ submitError }}</p>
          <p v-if="submitSuccess" class="overlay-success" role="status">{{ submitSuccess }}</p>
          <p class="overlay-hint">{{ t("shortcuts.shortcutHint") }}</p>
        </form>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
import { useRoute } from "vue-router";

import { makeRunTitle } from "../lib/runs";
import { useI18n } from "../lib/i18n";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

const route = useRoute();
const { t } = useI18n();

const isOpen = ref(false);
const prompt = ref("");
const note = ref("");
const submitting = ref(false);
const submitError = ref("");
const submitSuccess = ref("");
const promptInputRef = ref<HTMLTextAreaElement | null>(null);
const overlayCardRef = ref<HTMLElement | null>(null);
const overlaySessionId = ref(0);
const pendingCloseTimeoutId = ref<number | null>(null);
let previouslyFocusedElement: HTMLElement | null = null;

const ROUTE_MAX_LENGTH = 255;
const currentRoutePath = computed(() => {
  const fullPath = route.fullPath || route.path || "/";
  if (fullPath.length <= ROUTE_MAX_LENGTH) {
    return fullPath;
  }
  const fallbackPath = route.path || "/";
  return fallbackPath.slice(0, ROUTE_MAX_LENGTH);
});

function closeOverlay() {
  if (pendingCloseTimeoutId.value !== null) {
    window.clearTimeout(pendingCloseTimeoutId.value);
    pendingCloseTimeoutId.value = null;
  }
  overlaySessionId.value += 1;
  isOpen.value = false;
  if (previouslyFocusedElement) {
    previouslyFocusedElement.focus();
    previouslyFocusedElement = null;
  }
}

async function openOverlay() {
  if (pendingCloseTimeoutId.value !== null) {
    window.clearTimeout(pendingCloseTimeoutId.value);
    pendingCloseTimeoutId.value = null;
  }
  overlaySessionId.value += 1;
  previouslyFocusedElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  isOpen.value = true;
  submitError.value = "";
  submitSuccess.value = "";
  await nextTick();
  promptInputRef.value?.focus();
}

async function submitRun() {
  const submitSessionId = overlaySessionId.value;
  submitError.value = "";
  submitSuccess.value = "";
  submitting.value = true;

  try {
    const payload = {
      title: makeRunTitle(prompt.value),
      prompt: prompt.value,
      route: currentRoutePath.value,
      note: note.value || undefined,
      metadata: {
        source: "global-shortcut-overlay",
      },
    };

    const response = await fetch(`${apiBaseUrl}/api/runs`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`Run create failed (${response.status})`);
    }

    if (submitSessionId !== overlaySessionId.value || !isOpen.value) {
      return;
    }

    prompt.value = "";
    note.value = "";
    submitSuccess.value = t("shortcuts.successCreated");
    pendingCloseTimeoutId.value = window.setTimeout(() => {
      if (submitSessionId !== overlaySessionId.value) {
        return;
      }
      pendingCloseTimeoutId.value = null;
      closeOverlay();
    }, 350);
  } catch (error) {
    if (submitSessionId !== overlaySessionId.value) {
      return;
    }
    submitError.value = (error as Error).message;
  } finally {
    if (submitSessionId === overlaySessionId.value) {
      submitting.value = false;
    }
  }
}

function trapFocus(event: KeyboardEvent): void {
  const container = overlayCardRef.value;
  if (!container) {
    return;
  }

  const focusable = container.querySelectorAll<HTMLElement>(
    "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
  );
  if (!focusable.length) {
    return;
  }

  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const active = document.activeElement as HTMLElement | null;

  if (!event.shiftKey && active === last) {
    event.preventDefault();
    first.focus();
    return;
  }

  if (event.shiftKey && active === first) {
    event.preventDefault();
    last.focus();
  }
}

async function handleShortcut(event: KeyboardEvent) {
  const isShortcut = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k";
  if (!isShortcut || event.shiftKey || event.altKey) {
    if (event.key === "Escape" && isOpen.value) {
      event.preventDefault();
      closeOverlay();
      return;
    }
    if (event.key === "Tab" && isOpen.value) {
      trapFocus(event);
    }
    return;
  }

  event.preventDefault();

  if (isOpen.value) {
    closeOverlay();
    return;
  }

  await openOverlay();
}

onMounted(() => {
  window.addEventListener("keydown", handleShortcut);
});

onUnmounted(() => {
  window.removeEventListener("keydown", handleShortcut);
  if (pendingCloseTimeoutId.value !== null) {
    window.clearTimeout(pendingCloseTimeoutId.value);
    pendingCloseTimeoutId.value = null;
  }
});
</script>

<style scoped>
.overlay-shell {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: center;
}

.overlay-backdrop {
  position: absolute;
  inset: 0;
  border: 0;
  background: rgba(15, 23, 42, 0.65);
  cursor: pointer;
}

.overlay-card {
  position: relative;
  z-index: 1;
  width: min(720px, calc(100vw - 2rem));
  border-radius: 14px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  box-shadow: 0 22px 40px rgba(15, 23, 42, 0.35);
  padding: 1rem;
  display: grid;
  gap: 0.85rem;
}

.overlay-head h2 {
  margin: 0.15rem 0 0.35rem;
}

.overlay-eyebrow {
  margin: 0;
  font-size: 0.78rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #334155;
}

.overlay-subhead {
  margin: 0;
  color: #475569;
}

.overlay-form {
  display: grid;
  gap: 0.75rem;
}

.overlay-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}

label {
  display: grid;
  gap: 0.35rem;
  font-size: 0.9rem;
  color: #334155;
}

textarea,
input,
button {
  font: inherit;
}

textarea,
input {
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 0.55rem 0.65rem;
  background: #f8fafc;
}

.overlay-actions {
  display: flex;
  gap: 0.5rem;
}

button {
  border: 0;
  background: #0f766e;
  color: #f8fafc;
  border-radius: 10px;
  padding: 0.55rem 0.9rem;
  cursor: pointer;
}

button.secondary {
  background: #334155;
}

button:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.overlay-error {
  margin: 0;
  color: #b91c1c;
}

.overlay-success {
  margin: 0;
  color: #166534;
}

.overlay-hint {
  margin: 0;
  font-size: 0.85rem;
  color: #475569;
}

@media (max-width: 720px) {
  .overlay-row {
    grid-template-columns: 1fr;
  }
}
</style>
