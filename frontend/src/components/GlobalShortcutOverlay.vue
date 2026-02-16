<template>
  <Teleport to="body">
    <div v-if="isOpen" class="overlay-shell" role="dialog" aria-modal="true" aria-label="Codex quick prompt">
      <button class="overlay-backdrop" aria-label="Close quick prompt" @click="closeOverlay" />

      <section class="overlay-card">
        <header class="overlay-head">
          <p class="overlay-eyebrow">Global Shortcut</p>
          <h2>Quick Codex Prompt</h2>
          <p class="overlay-subhead">Current route will be attached automatically.</p>
        </header>

        <form class="overlay-form" @submit.prevent="submitRun">
          <label>
            Prompt
            <textarea
              ref="promptInputRef"
              v-model="prompt"
              rows="4"
              placeholder="Describe the change you want to request"
              required
            />
          </label>

          <div class="overlay-row">
            <label>
              Route
              <input :value="currentRoutePath" type="text" readonly />
            </label>
            <label>
              Optional Note
              <input v-model="note" type="text" placeholder="Extra context for this route" />
            </label>
          </div>

          <div class="overlay-actions">
            <button :disabled="submitting" type="submit">{{ submitting ? "Submitting..." : "Create Run" }}</button>
            <button :disabled="submitting" type="button" class="secondary" @click="closeOverlay">Cancel</button>
          </div>

          <p v-if="submitError" class="overlay-error">{{ submitError }}</p>
          <p v-if="submitSuccess" class="overlay-success">{{ submitSuccess }}</p>
          <p class="overlay-hint">Shortcut: Cmd/Ctrl+K to open, Esc to close.</p>
        </form>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
import { useRoute } from "vue-router";

import { makeRunTitle } from "../lib/runs";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

const route = useRoute();

const isOpen = ref(false);
const prompt = ref("");
const note = ref("");
const submitting = ref(false);
const submitError = ref("");
const submitSuccess = ref("");
const promptInputRef = ref<HTMLTextAreaElement | null>(null);

const currentRoutePath = computed(() => route.fullPath || route.path || "/");

function closeOverlay() {
  isOpen.value = false;
}

async function openOverlay() {
  isOpen.value = true;
  submitError.value = "";
  submitSuccess.value = "";
  await nextTick();
  promptInputRef.value?.focus();
}

async function submitRun() {
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

    prompt.value = "";
    note.value = "";
    submitSuccess.value = "Run request created.";
    setTimeout(() => {
      closeOverlay();
    }, 350);
  } catch (error) {
    submitError.value = (error as Error).message;
  } finally {
    submitting.value = false;
  }
}

async function handleShortcut(event: KeyboardEvent) {
  const isShortcut = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k";
  if (!isShortcut || event.shiftKey || event.altKey) {
    if (event.key === "Escape" && isOpen.value) {
      event.preventDefault();
      closeOverlay();
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
