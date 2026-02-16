<template>
  <RouterView />
  <RouteRunBadges />
  <GlobalShortcutOverlay />
</template>

<script setup lang="ts">
import GlobalShortcutOverlay from "./components/GlobalShortcutOverlay.vue";
import RouteRunBadges from "./components/RouteRunBadges.vue";
</script>
