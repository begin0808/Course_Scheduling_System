<script setup lang="ts">
import { NBadge, NButton, NEmpty, NPopover, NScrollbar, NSpace, NTag, NText, useMessage } from 'naive-ui'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { acknowledge, markRead, myNotifications } from '@/api/notifications'
import type { Notification } from '@/api/notifications'
import { publishedSemesters } from '@/api/timetables'
import { listSemesters } from '@/api/semesters'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const message = useMessage()

const POLL_MS = 20000 // 站內通知輪詢;鈴鐺不需即時,20 秒足矣

const sid = ref<number | null>(null)
const items = ref<Notification[]>([])
const unread = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

const canManage = computed(() =>
  auth.hasRole('admin') || auth.hasRole('scheduler') || auth.hasRole('director'))

async function resolveSemester() {
  // 教師看已發布課表的學期;管理者看全部學期。取最近一個。
  const list = canManage.value ? await listSemesters() : await publishedSemesters()
  sid.value = list[0]?.id ?? null
}

async function refresh() {
  if (sid.value === null) return
  try {
    const data = await myNotifications(sid.value)
    items.value = data.items
    unread.value = data.unread
  } catch {
    // 靜默:鈴鐺不該打斷使用者
  }
}

onMounted(async () => {
  await resolveSemester()
  await refresh()
  timer = setInterval(refresh, POLL_MS)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})

async function onOpen(show: boolean) {
  if (show) await refresh()
}

async function onAcknowledge(n: Notification) {
  await acknowledge(n.id)
  message.success('已送出確認回覆')
  await refresh()
}

async function onRead(n: Notification) {
  if (n.read_at) return
  await markRead(n.id)
  await refresh()
}

const TYPE_TAG: Record<string, string> = {
  substitution_assigned: '代課通知',
  substitution_cancelled: '代課取消',
  leave_registered: '請假登記',
  leave_cancelled: '銷假',
  timetable_published: '課表發布',
}
</script>

<template>
  <n-popover trigger="click" placement="bottom-end" @update:show="onOpen">
    <template #trigger>
      <n-badge :value="unread" :max="99" data-testid="notif-badge">
        <n-button quaternary circle data-testid="notif-bell">🔔</n-button>
      </n-badge>
    </template>

    <div style="width: min(360px, 80vw)">
      <n-empty v-if="!items.length" description="沒有通知" style="padding: 24px 0" />
      <n-scrollbar v-else style="max-height: 60vh">
        <n-space vertical size="small" style="padding-right: 8px">
          <div
            v-for="n in items" :key="n.id" data-testid="notif-item"
            style="border-bottom: 1px solid var(--n-border-color, #eee); padding-bottom: 8px"
            @mouseenter="onRead(n)"
          >
            <n-space align="center" size="small">
              <n-tag size="tiny" :type="n.acknowledged_at ? 'success' : 'warning'">
                {{ TYPE_TAG[n.type] ?? '通知' }}
              </n-tag>
              <n-text v-if="!n.read_at" type="error" style="font-size: 12px">● 未讀</n-text>
            </n-space>
            <div style="font-weight: 600; margin: 2px 0">{{ n.title }}</div>
            <n-text depth="3" style="font-size: 13px; white-space: pre-wrap">{{ n.body }}</n-text>
            <div style="margin-top: 6px">
              <n-tag v-if="n.acknowledged_at" size="small" type="success">已確認收到</n-tag>
              <n-button
                v-else size="tiny" type="primary" data-testid="notif-ack"
                @click="onAcknowledge(n)"
              >
                確認收到
              </n-button>
            </div>
          </div>
        </n-space>
      </n-scrollbar>
    </div>
  </n-popover>
</template>
