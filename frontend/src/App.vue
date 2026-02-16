<template>
  <main class="page">
    <h1>Ouroboros Frontend Scaffold</h1>
    <p>Vue 3 + TypeScript + Vite baseline is ready.</p>
    <p>API base URL: <code>{{ apiBaseUrl }}</code></p>
  </main>
</template>

<script setup lang="ts">
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
</script>
