<script setup lang="ts">
import {
  NAlert, NButton, NCard, NEmpty, NRadioButton, NRadioGroup, NSelect, NSpace, NTag, NText,
  useMessage,
} from 'naive-ui'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import TimetableGrid from '@/components/timetable/TimetableGrid.vue'
import type { DragData, DropFeedback, GridEntry, PeriodCell } from '@/components/timetable/types'
import type { ApiError } from '@/api/client'
import { listAssignments } from '@/api/assignments'
import type { Assignment } from '@/api/assignments'
import { listClassUnits, listRooms, listTeachers } from '@/api/basedata'
import type { ClassUnit, Room, Teacher } from '@/api/basedata'
import { getSemester, listSemesters } from '@/api/semesters'
import type { PeriodTable, SemesterListItem } from '@/api/semesters'
import {
  checkConflict, conflictText, createTimetable, deleteEntry, getClassPeriodTable, getTimetable,
  listTimetables, lockEntry, moveEntry, placeEntry,
} from '@/api/timetables'
import type { Timetable, TimetableBrief } from '@/api/timetables'

const message = useMessage()

const semesters = ref<SemesterListItem[]>([])
const sid = ref<number | null>(null)
const drafts = ref<TimetableBrief[]>([])
const ttId = ref<number | null>(null)
const tt = ref<Timetable | null>(null)

const assignments = ref<Assignment[]>([])
const classes = ref<ClassUnit[]>([])
const teachers = ref<Teacher[]>([])
const rooms = ref<Room[]>([])
const defaultTable = ref<PeriodTable | null>(null)
const periods = ref<PeriodCell[]>([])
const numWeekdays = ref(5)

const view = ref<'class' | 'teacher' | 'room'>('class')
const classId = ref<number | null>(null)
const teacherId = ref<number | null>(null)
const roomId = ref<number | null>(null)

const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))
const draftOptions = computed(() => drafts.value.map((d) => ({ label: d.name, value: d.id })))
const classOptions = computed(() =>
  classes.value.map((c) => ({ label: `${c.grade}年${c.name}`, value: c.id })))
const teacherOptions = computed(() => teachers.value.map((t) => ({ label: t.name, value: t.id })))
const roomOptions = computed(() => rooms.value.map((r) => ({ label: r.name, value: r.id })))

// 拖拉排課僅在班級視角進行;教師/場地視角為唯讀檢視(避免跨節次表的節次號對不齊)
const readonly = computed(() => view.value !== 'class')

async function loadSemester(id: number) {
  sid.value = id
  const [sem, as, cs, ts, rs] = await Promise.all([
    getSemester(id), listAssignments(id), listClassUnits(id), listTeachers(id), listRooms(id),
  ])
  assignments.value = as
  classes.value = cs
  teachers.value = ts
  rooms.value = rs
  defaultTable.value = sem.period_tables.find((p) => p.is_default) ?? sem.period_tables[0] ?? null

  drafts.value = await listTimetables(id)
  if (drafts.value.length === 0) {
    const created = await createTimetable(id, '草稿A')
    drafts.value = await listTimetables(id)
    ttId.value = created.id
  } else {
    ttId.value = drafts.value[0].id
  }
  classId.value = cs[0]?.id ?? null
  teacherId.value = ts[0]?.id ?? null
  roomId.value = rs[0]?.id ?? null
  await refreshTimetable()
  await loadPeriods()
}

async function refreshTimetable() {
  if (ttId.value) tt.value = await getTimetable(ttId.value)
}

async function loadPeriods() {
  let table: PeriodTable | null = defaultTable.value
  if (view.value === 'class' && classId.value) {
    try {
      table = await getClassPeriodTable(classId.value)
    } catch {
      table = defaultTable.value
    }
  }
  periods.value = (table?.periods ?? []) as PeriodCell[]
  numWeekdays.value = table?.num_weekdays ?? 5
}

onMounted(async () => {
  semesters.value = await listSemesters()
  if (semesters.value.length) await loadSemester(semesters.value[0].id)
  window.addEventListener('keydown', onKey)
})
onUnmounted(() => window.removeEventListener('keydown', onKey))

async function onViewChange() {
  clearDrag()
  await loadPeriods()
}
async function onClassChange(id: number) {
  classId.value = id
  await loadPeriods()
}
async function onDraftChange(id: number) {
  ttId.value = id
  undoStack.value = []
  redoStack.value = []
  await refreshTimetable()
}

// ── 格位 → 元件資料 ──
const visibleEntries = computed<GridEntry[]>(() => {
  const all = tt.value?.entries ?? []
  let list = all
  if (view.value === 'class') list = classId.value ? all.filter((e) => e.class_ids.includes(classId.value!)) : []
  else if (view.value === 'teacher') list = teacherId.value ? all.filter((e) => e.teacher_ids.includes(teacherId.value!)) : []
  else list = roomId.value ? all.filter((e) => e.room_id === roomId.value) : []
  return list.map((e) => ({
    id: e.id, weekday: e.weekday, period_no: e.period_no, span: e.span, locked: e.locked,
    subject: e.subject,
    teacher: view.value === 'class' ? e.teachers.join('、') : e.classes.join('、'),
    room: e.room ?? undefined,
  }))
})

// ── 未排課務(班級視角)──
const placedByAssignment = computed(() => {
  const m = new Map<number, number>()
  for (const e of tt.value?.entries ?? []) {
    m.set(e.course_assignment_id, (m.get(e.course_assignment_id) ?? 0) + e.span)
  }
  return m
})
interface TrayItem { a: Assignment; remaining: number; span: number }
const trayItems = computed<TrayItem[]>(() => {
  if (view.value !== 'class' || !classId.value) return []
  return assignments.value
    .filter((a) => a.scheduling_unit.classes.some((c) => c.id === classId.value))
    .map((a) => {
      const remaining = a.periods_per_week - (placedByAssignment.value.get(a.id) ?? 0)
      const b = a.block_rules[0]
      const span = b && remaining >= b.block_size ? b.block_size : 1
      return { a, remaining, span }
    })
    .filter((x) => x.remaining > 0)
})
const totalRemaining = computed(() => trayItems.value.reduce((n, x) => n + x.remaining, 0))

// ── 拖拉與衝突檢查 ──
interface WbDrag extends DragData { assignmentId: number; span: number }
const dragging = ref<WbDrag | null>(null)
const feedback = ref<DropFeedback | null>(null)
let lastKey = ''
let checkToken = 0

function clearDrag() {
  dragging.value = null
  feedback.value = null
  lastKey = ''
}

function onTrayDragStart(item: TrayItem, ev: DragEvent) {
  const data: WbDrag = { source: 'tray', assignmentId: item.a.id, span: item.span }
  dragging.value = data
  ev.dataTransfer?.setData('application/json', JSON.stringify(data))
  if (ev.dataTransfer) ev.dataTransfer.effectAllowed = 'move'
}
function onGridDragStart(data: DragData) {
  const e = tt.value?.entries.find((x) => x.id === data.entryId)
  if (!e) return
  dragging.value = { source: 'grid', entryId: e.id, assignmentId: e.course_assignment_id, span: e.span }
}

async function onCheck(p: { weekday: number; period_no: number }) {
  const d = dragging.value
  if (!d || !ttId.value) return
  const key = `${p.weekday}-${p.period_no}`
  if (key === lastKey) return // dragover 會連續觸發,同格只查一次
  lastKey = key
  const token = ++checkToken
  try {
    const res = await checkConflict(ttId.value, {
      course_assignment_id: d.assignmentId, weekday: p.weekday, period_no: p.period_no,
      span: d.span, ...(d.source === 'grid' ? { ignore_entry_id: d.entryId as number } : {}),
    })
    if (token !== checkToken) return // 丟棄過期回應
    feedback.value = {
      weekday: p.weekday, period_no: p.period_no,
      ok: res.ok, reason: res.conflicts[0]?.message,
    }
  } catch { /* 檢查失敗不阻擋 UI */ }
}

async function onDrop(p: { weekday: number; period_no: number }) {
  const d = dragging.value
  if (!d || !ttId.value) return
  const id = ttId.value
  clearDrag()
  try {
    if (d.source === 'tray') {
      const before = new Set((tt.value?.entries ?? []).map((e) => e.id))
      const updated = await placeEntry(id, {
        course_assignment_id: d.assignmentId, weekday: p.weekday,
        period_no: p.period_no, span: d.span,
      })
      tt.value = updated
      let createdId = updated.entries.find((e) => !before.has(e.id))?.id
      pushUndo({
        undo: async () => { if (createdId) await deleteEntry(id, createdId); await refreshTimetable() },
        redo: async () => {
          const before2 = new Set((tt.value?.entries ?? []).map((e) => e.id))
          const u = await placeEntry(id, {
            course_assignment_id: d.assignmentId, weekday: p.weekday,
            period_no: p.period_no, span: d.span,
          })
          tt.value = u
          createdId = u.entries.find((e) => !before2.has(e.id))?.id
        },
      })
    } else {
      const e = tt.value!.entries.find((x) => x.id === d.entryId)!
      const from = { weekday: e.weekday, period_no: e.period_no }
      const to = { weekday: p.weekday, period_no: p.period_no }
      tt.value = await moveEntry(id, e.id, to)
      pushUndo({
        undo: async () => { tt.value = await moveEntry(id, e.id, from) },
        redo: async () => { tt.value = await moveEntry(id, e.id, to) },
      })
    }
  } catch (err) {
    message.error(conflictText((err as ApiError).detail))
  }
}

async function onTrayDrop(ev: DragEvent) {
  ev.preventDefault()
  const d = dragging.value
  clearDrag()
  if (!d || d.source !== 'grid' || !ttId.value) return
  const id = ttId.value
  const e = tt.value?.entries.find((x) => x.id === d.entryId)
  if (!e) return
  if (e.locked) { message.warning('鎖定格位不可移除,請先解鎖'); return }
  const snap = { aid: e.course_assignment_id, weekday: e.weekday, period_no: e.period_no, span: e.span }
  let curId = e.id
  try {
    await deleteEntry(id, curId)
    await refreshTimetable()
    pushUndo({
      undo: async () => {
        const u = await placeEntry(id, {
          course_assignment_id: snap.aid, weekday: snap.weekday,
          period_no: snap.period_no, span: snap.span,
        })
        tt.value = u
        const back = u.entries.find(
          (x) => x.course_assignment_id === snap.aid && x.weekday === snap.weekday
            && x.period_no === snap.period_no)
        if (back) curId = back.id
      },
      redo: async () => { await deleteEntry(id, curId); await refreshTimetable() },
    })
  } catch (err) {
    message.error(conflictText((err as ApiError).detail))
  }
}

async function onSelect(g: GridEntry) {
  if (readonly.value || !ttId.value) return
  const id = ttId.value
  const e = tt.value?.entries.find((x) => x.id === g.id)
  if (!e) return
  const next = !e.locked
  tt.value = await lockEntry(id, e.id, next)
  message.info(next ? `已鎖定「${e.subject}」` : `已解鎖「${e.subject}」`)
  pushUndo({
    undo: async () => { tt.value = await lockEntry(id, e.id, !next) },
    redo: async () => { tt.value = await lockEntry(id, e.id, next) },
  })
}

// ── 復原 / 重做(command stack,上限 20 步)──
interface Cmd { undo: () => Promise<void>; redo: () => Promise<void> }
const UNDO_LIMIT = 20
const undoStack = ref<Cmd[]>([])
const redoStack = ref<Cmd[]>([])
const busy = ref(false)

function pushUndo(c: Cmd) {
  undoStack.value.push(c)
  if (undoStack.value.length > UNDO_LIMIT) undoStack.value.shift()
  redoStack.value = []
}
async function doUndo() {
  const c = undoStack.value.pop()
  if (!c || busy.value) return
  busy.value = true
  try { await c.undo(); redoStack.value.push(c) } catch { message.error('復原失敗') } finally { busy.value = false }
}
async function doRedo() {
  const c = redoStack.value.pop()
  if (!c || busy.value) return
  busy.value = true
  try { await c.redo(); undoStack.value.push(c) } catch { message.error('重做失敗') } finally { busy.value = false }
}
function onKey(ev: KeyboardEvent) {
  if (!(ev.ctrlKey || ev.metaKey)) return
  const k = ev.key.toLowerCase()
  if (k === 'z' && !ev.shiftKey) { ev.preventDefault(); void doUndo() }
  else if (k === 'y' || (k === 'z' && ev.shiftKey)) { ev.preventDefault(); void doRedo() }
}
</script>

<template>
  <n-space vertical size="large">
    <n-space align="center" :wrap="true">
      <h1 style="margin: 0">排課工作台</h1>
      <n-select
        :value="sid" :options="semesterOptions" placeholder="選擇學期"
        style="width: 200px" @update:value="loadSemester"
      />
      <n-select
        v-if="drafts.length" :value="ttId" :options="draftOptions"
        style="width: 140px" @update:value="onDraftChange"
      />
      <n-button size="small" data-testid="wb-undo" :disabled="!undoStack.length" @click="doUndo">
        復原 (Ctrl+Z)
      </n-button>
      <n-button size="small" data-testid="wb-redo" :disabled="!redoStack.length" @click="doRedo">
        重做
      </n-button>
      <n-text depth="3" style="font-size: 12px">變更即時儲存</n-text>
    </n-space>

    <n-alert v-if="!sid" type="info">請先建立學期並完成配課,再回此頁排課。</n-alert>

    <template v-else>
      <n-space align="center">
        <n-radio-group :value="view" @update:value="(v: 'class'|'teacher'|'room') => { view = v; onViewChange() }">
          <n-radio-button value="class" data-testid="wb-view-class">班級視角</n-radio-button>
          <n-radio-button value="teacher" data-testid="wb-view-teacher">教師視角</n-radio-button>
          <n-radio-button value="room" data-testid="wb-view-room">場地視角</n-radio-button>
        </n-radio-group>
        <n-select
          v-if="view === 'class'" :value="classId" data-testid="wb-class"
          :options="classOptions" style="width: 180px" filterable @update:value="onClassChange"
        />
        <n-select
          v-else-if="view === 'teacher'" v-model:value="teacherId" data-testid="wb-teacher"
          :options="teacherOptions" style="width: 180px" filterable
        />
        <n-select
          v-else v-model:value="roomId" data-testid="wb-room"
          :options="roomOptions" style="width: 180px" filterable
        />
        <n-tag v-if="readonly" size="small" type="warning">唯讀檢視(排課請切回班級視角)</n-tag>
      </n-space>

      <div class="wb-layout">
        <n-card size="small" style="flex: 1; min-width: 0">
          <n-empty v-if="periods.length === 0" description="此學期尚無節次表" />
          <TimetableGrid
            v-else
            :periods="periods" :num-weekdays="numWeekdays" :entries="visibleEntries"
            :dragging="dragging" :feedback="feedback" :readonly="readonly"
            @dragstart="onGridDragStart" @dragend="clearDrag"
            @check="onCheck" @drop="onDrop" @select="onSelect"
          />
        </n-card>

        <n-card
          v-if="!readonly" size="small" class="wb-tray" data-testid="wb-tray"
          @dragover.prevent @drop="onTrayDrop"
        >
          <template #header>
            <n-space align="center" size="small">
              <span>未排課務</span>
              <n-tag size="small" :type="totalRemaining === 0 ? 'success' : 'info'" data-testid="wb-remaining">
                剩 {{ totalRemaining }} 節
              </n-tag>
            </n-space>
          </template>
          <n-space vertical size="small">
            <n-text v-if="trayItems.length === 0" depth="3" data-testid="wb-tray-empty">
              本班課務已全部排入 🎉
            </n-text>
            <div
              v-for="item in trayItems" :key="item.a.id"
              class="tray-item" :data-testid="`wb-tray-${item.a.subject.name}`" draggable="true"
              @dragstart="onTrayDragStart(item, $event)" @dragend="clearDrag"
            >
              <div class="tray-subject">
                {{ item.a.subject.name }}
                <n-tag v-if="item.span > 1" size="tiny" type="warning">{{ item.span }}連堂</n-tag>
              </div>
              <div class="tray-meta">
                {{ item.a.teachers.map((t) => t.name).join('、') }} · 剩 {{ item.remaining }} 節
              </div>
            </div>
            <n-text depth="3" style="font-size: 12px">
              拖曳到左側格子排課;拖回此處移除;點格內卡片可鎖定/解鎖。
            </n-text>
          </n-space>
        </n-card>
      </div>
    </template>
  </n-space>
</template>

<style scoped>
.wb-layout { display: flex; gap: 20px; align-items: flex-start; }
.wb-tray { width: 260px; flex-shrink: 0; }
.tray-item {
  border: 1px solid var(--n-border-color, #e2e2e2); border-radius: 6px; padding: 8px 10px;
  cursor: grab; background: rgba(24, 160, 88, 0.08);
}
.tray-subject { font-weight: 600; display: flex; align-items: center; gap: 6px; }
.tray-meta { font-size: 12px; opacity: 0.75; }
@media (max-width: 900px) { .wb-layout { flex-direction: column; } .wb-tray { width: 100%; } }
</style>
