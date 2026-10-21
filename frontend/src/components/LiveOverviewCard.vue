<script setup lang="ts">
// 儀表板即時概況(v1.3.3,Issue #50):現在這一節各班實際在上什麼課、誰在上。
// 已套用當天的調代課;下課、早自習、午休時列下一節。每分鐘自動更新。
import { NButton, NCard, NTag } from 'naive-ui'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { getLiveOverview, openPatrolSheets } from '@/api/substitutionLog'
import type { LiveOverview, LiveSection } from '@/api/substitutionLog'

const props = defineProps<{ semesterId: number }>()

const WEEKDAYS = ['週日', '週一', '週二', '週三', '週四', '週五', '週六']
const REFRESH_MS = 60_000

const live = ref<LiveOverview | null>(null)
let timer: ReturnType<typeof setInterval> | undefined

async function load() {
  try {
    live.value = await getLiveOverview(props.semesterId)
  } catch {
    // 沒有權限(一般教師)或暫時連不上:不顯示這張卡,下一分鐘再試
  }
}

onMounted(() => {
  load()
  timer = setInterval(load, REFRESH_MS)
})
onUnmounted(() => clearInterval(timer))

const title = computed(() => {
  const v = live.value
  if (!v) return '即時概況'
  const [, m, d] = v.date.split('-').map(Number)
  return `即時概況 · ${m}/${d}(${WEEKDAYS[v.weekday % 7]})${v.time}`
})

function heading(s: LiveSection): string {
  const range = `${s.period_name}(${s.start}–${s.end})`
  return s.state === 'in_class' ? `上課中:${range}` : `${s.now_label}中,下一節是${range}`
}

/** 有異動的格子標顏色:請假還沒安排最要緊 */
function noteType(note: string): 'error' | 'warning' | 'info' {
  if (note.includes('請假待處理')) return 'error'
  if (note.includes('停課') || note.includes('自習')) return 'warning'
  return 'info'
}
</script>

<template>
  <n-card v-if="live" data-testid="dash-live" :title="title">
    <template #header-extra>
      <span class="hint">每分鐘自動更新</span>
    </template>

    <p v-if="live.message" class="line" data-testid="live-message">{{ live.message }}</p>

    <section v-for="s in live.sections" :key="s.table_name" class="section" data-testid="live-section">
      <h3 v-if="s.table_name" class="table-name">{{ s.table_name }}</h3>
      <p v-if="s.message" class="line" data-testid="live-message">{{ s.message }}</p>
      <template v-else>
        <p class="period" data-testid="live-period">{{ heading(s) }}</p>
        <div class="grid">
          <div
            v-for="c in s.cells"
            :key="c.class_name"
            class="tile"
            :class="{ changed: c.note, empty: !c.subject }"
            :data-testid="`live-${c.class_name}`"
          >
            <div class="klass">{{ c.class_name }}</div>
            <template v-if="c.subject">
              <div class="subject">{{ c.subject }}</div>
              <div class="teacher">{{ c.teacher || '—' }}</div>
              <div v-if="c.room" class="room">{{ c.room }}</div>
              <n-tag v-if="c.note" size="small" :type="noteType(c.note)" :bordered="false">
                {{ c.note }}
              </n-tag>
            </template>
            <div v-else class="none">沒有課</div>
          </div>
        </div>
      </template>
    </section>

    <div v-if="!live.message" class="actions">
      <n-button size="small" @click="openPatrolSheets(semesterId, live.date)">
        看今天整天的巡堂表
      </n-button>
    </div>
  </n-card>
</template>

<style scoped>
.hint { color: #666; font-size: 12px; }
.line { margin: 0; color: #666; }
.section + .section { margin-top: 16px; }
.table-name { margin: 0 0 6px; font-size: 15px; }
.period { margin: 0 0 10px; font-weight: 600; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(118px, 1fr));
  gap: 8px;
}
.tile {
  border: 1px solid #e5e5e5;
  border-radius: 6px;
  padding: 8px 10px;
  min-width: 0;
  overflow-wrap: anywhere;
}
.tile.changed { border-color: #f0a020; background: #fffaf0; }
.tile.empty { background: #fafafa; }
.klass { font-weight: 700; margin-bottom: 2px; }
.subject { font-size: 15px; }
.teacher { color: #555; font-size: 13px; }
.room { color: #666; font-size: 12px; }
.none { color: #666; font-size: 13px; }
.tile :deep(.n-tag) { margin-top: 4px; }
.actions { margin-top: 12px; }
</style>
