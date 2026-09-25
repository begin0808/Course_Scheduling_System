<script setup lang="ts">
// 通知單列印頁:調課單(v1.2.2)與代課單(v1.2.5),一張一頁(A4 直式)。
// 版面照使用學校現行的紙本:週課表,只在有異動的格子寫「日期/科目/第三行」。
// 兩種單子格線相同,差在抬頭與表頭欄位:代課單多了請假教師、假別、計費方式。
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import type { ApiError } from '@/api/client'
import { getSubstituteSlips, getSwapSlips } from '@/api/substitutions'
import type { Slip, SlipCell, SlipRow, Slips } from '@/api/substitutions'

const DAY_NAMES = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']

const route = useRoute()
const data = ref<Slips | null>(null)
const error = ref('')
const loading = ref(true)

const isSwap = computed(() => !route.path.startsWith('/substitute-slips'))

// 一週一頁:跨週的調課(例如本週與隔三週對調)會印成同一位老師/班級的兩頁
const pages = computed(() =>
  (data.value?.slips ?? []).flatMap((slip) => slip.weeks.map((week) => ({ slip, week }))))

function heading(slip: Slip): string {
  if (isSwap.value) return `●${slip.kind === 'teacher' ? '教師' : '班級'}調課通知單●`
  return slip.kind === 'teacher' ? '代課　通知單' : '班級代課　通知單'
}

function rowsOf(slip: Slip): SlipRow[] {
  if (slip.rows.length) return slip.rows
  // 節次表查不到時退而求其次:依格子用到的最大節次畫列,沒有時間
  const max = Math.max(1, ...slip.weeks.flatMap((w) => w.cells.map((c) => c.ordinal)))
  return Array.from({ length: max }, (_, i) => ({
    ordinal: i + 1, start_time: null, end_time: null, afternoon_starts: false,
  }))
}

function cellsAt(cells: SlipCell[], day: string, ordinal: number): SlipCell[] {
  return cells.filter((c) => c.date === day && c.ordinal === ordinal)
}

const hhmm = (t: string | null) => (t ? t.slice(0, 5) : '')

function doPrint() {
  window.print()
}
function doClose() {
  window.close()
}

onMounted(async () => {
  const sid = Number(route.query.semester_id)
  const ids = String(route.query.ids ?? '').split(',').map(Number).filter(Boolean)
  const fetch = isSwap.value ? getSwapSlips : getSubstituteSlips
  try {
    data.value = await fetch(sid, ids)
  } catch (e) {
    error.value = (e as ApiError).message || (isSwap.value ? '無法產生調課單' : '無法產生代課單')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="slips">
    <div class="no-print toolbar">
      <span v-if="data" class="hint">共 {{ pages.length }} 張</span>
      <button type="button" data-testid="slips-print" @click="doPrint">列印</button>
      <button type="button" @click="doClose">關閉</button>
    </div>

    <p v-if="loading" class="msg">載入中…</p>
    <p v-else-if="error" class="msg" data-testid="slips-error">{{ error }}</p>

    <section
      v-for="({ slip, week }, i) in pages" :key="i" class="page"
      :data-testid="slip.kind === 'teacher' ? 'slip-teacher' : 'slip-class'"
    >
      <!-- 調課單:校名一行、單別一行;代課單照紙本把校名與單別排成一行 -->
      <template v-if="isSwap">
        <h1 class="school">{{ data?.title }}</h1>
        <h2 class="kind">{{ heading(slip) }}</h2>
      </template>
      <h1 v-else class="school one-line">{{ data?.title }}　{{ heading(slip) }}</h1>

      <div v-if="isSwap && slip.kind === 'teacher'" class="meta">
        <div class="meta-line">
          <span class="big">調課教師：{{ slip.teacher_name }}</span>
          <span class="big">調課班級：{{ slip.class_names }}</span>
        </div>
        <div class="small">調課日期：{{ slip.date_from }}~{{ slip.date_to }}</div>
      </div>
      <div v-else-if="isSwap" class="meta meta-line">
        <span class="big">調課班級：{{ slip.class_names }}</span>
        <span class="small">調課日期：{{ slip.date_from }}~{{ slip.date_to }}</span>
      </div>
      <div v-else class="meta">
        <div class="meta-line">
          <span v-if="slip.kind === 'teacher'" class="big">代課教師：{{ slip.teacher_name }}</span>
          <span v-else class="big">代課班級：{{ slip.class_names }}</span>
          <span class="big">請假教師：{{ slip.absent_teacher_name }}</span>
        </div>
        <div class="meta-line small" data-testid="slip-leave-meta">
          <span>日期：{{ slip.date_from }} ~ {{ slip.date_to }}</span>
          <span>假別：{{ slip.leave_type_name }}</span>
          <span>計費方式：{{ slip.funding_label || '—' }}</span>
        </div>
      </div>

      <table class="grid">
        <colgroup>
          <col style="width: 7%">
          <col style="width: 10%">
          <col v-for="day in week.days" :key="day">
        </colgroup>
        <thead>
          <tr>
            <th colspan="2" class="corner">
              <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                <line x1="0" y1="0" x2="100" y2="100" vector-effect="non-scaling-stroke" />
              </svg>
            </th>
            <th v-for="(day, d) in week.days" :key="day">
              {{ DAY_NAMES[d] }}<br><span class="date">{{ day }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rowsOf(slip)" :key="row.ordinal"
            :class="{ afternoon: row.afternoon_starts }"
          >
            <td class="ordinal">{{ row.ordinal }}</td>
            <td class="time">
              <template v-if="row.start_time">
                {{ hhmm(row.start_time) }}<br>|<br>{{ hhmm(row.end_time) }}
              </template>
            </td>
            <td v-for="day in week.days" :key="day" class="cell">
              <div
                v-for="(c, k) in cellsAt(week.cells, day, row.ordinal)" :key="k"
                data-testid="slip-cell"
              >
                {{ c.date }}<br>{{ c.subject_name }}<br>{{ c.actor }}
                <template v-if="c.code"><br>[{{ c.code }}]</template>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.slips {
  color: #000;
  background: #fff;
  font-family: "DFKai-SB", "BiauKai", "標楷體", "Kaiti TC", serif;
}
.toolbar { display: flex; gap: 8px; justify-content: flex-end; align-items: center; padding: 16px 24px 0; }
.toolbar button {
  padding: 6px 16px; cursor: pointer; border: 1px solid #888; border-radius: 4px; background: #f4f4f4;
}
.hint { color: #555; font-size: 14px; }
.msg { text-align: center; padding: 40px 0; font-size: 15px; }
.page { max-width: 720px; margin: 0 auto; padding: 32px 24px; }
.page + .page { border-top: 1px dashed #bbb; }
.school { font-size: 22px; font-weight: normal; text-align: center; margin: 0; }
.school.one-line { margin-bottom: 18px; }
.kind { font-size: 20px; font-weight: normal; text-align: center; margin: 2px 0 18px; }
.meta { margin-bottom: 18px; }
.meta-line { display: flex; justify-content: space-between; align-items: baseline; }
.big { font-size: 19px; }
.small { font-size: 13px; margin-top: 6px; }
.grid {
  width: 100%; border-collapse: collapse; table-layout: fixed; border: 4px double #000;
}
.grid th, .grid td { border: 1px solid #000; text-align: center; vertical-align: middle; }
.grid th { font-weight: normal; font-size: 14px; height: 72px; border-bottom-width: 2px; }
.grid .date { font-size: 13px; }
/* 斜線用 SVG 畫在格子內容裡:用背景畫的話,瀏覽器列印預設不印背景,紙本上會變空白格 */
.corner { position: relative; padding: 0; }
.corner svg { position: absolute; inset: 0; width: 100%; height: 100%; }
.corner line { stroke: #000; stroke-width: 1; }
.grid td { height: 70px; font-size: 13px; line-height: 1.35; }
.grid td.ordinal { font-size: 20px; }
.grid td.time { font-size: 11px; line-height: 1.2; }
.grid td.time { border-right-width: 2px; }
tr.afternoon td { border-top-width: 2px; }

@media print {
  @page { size: A4 portrait; margin: 12mm; }
  .no-print { display: none !important; }
  .page { max-width: none; padding: 0; break-after: page; }
  .page + .page { border-top: none; }
  .page:last-child { break-after: auto; }
}
</style>
