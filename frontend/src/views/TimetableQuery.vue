<script setup lang="ts">
import { NCard, NEmpty, NRadioButton, NRadioGroup, NSelect, NSpace, NTag, NText } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import TimetableGrid from '@/components/timetable/TimetableGrid.vue'
import type { GridEntry, PeriodCell } from '@/components/timetable/types'
import { getMyTeacher, getPublishedTimetable, publishedSemesters } from '@/api/timetables'
import type { NamedBrief, PublicSemester, PublishedTimetable } from '@/api/timetables'

const semesters = ref<PublicSemester[]>([])
const sid = ref<number | null>(null)
const data = ref<PublishedTimetable | null>(null)
const me = ref<NamedBrief | null>(null)
const loading = ref(true)

const view = ref<'class' | 'teacher' | 'room'>('class')
const classId = ref<number | null>(null)
const teacherId = ref<number | null>(null)
const roomId = ref<number | null>(null)

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
const periods = computed<PeriodCell[]>(() => (activeTable.value?.periods ?? []) as PeriodCell[])
const numWeekdays = computed(() => activeTable.value?.num_weekdays ?? 5)

const entries = computed<GridEntry[]>(() => {
  const all = data.value?.entries ?? []
  let list = all
  if (view.value === 'class') list = classId.value ? all.filter((e) => e.class_ids.includes(classId.value!)) : []
  else if (view.value === 'teacher') list = teacherId.value ? all.filter((e) => e.teacher_ids.includes(teacherId.value!)) : []
  else list = roomId.value ? all.filter((e) => e.room_id === roomId.value) : []
  return list.map((e) => ({
    id: e.id, weekday: e.weekday, period_no: e.period_no, span: e.span, locked: false,
    subject: e.subject,
    teacher: view.value === 'class' ? e.teachers.join('、') : e.classes.join('、'),
    room: e.room ?? undefined,
  }))
})
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

      <n-card size="small" data-testid="tq-grid">
        <n-empty v-if="periods.length === 0" description="此學期尚無節次表" />
        <TimetableGrid
          v-else
          :periods="periods" :num-weekdays="numWeekdays" :entries="entries" readonly
        />
      </n-card>
      <n-text depth="3" style="font-size: 12px">課表為唯讀檢視;如有異動請洽教學組。</n-text>
    </template>
  </n-space>
</template>
