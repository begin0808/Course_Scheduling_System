<script setup lang="ts">
import {
  NButton, NButtonGroup, NCard, NDatePicker, NEmpty, NRadioButton, NRadioGroup, NSelect, NSpace,
  NTag, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref, watch } from 'vue'
import { crossTableNote, extraRows } from '@/components/timetable/crossTable'
import { mergeGroups } from '@/components/timetable/groupCells'
import { dayLabels, weekEntries } from '@/components/timetable/weekCells'
import TimetableGrid from '@/components/timetable/TimetableGrid.vue'
import type { GridEntry, PeriodCell } from '@/components/timetable/types'
import {
  getMyTeacher, getPublishedTimetable, getPublishedWeek, publishedSemesters,
} from '@/api/timetables'
import type { NamedBrief, PublicSemester, PublishedTimetable, TimetableWeek } from '@/api/timetables'
import {
  exportBatchZip, exportSchoolPdf, exportSchoolWorkbook, exportTimetable,
} from '@/api/exports'
import type { ExportFmt } from '@/api/exports'
import { useAuthStore } from '@/stores/auth'

const semesters = ref<PublicSemester[]>([])
const sid = ref<number | null>(null)
const data = ref<PublishedTimetable | null>(null)
const me = ref<NamedBrief | null>(null)
const loading = ref(true)

const message = useMessage()
const auth = useAuthStore()
const canManage = computed(() =>
  auth.hasRole('admin') || auth.hasRole('scheduler') || auth.hasRole('director'))

const view = ref<'class' | 'teacher' | 'room'>('class')
const classId = ref<number | null>(null)
const teacherId = ref<number | null>(null)
const roomId = ref<number | null>(null)
const exporting = ref(false)

const targetId = computed(() =>
  view.value === 'class' ? classId.value
    : view.value === 'teacher' ? teacherId.value : roomId.value)

async function onExport(fmt: ExportFmt) {
  if (sid.value === null || targetId.value === null) return
  exporting.value = true
  try {
    await exportTimetable(sid.value, view.value, targetId.value, fmt)
  } catch (e) {
    message.error((e as Error).message || '匯出失敗')
  } finally {
    exporting.value = false
  }
}

// 全校匯出跟著目前的檢視走:班級視角出班級版,教師視角出教師版(使用者回報 #22)。
// 場地沒有這個需求,切到場地時不顯示這兩個按鈕。
const batchView = computed<'class' | 'teacher' | null>(() =>
  view.value === 'class' || view.value === 'teacher' ? view.value : null)
const batchLabel = computed(() => (batchView.value === 'teacher' ? '全校教師' : '全校班級'))

// 全校總表、批次 zip 都可以選 Excel 或 PDF(批次 PDF 是 LINE 社群組長要的,v1.4.6)。
// PDF 要在背景渲染,全校約十幾秒,按鈕轉圈並先說一聲,免得以為當掉。
type AllKind = 'school-xlsx' | 'school-pdf' | 'batch-xlsx' | 'batch-pdf'
const exportingAll = ref<AllKind | null>(null)

async function onExportAll(kind: AllKind) {
  if (sid.value === null || batchView.value === null) return
  exporting.value = true
  exportingAll.value = kind
  if (kind.endsWith('pdf')) message.info('正在產生 PDF,全校約需十幾秒,請稍候…')
  try {
    if (kind === 'school-xlsx') await exportSchoolWorkbook(sid.value, batchView.value)
    else if (kind === 'school-pdf') await exportSchoolPdf(sid.value, batchView.value)
    else await exportBatchZip(sid.value, batchView.value, kind === 'batch-pdf' ? 'pdf' : 'xlsx')
  } catch (e) {
    message.error((e as Error).message || '匯出失敗')
  } finally {
    exporting.value = false
    exportingAll.value = null
  }
}

const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))
const classOptions = computed(() =>
  (data.value?.classes ?? []).map((c) => ({ label: `${c.grade}年${c.name}`, value: c.id })))
const teacherOptions = computed(() =>
  (data.value?.teachers ?? []).map((t) => ({ label: t.name, value: t.id })))
const roomOptions = computed(() =>
  (data.value?.rooms ?? []).map((r) => ({ label: r.name, value: r.id })))

async function load(id: number) {
  sid.value = id
  ;[data.value, me.value] = await Promise.all([getPublishedTimetable(id), getMyTeacher(id)])
  const d = data.value
  if (!d) return
  classId.value = d.classes[0]?.id ?? null
  roomId.value = d.rooms[0]?.id ?? null
  // 教師登入且已綁定 → 預設顯示本人課表
  if (me.value) {
    view.value = 'teacher'
    teacherId.value = me.value.id
  } else {
    teacherId.value = d.teachers[0]?.id ?? null
  }
}

onMounted(async () => {
  try {
    semesters.value = await publishedSemesters()
    if (semesters.value.length) await load(semesters.value[0].id)
  } finally {
    loading.value = false
  }
})

const defaultTable = computed(() => {
  const ts = data.value?.period_tables ?? []
  return ts.find((t) => t.is_default) ?? ts[0] ?? null
})
/** 班級視角用該班所屬節次表;教師/場地視角用學期預設表。 */
const activeTable = computed(() => {
  if (view.value === 'class' && classId.value) {
    const c = data.value?.classes.find((x) => x.id === classId.value)
    if (c?.period_table_id) {
      return data.value?.period_tables.find((t) => t.id === c.period_table_id) ?? defaultTable.value
    }
  }
  return defaultTable.value
})
const numWeekdays = computed(() => activeTable.value?.num_weekdays ?? 5)

const shownEntries = computed(() => {
  const all = data.value?.entries ?? []
  if (view.value === 'class') return classId.value ? all.filter((e) => e.class_ids.includes(classId.value!)) : []
  if (view.value === 'teacher') return teacherId.value ? all.filter((e) => e.teacher_ids.includes(teacherId.value!)) : []
  return roomId.value ? all.filter((e) => e.room_id === roomId.value) : []
})
/** 教師/場地視角:預設表沒有、但這位老師(這間場地)用得到的節次列要補上(如高中部的第八節)。 */
const periods = computed<PeriodCell[]>(() => {
  const base = (activeTable.value?.periods ?? []) as PeriodCell[]
  if (view.value === 'class') return base
  return [...base, ...extraRows(
    shownEntries.value, data.value?.classes ?? [], data.value?.period_tables ?? [], activeTable.value,
  ) as PeriodCell[]]
})

// ── 某一週實際課表(v1.4.15,老師建議):選了日期就看那一週調代課之後的樣子,異動標色 ──
const weekTs = ref<number | null>(null)
const weekData = ref<TimetableWeek | null>(null)
const weekError = ref('')
const weekMode = computed(() => weekTs.value !== null && view.value !== 'room')

function isoDate(ts: number): string {
  const d = new Date(ts)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function shiftWeek(n: number) {
  const base = weekTs.value ?? Date.now()
  const d = new Date(base)
  weekTs.value = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 7 * n).getTime()
}
function thisWeek() {
  const d = new Date()
  weekTs.value = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

async function loadWeek() {
  weekData.value = null
  weekError.value = ''
  if (!weekMode.value || sid.value === null || targetId.value === null) return
  const v = view.value as 'class' | 'teacher'
  try {
    weekData.value = await getPublishedWeek(sid.value, v, targetId.value, isoDate(weekTs.value!))
  } catch (e) {
    weekError.value = (e as Error).message || '無法載入這一週的課表'
  }
}
watch([sid, view, targetId, weekTs], loadWeek)

const weekLabels = computed(() => (weekMode.value && weekData.value ? dayLabels(weekData.value) : null))
const weekChanges = computed(() =>
  (weekData.value?.cells ?? []).filter((c) => c.kind !== 'normal').length)

const fixedEntries = computed<GridEntry[]>(() => {
  // 跑班群組同一節的各組課併成一格(v1.4.13);教師課表本來就只有自己那一組
  const shown = view.value === 'teacher' ? shownEntries.value : mergeGroups(shownEntries.value)
  return shown.map((e) => ({
    id: e.id, weekday: e.weekday, period_no: e.period_no, span: e.span, locked: false,
    subject: e.subject,
    teacher: view.value === 'class' ? e.teachers.join('、') : e.classes.join('、'),
    room: e.room ?? undefined,
    // 教師/場地視角照預設節次表畫格線;另一套節次表的課要標出實際時間
    note: view.value === 'class' ? undefined : crossTableNote(
      e, data.value?.classes ?? [], data.value?.period_tables ?? [], activeTable.value),
    // 單雙週(v1.3.0):同一格單週、雙週兩堂上下並列
    week: e.week_parity === 'odd' ? '單' as const : e.week_parity === 'even' ? '雙' as const : undefined,
  }))
})

const entries = computed<GridEntry[]>(() =>
  weekMode.value ? (weekData.value ? weekEntries(weekData.value, periods.value) : []) : fixedEntries.value)
</script>

<template>
  <n-space vertical size="large">
    <n-space align="center" :wrap="true">
      <h1 style="margin: 0">課表查詢</h1>
      <n-select
        v-if="semesters.length > 1" :value="sid" :options="semesterOptions"
        style="width: 200px" @update:value="load"
      />
      <n-tag v-if="data" size="small" type="success">
        {{ data.semester_label }} · {{ data.name }}(已發布)
      </n-tag>
    </n-space>

    <n-card v-if="!loading && !data" size="small">
      <n-empty description="目前尚無已發布的課表" data-testid="tq-none" />
    </n-card>

    <template v-else-if="data">
      <n-space align="center" :wrap="true">
        <n-radio-group v-model:value="view">
          <n-radio-button value="class" data-testid="tq-view-class">班級</n-radio-button>
          <n-radio-button value="teacher" data-testid="tq-view-teacher">教師</n-radio-button>
          <n-radio-button value="room" data-testid="tq-view-room">場地</n-radio-button>
        </n-radio-group>
        <n-select
          v-if="view === 'class'" v-model:value="classId" data-testid="tq-class"
          :options="classOptions" style="width: 160px" filterable
        />
        <n-select
          v-else-if="view === 'teacher'" v-model:value="teacherId" data-testid="tq-teacher"
          :options="teacherOptions" style="width: 160px" filterable
        />
        <n-select
          v-else v-model:value="roomId" data-testid="tq-room"
          :options="roomOptions" style="width: 160px" filterable
        />
        <n-tag v-if="me && view === 'teacher' && teacherId === me.id" size="small" type="info">
          本人課表
        </n-tag>
      </n-space>

      <n-space v-if="view !== 'room'" align="center" :wrap="true">
        <n-text depth="3" style="font-size: 13px">看某一週(含調代課):</n-text>
        <n-date-picker
          v-model:value="weekTs" type="date" clearable style="width: 170px"
          placeholder="選日期,清空回固定課表" data-testid="tq-week"
        />
        <n-button-group size="small">
          <n-button data-testid="tq-week-prev" @click="shiftWeek(-1)">上一週</n-button>
          <n-button data-testid="tq-week-this" @click="thisWeek">本週</n-button>
          <n-button data-testid="tq-week-next" @click="shiftWeek(1)">下一週</n-button>
        </n-button-group>
        <n-button v-if="weekTs !== null" size="small" quaternary data-testid="tq-week-clear" @click="weekTs = null">
          回到固定課表
        </n-button>
        <template v-if="weekMode && weekData">
          <n-tag size="small" :type="weekChanges ? 'warning' : 'default'" data-testid="tq-week-tag">
            {{ weekChanges ? `這週有 ${weekChanges} 節異動` : '這週沒有異動' }}
          </n-tag>
          <n-space size="small" style="font-size: 12px">
            <span style="color: #1f4fd8">藍:代課、併班</span>
            <span style="color: #d00000">紅:調課</span>
            <span><s>劃線</s>:原本的課沒上</span>
            <span style="color: #c05800">橘:請假還沒安排</span>
          </n-space>
        </template>
        <n-text v-if="weekError" type="error" style="font-size: 12px">{{ weekError }}</n-text>
      </n-space>

      <n-space align="center" :wrap="true">
        <n-text depth="3" style="font-size: 13px">匯出目前課表:</n-text>
        <n-button-group>
          <n-button
            size="small" :disabled="targetId === null || exporting"
            data-testid="export-xlsx" @click="onExport('xlsx')"
          >
            Excel
          </n-button>
          <n-button
            size="small" :loading="exporting" :disabled="targetId === null"
            data-testid="export-pdf" @click="onExport('pdf')"
          >
            PDF
          </n-button>
          <n-button
            size="small" :loading="exporting" :disabled="targetId === null"
            data-testid="export-png" @click="onExport('png')"
          >
            PNG
          </n-button>
        </n-button-group>
        <template v-if="canManage && batchView">
          <n-text depth="3" style="font-size: 13px">{{ batchLabel }}:</n-text>
          <n-text depth="3" style="font-size: 13px">總表</n-text>
          <n-button-group>
            <n-button
              size="small" :disabled="exporting" :loading="exportingAll === 'school-xlsx'"
              data-testid="export-school" @click="onExportAll('school-xlsx')"
            >
              Excel
            </n-button>
            <n-button
              size="small" :disabled="exporting" :loading="exportingAll === 'school-pdf'"
              data-testid="export-school-pdf" @click="onExportAll('school-pdf')"
            >
              PDF
            </n-button>
          </n-button-group>
          <n-text depth="3" style="font-size: 13px">批次 zip</n-text>
          <n-button-group>
            <n-button
              size="small" :disabled="exporting" :loading="exportingAll === 'batch-xlsx'"
              data-testid="export-batch" @click="onExportAll('batch-xlsx')"
            >
              Excel
            </n-button>
            <n-button
              size="small" :disabled="exporting" :loading="exportingAll === 'batch-pdf'"
              data-testid="export-batch-pdf" @click="onExportAll('batch-pdf')"
            >
              PDF
            </n-button>
          </n-button-group>
          <n-text depth="3" style="font-size: 12px">
            {{ batchView === 'teacher'
              ? '總表:全部在一個檔;批次:每位在職教師一個檔(含沒排到課的)'
              : '總表:全部在一個檔;批次:每班一個檔' }}
          </n-text>
        </template>
      </n-space>

      <n-card size="small" data-testid="tq-grid">
        <n-empty v-if="periods.length === 0" description="此學期尚無節次表" />
        <TimetableGrid
          v-else
          :periods="periods" :num-weekdays="numWeekdays" :entries="entries" readonly
          :day-labels="weekLabels"
        />
      </n-card>
      <n-text depth="3" style="font-size: 12px">
        課表為唯讀檢視;如有異動請洽教學組。{{ weekMode ? '匯出的是固定課表,不含這一週的調代課。' : '' }}
      </n-text>
    </template>
  </n-space>
</template>
