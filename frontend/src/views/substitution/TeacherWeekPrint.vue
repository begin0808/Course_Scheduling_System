<script setup lang="ts">
// 全校教師週總表列印頁(v1.4.14),A3 橫式。版面照學校手做的那張表:
//   老師為欄、日期 × 節次為列,格子寫「班級 科目」;
//   劃線 = 原本的課沒上,藍字 = 代課/併班,紅字 = 調課(記號指向對調的另一節)。
// 老師多時每頁放 TEACHERS_PER_PAGE 位,同一週分成幾頁印。
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import type { ApiError } from '@/api/client'
import { getTeacherWeekSheets } from '@/api/substitutionLog'
import type { TeacherWeekItem, TeacherWeekSheets } from '@/api/substitutionLog'

const TEACHERS_PER_PAGE = 16
const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']

const route = useRoute()
const data = ref<TeacherWeekSheets | null>(null)
const error = ref('')
const loading = ref(true)

function md(iso: string): string {
  const [, m, d] = iso.split('-').map(Number)
  return `${m}/${d}`
}
function weekday(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return WEEKDAYS[(new Date(y, m - 1, d).getDay() + 6) % 7]
}
function sunday(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  const s = new Date(y, m - 1, d + 6)
  return `${s.getMonth() + 1}/${s.getDate()}`
}

interface DayBlock {
  date: string
  rows: { ordinal: number; cells: TeacherWeekItem[][] }[]
}
interface Page {
  monday: string
  part: number
  parts: number
  teachers: { name: string; role: string }[]
  days: DayBlock[]
}

const pages = computed<Page[]>(() => {
  const d = data.value
  if (!d) return []
  const out: Page[] = []
  const chunks = Math.max(1, Math.ceil(d.teachers.length / TEACHERS_PER_PAGE))
  for (const week of d.weeks) {
    for (let c = 0; c < chunks; c++) {
      const lo = c * TEACHERS_PER_PAGE
      const hi = lo + TEACHERS_PER_PAGE
      const days: DayBlock[] = []
      for (const row of week.rows) {
        let block = days[days.length - 1]
        if (!block || block.date !== row.date) {
          block = { date: row.date, rows: [] }
          days.push(block)
        }
        block.rows.push({ ordinal: row.ordinal, cells: row.cells.slice(lo, hi) })
      }
      out.push({
        monday: week.monday, part: c + 1, parts: chunks,
        teachers: d.teachers.slice(lo, hi), days,
      })
    }
  }
  return out
})

function doPrint() {
  window.print()
}
function doClose() {
  window.close()
}

onMounted(async () => {
  const sid = Number(route.query.semester_id)
  const from = String(route.query.from ?? '')
  const weeks = Number(route.query.weeks ?? 1)
  try {
    data.value = await getTeacherWeekSheets(sid, from, weeks)
  } catch (e) {
    error.value = (e as ApiError).message || '無法產生教師週總表'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="tw">
    <div class="no-print toolbar">
      <span v-if="data" class="hint">共 {{ pages.length }} 頁(A3 橫式;用 A4 印請在列印設定選「縮放至紙張大小」)</span>
      <button type="button" data-testid="tw-print" @click="doPrint">列印</button>
      <button type="button" @click="doClose">關閉</button>
    </div>

    <p v-if="loading" class="msg">載入中…</p>
    <p v-else-if="error" class="msg" data-testid="tw-error">{{ error }}</p>

    <section v-for="(page, i) in pages" :key="i" class="page" data-testid="tw-page">
      <h1 class="title">
        <span class="school">{{ data?.title }}教師週總表</span>
        <span>{{ md(page.monday) }}~{{ sunday(page.monday) }}</span>
        <span v-if="page.parts > 1" class="part">({{ page.part }}/{{ page.parts }})</span>
        <span class="legend">{{ data?.legend }}</span>
      </h1>
      <table class="grid">
        <colgroup>
          <col style="width: 44px">
          <col style="width: 26px">
          <col v-for="t in page.teachers" :key="t.name">
        </colgroup>
        <thead>
          <tr>
            <th>星期</th>
            <th>節</th>
            <th v-for="(t, k) in page.teachers" :key="k" data-testid="tw-teacher">
              <div>{{ t.name }}</div>
              <div v-if="t.role" class="role">{{ t.role }}</div>
            </th>
          </tr>
        </thead>
        <tbody v-for="day in page.days" :key="day.date" class="day">
          <tr v-for="(row, r) in day.rows" :key="row.ordinal">
            <td v-if="r === 0" :rowspan="day.rows.length" class="date">
              {{ md(day.date) }}<br>({{ weekday(day.date) }})
            </td>
            <td class="ordinal">{{ row.ordinal }}</td>
            <td v-for="(items, k) in row.cells" :key="k" data-testid="tw-cell">
              <div v-for="(item, n) in items" :key="n" :class="['item', item.kind]">
                <span class="text">{{ item.text }}</span>
                <span v-if="item.note" class="note">{{ item.note }}</span>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.tw {
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
.page { max-width: 1500px; margin: 0 auto; padding: 24px; overflow-x: auto; }
.page + .page { border-top: 1px dashed #bbb; }
.title { display: flex; flex-wrap: wrap; gap: 14px; align-items: baseline; margin: 0 0 6px; font-size: 15px; font-weight: normal; }
.title .school { font-size: 19px; font-weight: bold; }
.part { font-size: 14px; }
.legend { font-size: 12px; color: #333; }
.grid { width: 100%; min-width: 900px; border-collapse: collapse; table-layout: fixed; border: 2px solid #000; }
.grid th, .grid td {
  border: 1px solid #000; text-align: center; vertical-align: middle;
  font-size: 11px; line-height: 1.2; padding: 1px 2px; overflow-wrap: anywhere;
}
.grid th { font-weight: normal; font-size: 12px; height: 34px; }
.role { font-size: 10px; }
tbody.day { border-top: 2px solid #000; }
.date { font-size: 12px; }
.ordinal { font-size: 12px; }
.grid td { height: 22px; }
.item + .item { margin-top: 2px; }
.note { display: block; font-size: 10px; }
.off .text, .pending .text { text-decoration: line-through; color: #777; }
.off .note { color: #555; }
.pending .note { color: #c05800; }
.cover { color: #1f4fd8; }
.swap { color: #d00000; }

@media print {
  @page { size: A3 landscape; margin: 8mm; }
  .no-print { display: none !important; }
  .page { max-width: none; padding: 0; overflow: visible; break-after: page; }
  .page + .page { border-top: none; }
  .page:last-child { break-after: auto; }
  .grid { min-width: 0; }
  tbody.day { break-inside: avoid; }
  .tw { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
</style>
