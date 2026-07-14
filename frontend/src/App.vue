<script setup lang="ts">
import {
  NConfigProvider, NDialogProvider, NGlobalStyle, NMessageProvider, zhTW, dateZhTW,
} from 'naive-ui'
import { themeOverrides } from '@/theme'
</script>

<template>
  <n-config-provider :locale="zhTW" :date-locale="dateZhTW" :theme-overrides="themeOverrides">
    <n-global-style />
    <!-- dialog provider 不可少:useDialog() 找不到它會在 setup 直接擲錯,整頁渲染不出來
         (系統管理頁就是這樣整片空白的)。 -->
    <n-message-provider>
      <n-dialog-provider>
        <router-view />
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>
