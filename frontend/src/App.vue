<template>
  <RouterView />
  <RunLifecycleNotifications />
  <RouteRunBadges />
  <GlobalShortcutOverlay />
</template>

<script setup lang="ts">
import GlobalShortcutOverlay from "./components/GlobalShortcutOverlay.vue";
import RouteRunBadges from "./components/RouteRunBadges.vue";
import RunLifecycleNotifications from "./components/RunLifecycleNotifications.vue";
</script>
