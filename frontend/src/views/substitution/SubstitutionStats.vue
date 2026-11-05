<script setup lang="ts">
import {
  NAlert, NButton, NDatePicker, NEmpty, NRadioButton, NRadioGroup, NSelect, NSpace, NTag, NText,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { listTeachers } from '@/api/basedata'
import { listSemesters } from '@/api/semesters'
import { publishedSemesters } from '@/api/timetables'
import { getMyStats, getStats, statsExportUrl } from '@/api/substitutionStats'
import type { MonthlyReport, StatsPeriod } from '@/api/substitutionStats'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canManage = computed(() =>
  auth.hasRole('admin') || auth.hasRole('scheduler') || auth.hasRole('director'))

const WEEKDAYS = ['週日', '週一', '週二', '週三', '週四', '週五', '週六']
function withWeekday(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return `${iso}(${WEEKDAYS[new Date(y, m - 1, d).getDay()]})`
}

function monthTs(): number {
  const d = new Date()
  return new Date(d.getFullYear(), d.getMonth(), 1).getTime()
}

const route = useRoute()

function initialMonthTs(): number {
  const y = Number(route.query.year)
  const m = Number(route.query.month)
  if (y && m) return new Date(y, m - 1, 1).getTime()
  return monthTs()
}

/** 本機日期 yyyy-mm-dd(不用 toISOString——會轉成 UTC,台灣凌晨會倒退一天) */
function isoOf(ts: number): string {
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** 自訂區間的預設:上個月的「今天的隔天」到今天(15 日結算的學校,11/15 打開就是 10/16~11/15) */
function defaultRange(): [number, number] {
  const t = new Date()
  const today = new Date(t.getFullYear(), t.getMonth(), t.getDate())
  // 上個月的同一天(上個月沒有這一天就取月底,例如 3/31 → 2/28),再加一天
  const lastOfPrev = new Date(t.getFullYear(), t.getMonth(), 0).getDate()
  const sameDayPrev = Math.min(t.getDate(), lastOfPrev)
  const from = new Date(t.getFullYear(), t.getMonth() - 1, sameDayPrev + 1)
  return [from.getTime(), today.getTime()]
}

// 按月或自訂區間(v1.4.11,組長回報:有的學校不是月底結算,而是月中)。
// 記住上次選的方式:每月 15 日結算的學校,下次打開就直接是自訂區間
const MODE_KEY = 'stats-period-mode'
function savedMode(): 'month' | 'range' {
  try {
    return localStorage.getItem(MODE_KEY) === 'range' ? 'range' : 'month'
  } catch {
    return 'month'
  }
}
/** 網址帶 ?date_from=&date_to= 就是自訂區間;帶 ?year=&month= 就是按月(兩者都優先於上次的選擇) */
function tsOf(iso: unknown): number | null {
  if (typeof iso !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).getTime()
}
const qFrom = tsOf(route.query.date_from)
const qTo = tsOf(route.query.date_to)
const initialMode: 'month' | 'range' =
  qFrom !== null && qTo !== null ? 'range' : route.query.year ? 'month' : savedMode()
const mode = ref<'month' | 'range'>(initialMode)
const rangeValue = ref<[number, number]>(
  qFrom !== null && qTo !== null ? [qFrom, qTo] : defaultRange())

function onModeChange(v: 'month' | 'range') {
  mode.value = v
  try {
    localStorage.setItem(MODE_KEY, v)
  } catch {
    // 無痕視窗等讀寫不到時,只是下次不記得
  }
  reload()
}

const semesters = ref<{ id: number; label: string }[]>([])
const sid = ref<number | null>(null)
const monthValue = ref<number>(initialMonthTs())
const teacherOptions = ref<{ label: string; value: number }[]>([])
const teacherId = ref<number | null>(null)
const report = ref<MonthlyReport | null>(null)
const loading = ref(false)
const error = ref('') // 例如自訂區間超過一年

const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))

function period(): StatsPeriod {
  if (mode.value === 'range') {
    return { from: isoOf(rangeValue.value[0]), to: isoOf(rangeValue.value[1]) }
  }
  const d = new Date(monthValue.value)
  return { year: d.getFullYear(), month: d.getMonth() + 1 }
}
const periodLabel = computed(() => {
  const p = period()
  if ('from' in p) return `${p.from.replace(/-/g, '/')} ~ ${p.to.replace(/-/g, '/')}`
  return `${p.year} 年 ${p.month} 月`
})
const totalBillable = computed(() =>
  (report.value?.summaries ?? []).reduce((n, s) => n + s.billable_count, 0))
// 日薪代課(國小常見)按日計酬:沒有用到日薪的學校,畫面和原本完全一樣
const totalDailyDays = computed(() =>
  (report.value?.summaries ?? []).reduce((n, s) => n + s.daily_days, 0))
const hasDaily = computed(() => (report.value?.details ?? []).some((d) => d.pay_kind === 'daily'))
const hasShared = computed(() => (report.value?.details ?? []).some((d) => d.daily_shared))
// 代導(v1.4.0):同一份報表,只分開記全天、半天,代導費由學校自己換算
const hasCover = computed(() => (report.value?.cover_details ?? []).length > 0)
const hasAny = computed(() => !!report.value?.details.length || hasCover.value)
const coverFull = computed(() =>
  (report.value?.summaries ?? []).reduce((n, s) => n + s.cover_full_days, 0))
const coverHalf = computed(() =>
  (report.value?.summaries ?? []).reduce((n, s) => n + s.cover_half_days, 0))
const PAY: Record<string, { label: string; type: 'success' | 'info' | 'default' }> = {
  hourly: { label: '計費', type: 'success' },
  daily: { label: '日薪', type: 'info' },
  none: { label: '不計', type: 'default' },
}

async function reload() {
  if (sid.value === null) return
  loading.value = true
  error.value = ''
  try {
    report.value = canManage.value
      ? await getStats(sid.value, period(), teacherId.value)
      : await getMyStats(sid.value, period())
  } catch (e) {
    report.value = null
    error.value = (e as Error).message || '查詢失敗'
  } finally {
    loading.value = false
  }
}

async function onSemesterChange(id: number) {
  sid.value = id
  if (canManage.value) {
    teacherOptions.value = (await listTeachers(id)).map((t) => ({ label: t.name, value: t.id }))
  }
  await reload()
}

function onExport() {
  if (sid.value === null) return
  window.open(statsExportUrl(sid.value, period(), teacherId.value), '_blank')
}

onMounted(async () => {
  // 教師看不到 /semesters(管理權限),改用已發布學期清單
  semesters.value = canManage.value ? await listSemesters() : await publishedSemesters()
  if (!semesters.value.length) return
  const qsid = Number(route.query.semester_id)
  const initial = semesters.value.find((s) => s.id === qsid)?.id ?? semesters.value[0].id
  await onSemesterChange(initial)
})
</script>

<template>
  <n-space vertical size="large">
    <h2 style="margin: 0">{{ canManage ? '代課鐘點統計' : '我的代課鐘點' }}</h2>

    <n-space align="center" :wrap="true">
      <n-select
        :value="sid" :options="semesterOptions" style="width: 200px"
        placeholder="選擇學期" @update:value="onSemesterChange"
      />
      <n-radio-group :value="mode" size="small" data-testid="stats-mode" @update:value="onModeChange">
        <n-radio-button value="month">按月</n-radio-button>
        <n-radio-button value="range">自訂區間</n-radio-button>
      </n-radio-group>
      <n-date-picker
        v-if="mode === 'month'" v-model:value="monthValue" type="month" style="width: 160px"
        data-testid="stats-month" @update:value="reload"
      />
      <n-date-picker
        v-else v-model:value="rangeValue" type="daterange" style="width: 260px"
        data-testid="stats-range" @update:value="reload"
      />
      <n-select
        v-if="canManage" v-model:value="teacherId" :options="teacherOptions" clearable filterable
        placeholder="全部教師" style="width: 180px"
        data-testid="stats-teacher" @update:value="reload"
      />
      <n-button
        v-if="canManage && hasAny" type="primary"
        data-testid="stats-export" @click="onExport"
      >
        匯出 Excel
      </n-button>
    </n-space>

    <n-space align="center">
      <n-text depth="3">{{ periodLabel }}</n-text>
      <n-tag v-if="report" type="info" data-testid="stats-total">
        計費合計 {{ totalBillable }} 節
      </n-tag>
      <n-tag v-if="hasDaily" type="info" data-testid="stats-total-daily">
        日薪合計 {{ totalDailyDays }} 天
      </n-tag>
      <n-tag v-if="hasCover" type="info" data-testid="stats-total-cover">
        代導合計 全天 {{ coverFull }} 天、半天 {{ coverHalf }} 天
      </n-tag>
    </n-space>

    <n-text v-if="mode === 'range'" depth="3" data-testid="stats-range-hint">
      起訖兩天都算在內(例如每月 15 日結算,就選上個月 16 日到這個月 15 日)。只統計所選學期的紀錄。
    </n-text>

    <n-alert v-if="error" type="warning" :bordered="false" data-testid="stats-error">
      {{ error }}
    </n-alert>

    <n-alert v-if="hasDaily" type="info" :show-icon="true" data-testid="stats-daily-note">
      計費方式為「日薪代課」的節次按日計酬:列在「日薪天數」,不計入鐘點計費節數。
      <template v-if="hasShared">
        標示「分擔」的日子,同一位請假教師的課由兩位以上日薪代課老師分擔,每位各算 1 天,
        實際如何給付請依學校規定核對。
      </template>
    </n-alert>

    <n-empty
      v-if="report && !hasAny && !loading"
      :description="mode === 'range' ? '這段期間沒有代課紀錄' : '本月無代課紀錄'" data-testid="stats-empty"
    />

    <template v-else-if="report && hasAny">
      <!-- 彙總:每位教師 -->
      <table v-if="canManage" class="data-table" data-testid="stats-summary">
        <thead>
          <tr>
            <th>教師</th><th>代課節數</th><th>{{ hasDaily ? '鐘點計費節數' : '計費節數' }}</th>
            <th v-if="hasDaily">日薪天數</th>
            <th v-if="hasCover">代導全天</th>
            <th v-if="hasCover">代導半天</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in report.summaries" :key="s.teacher_id" data-testid="stats-summary-row">
            <td>{{ s.teacher_name }}</td>
            <td>{{ s.handled_count }}</td>
            <td>{{ s.billable_count }}</td>
            <td v-if="hasDaily" data-testid="stats-daily-cell">
              <template v-if="s.daily_days">
                {{ s.daily_days }} 天
                <n-text depth="3">(共 {{ s.daily_periods }} 節)</n-text>
                <n-tag v-if="s.daily_shared_days" size="tiny" type="warning">
                  其中 {{ s.daily_shared_days }} 天分擔
                </n-tag>
              </template>
              <template v-else>—</template>
            </td>
            <td v-if="hasCover" data-testid="stats-cover-full">{{ s.cover_full_days || '—' }}</td>
            <td v-if="hasCover" data-testid="stats-cover-half">{{ s.cover_half_days || '—' }}</td>
          </tr>
        </tbody>
      </table>

      <!-- 明細:逐節 -->
      <table v-if="report.details.length" class="data-table" data-testid="stats-detail">
        <thead>
          <tr>
            <th v-if="canManage">教師</th>
            <th>日期</th><th>節次</th><th>班級</th><th>科目</th>
            <th>原任教師</th><th>假別</th><th>處置</th><th>計費</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(d, i) in report.details" :key="i" data-testid="stats-detail-row">
            <td v-if="canManage">{{ d.handler_name }}</td>
            <td>{{ withWeekday(d.date) }}</td>
            <td>{{ d.period_name }}</td>
            <td>{{ d.class_names }}</td>
            <td>{{ d.subject_name }}</td>
            <td>{{ d.absent_teacher_name }}</td>
            <td>{{ d.leave_type_label }}</td>
            <td>{{ d.sub_type_label }}</td>
            <td>
              <n-tag size="tiny" :type="PAY[d.pay_kind].type" data-testid="stats-pay">
                {{ PAY[d.pay_kind].label }}
              </n-tag>
              <n-tag v-if="d.daily_shared" size="tiny" type="warning">分擔</n-tag>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- 代導明細:逐天 -->
      <template v-if="hasCover">
        <h3 class="sub-title">代導明細</h3>
        <n-text depth="3">
          代導以天為單位,一班一天算一次;半天假的代導另外計算,代導費請依學校規定換算。
        </n-text>
        <table class="data-table" data-testid="stats-cover-detail">
          <thead>
            <tr>
              <th v-if="canManage">教師</th>
              <th>日期</th><th>班級</th><th>時段</th><th>原導師</th><th>假別</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(d, i) in report.cover_details" :key="i" data-testid="stats-cover-row">
              <td v-if="canManage">{{ d.handler_name }}</td>
              <td>{{ withWeekday(d.date) }}</td>
              <td>{{ d.class_name }}</td>
              <td>{{ d.part_label }}</td>
              <td>{{ d.absent_teacher_name }}</td>
              <td>{{ d.leave_type_label }}</td>
            </tr>
          </tbody>
        </table>
      </template>
    </template>
  </n-space>
</template>

<style scoped>
.data-table { border-collapse: collapse; width: 100%; }
.data-table th, .data-table td {
  border: 1px solid var(--n-border-color, #e0e0e0); padding: 6px 10px; text-align: left;
  white-space: nowrap;
}
.data-table th { background: rgba(128, 128, 128, 0.08); font-weight: 600; }
.sub-title { margin: 8px 0 0; font-size: 16px; }
</style>
