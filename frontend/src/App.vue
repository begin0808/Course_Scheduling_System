<script setup lang="ts">
import { NConfigProvider, NGlobalStyle, NMessageProvider, zhTW, dateZhTW } from 'naive-ui'
import { themeOverrides } from '@/theme'
</script>

<template>
  <n-config-provider :locale="zhTW" :date-locale="dateZhTW" :theme-overrides="themeOverrides">
    <n-global-style />
    <n-message-provider>
      <router-view />
    </n-message-provider>
  </n-config-provider>
</template>
