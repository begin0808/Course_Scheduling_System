<script setup lang="ts">
import {
  NAlert, NButton, NCard, NCheckbox, NDivider, NEmpty, NInputNumber, NModal, NPopconfirm,
  NRadioButton, NRadioGroup, NSelect, NSpace, NTag, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  WEEK_LABELS, createAlternate, createAssignment, createGroup, deleteAssignment, deleteGroup,
  listAlternates, listAssignments, listGroups, updateAssignment, teacherLoad, classLoad,
} from '@/api/assignments'
import type {
  Assignment, AssignmentPayload, ClassLoad, SchedulingUnit, TeacherLoad, WeekParity,
} from '@/api/assignments'
import { listClassUnits, listRooms, listSubjects, listTeachers, ROOM_TYPE_LABELS } from '@/api/basedata'
import type { ClassUnit, Room, Subject, Teacher } from '@/api/basedata'
import { listSemesters } from '@/api/semesters'
import type { SemesterListItem } from '@/api/semesters'

const message = useMessage()

const semesters = ref<SemesterListItem[]>([])
const sid = ref<number | null>(null)
const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))

const classes = ref<ClassUnit[]>([])
const subjects = ref<Subject[]>([])
const teachers = ref<Teacher[]>([])
const rooms = ref<Room[]>([])
const groups = ref<SchedulingUnit[]>([])
const alternates = ref<SchedulingUnit[]>([])
const assignments = ref<Assignment[]>([])
const loads = ref<TeacherLoad[]>([])
const classLoads = ref<ClassLoad[]>([])

const classOptions = computed(() =>
  classes.value.map((c) => ({ label: `${c.grade}年${c.name}`, value: c.id })))
const subjectOptions = computed(() => subjects.value.map((s) => ({ label: s.name, value: s.id })))
const teacherOptions = computed(() => teachers.value.map((t) => ({ label: t.name, value: t.id })))
const roomOptions = computed(() => rooms.value.map((r) => ({ label: r.name, value: r.id })))
const roomTypeOptions = Object.entries(ROOM_TYPE_LABELS).map(([value, label]) => ({ label, value }))
const groupOptions = computed(() => groups.value.map((g) => ({ label: g.name, value: g.id })))
const alternateOptions = computed(() =>
  alternates.value.map((g) => ({ label: g.name, value: g.id })))
/** 單雙週組已經配了哪幾週(引導組長補齊另一筆) */
function weeksOf(u: SchedulingUnit): { odd?: Assignment; even?: Assignment } {
  const out: { odd?: Assignment; even?: Assignment } = {}
  for (const a of assignments.value) {
    if (a.scheduling_unit.id === u.id && a.week_parity) out[a.week_parity] = a
  }
  return out
}

async function loadBase(id: number) {
  ;[classes.value, subjects.value, teachers.value, rooms.value] = await Promise.all([
    listClassUnits(id), listSubjects(id), listTeachers(id), listRooms(id),
  ])
}
async function reloadAll(id: number) {
  ;[assignments.value, groups.value, alternates.value, loads.value, classLoads.value] =
    await Promise.all([
      listAssignments(id), listGroups(id), listAlternates(id), teacherLoad(id), classLoad(id),
    ])
}
async function onSemesterChange(id: number) {
  sid.value = id
  await loadBase(id)
  await reloadAll(id)
}

onMounted(async () => {
  semesters.value = await listSemesters()
  if (semesters.value.length) await onSemesterChange(semesters.value[0].id)
})

const overCapacity = computed(() => classLoads.value.filter((c) => c.over_capacity))
// 超鐘點本身是合法的(超出的節數另計鐘點費),只有超過上限才是問題。
// 舊版把任何 delta>0 都標紅,會讓正常配課看起來像出錯。
function loadTagType(l: TeacherLoad): 'success' | 'error' | 'warning' | 'info' {
  if (l.over_limit) return 'error'
  if (l.delta > 0) return 'warning'
  if (l.delta < 0) return 'info'
  return 'success'
}

// 單雙週的課鐘點算一半,可能出現 .5
function num(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1)
}

function loadTagText(l: TeacherLoad): string {
  if (l.delta > 0) {
    return l.over_limit
      ? `+${num(l.delta)} 超過上限 ${l.max_overtime}`
      : `+${num(l.delta)} 超鐘點`
  }
  return l.delta < 0 ? `${num(l.delta)} 不足` : '剛好'
}

// ── 配課 modal ──
const show = ref(false)
const editingId = ref<number | null>(null)
interface AForm {
  target: 'single' | 'group' | 'alternate'
  class_id: number | null
  scheduling_unit_id: number | null
  subject_id: number | null
  teacher_ids: number[]
  lead_teacher_id: number | null
  periods_per_week: number
  block_rules: { block_size: number; count_per_week: number }[]
  required_room_type: string | null
  room_id: number | null
  lock_room: boolean
  week_parity: WeekParity | null
}
function emptyForm(): AForm {
  return {
    target: 'single', class_id: null, scheduling_unit_id: null, subject_id: null,
    teacher_ids: [], lead_teacher_id: null, periods_per_week: 1, block_rules: [],
    required_room_type: null, room_id: null, lock_room: false, week_parity: null,
  }
}
const form = ref<AForm>(emptyForm())
const leadOptions = computed(() =>
  teachers.value.filter((t) => form.value.teacher_ids.includes(t.id))
    .map((t) => ({ label: t.name, value: t.id })))

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  show.value = true
}
/** 從單雙週組卡片直接新增那一組缺的那一週 */
function openCreateWeek(u: SchedulingUnit, week: WeekParity, from?: Assignment) {
  editingId.value = null
  form.value = {
    ...emptyForm(), target: 'alternate', scheduling_unit_id: u.id, week_parity: week,
    // 另一週的節數與連堂要相同,先帶入
    periods_per_week: from?.periods_per_week ?? 1,
    block_rules: from?.block_rules.map((b) => ({ ...b })) ?? [],
  }
  show.value = true
}
function openEdit(a: Assignment) {
  editingId.value = a.id
  const kind = a.scheduling_unit.unit_type
  const isGroup = kind !== 'single'
  form.value = {
    target: kind === 'alternate' ? 'alternate' : isGroup ? 'group' : 'single',
    week_parity: a.week_parity,
    class_id: isGroup ? null : (a.scheduling_unit.classes[0]?.id ?? null),
    scheduling_unit_id: isGroup ? a.scheduling_unit.id : null,
    subject_id: a.subject.id,
    teacher_ids: a.teachers.map((t) => t.teacher_id),
    lead_teacher_id: a.teachers.find((t) => t.is_lead)?.teacher_id ?? null,
    periods_per_week: a.periods_per_week,
    block_rules: a.block_rules.map((b) => ({ block_size: b.block_size, count_per_week: b.count_per_week })),
    required_room_type: a.required_room_type,
    room_id: a.room_id,
    lock_room: a.lock_room,
  }
  show.value = true
}
function addBlock() {
  form.value.block_rules.push({ block_size: 2, count_per_week: 1 })
}
function removeBlock(i: number) {
  form.value.block_rules.splice(i, 1)
}

async function save() {
  const f = form.value
  if (f.target === 'single' && !f.class_id) return message.warning('請選擇班級')
  if (f.target === 'group' && !f.scheduling_unit_id) return message.warning('請選擇跑班群組')
  if (f.target === 'alternate' && !f.scheduling_unit_id) return message.warning('請選擇單雙週組')
  if (f.target === 'alternate' && !f.week_parity) return message.warning('請選擇單週或雙週')
  if (!f.subject_id) return message.warning('請選擇科目')
  if (f.teacher_ids.length === 0) return message.warning('請至少指定一位教師')
  const lead = f.lead_teacher_id && f.teacher_ids.includes(f.lead_teacher_id)
    ? f.lead_teacher_id : f.teacher_ids[0]
  const payload: AssignmentPayload = {
    class_id: f.target === 'single' ? f.class_id : null,
    scheduling_unit_id: f.target === 'single' ? null : f.scheduling_unit_id,
    week_parity: f.target === 'alternate' ? f.week_parity : null,
    subject_id: f.subject_id,
    periods_per_week: f.periods_per_week,
    teachers: f.teacher_ids.map((id) => ({ teacher_id: id, is_lead: id === lead })),
    block_rules: f.block_rules,
    required_room_type: (f.required_room_type as AssignmentPayload['required_room_type']) || null,
    room_id: f.room_id,
    lock_room: f.lock_room,
  }
  try {
    if (editingId.value) await updateAssignment(editingId.value, payload)
    else await createAssignment(sid.value!, payload)
    show.value = false
    message.success('已儲存配課')
    await reloadAll(sid.value!)
  } catch (e) {
    message.error((e as ApiError).detail || '儲存失敗')
  }
}
async function removeAssignment(a: Assignment) {
  await deleteAssignment(a.id)
  message.success('已刪除')
  await reloadAll(sid.value!)
}

// ── 跑班群組 modal ──
const groupShow = ref(false)
const groupForm = ref<{ name: string; class_ids: number[] }>({ name: '', class_ids: [] })
function openGroup() {
  groupForm.value = { name: '', class_ids: [] }
  groupShow.value = true
}
async function saveGroup() {
  if (!groupForm.value.name) return message.warning('請輸入群組名稱')
  if (groupForm.value.class_ids.length < 2) return message.warning('跑班群組至少需 2 個班級')
  try {
    await createGroup(sid.value!, groupForm.value)
    groupShow.value = false
    message.success('已建立跑班群組')
    await reloadAll(sid.value!)
  } catch (e) {
    message.error((e as ApiError).detail || '建立失敗')
  }
}
async function removeGroup(g: SchedulingUnit) {
  try {
    await deleteGroup(g.id)
    message.success('已刪除群組')
    await reloadAll(sid.value!)
  } catch (e) {
    message.error((e as ApiError).detail || '刪除失敗(群組可能仍有配課)')
  }
}

// ── 單雙週組 modal ──
const altShow = ref(false)
const altClass = ref<number | null>(null)
function openAlternate() {
  altClass.value = null
  altShow.value = true
}
async function saveAlternate() {
  if (!altClass.value) return message.warning('請選擇班級')
  try {
    const u = await createAlternate(sid.value!, { class_id: altClass.value })
    altShow.value = false
    message.success(`已建立「${u.name}」,接著新增單週與雙週的課`)
    await reloadAll(sid.value!)
  } catch (e) {
    message.error((e as ApiError).detail || '建立失敗')
  }
}

function unitLabel(a: Assignment): string {
  const u = a.scheduling_unit
  if (u.unit_type === 'group') return `${u.name}(跑班)`
  if (u.unit_type === 'alternate') {
    return `${u.name}(${a.week_parity ? WEEK_LABELS[a.week_parity] : '未設週別'})`
  }
  const c = u.classes[0]
  return c ? `${c.grade}年${c.name}` : u.name
}
function blockLabel(a: Assignment): string {
  if (a.block_rules.length === 0) return '—'
  return a.block_rules.map((b) => `${b.block_size}連堂×${b.count_per_week}`).join('、')
}
</script>

<template>
  <n-space vertical size="large">
    <n-space align="center">
      <h1 style="margin: 0">配課管理</h1>
      <n-select
        :value="sid" :options="semesterOptions" placeholder="選擇學期"
        style="width: 240px" @update:value="onSemesterChange"
      />
    </n-space>

    <n-alert v-if="!sid" type="info">請先建立學期並於基礎資料建立班級、科目、教師。</n-alert>

    <div v-else class="layout">
      <!-- 主區:配課清單 -->
      <n-space vertical size="large" style="flex: 1; min-width: 0">
        <n-space>
          <n-button type="primary" data-testid="assignment-add" @click="openCreate">新增配課</n-button>
          <n-button data-testid="group-add" @click="openGroup">新增跑班群組</n-button>
          <n-button data-testid="alt-add" @click="openAlternate">新增單雙週組</n-button>
        </n-space>

        <n-card title="配課清單" size="small">
          <n-empty v-if="assignments.length === 0" description="尚無配課" />
          <table v-else class="data-table">
            <thead>
              <tr><th>排課單位</th><th>科目</th><th>教師</th><th>週節數</th><th>連堂</th><th>場地</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="a in assignments" :key="a.id">
                <td>{{ unitLabel(a) }}</td>
                <td>{{ a.subject.name }}</td>
                <td>
                  <n-space size="small">
                    <n-tag
                      v-for="t in a.teachers" :key="t.teacher_id" size="small"
                      :type="t.is_lead ? 'success' : 'default'"
                    >
                      {{ t.name }}{{ t.is_lead ? '(主教)' : '' }}
                    </n-tag>
                  </n-space>
                </td>
                <td>{{ a.periods_per_week }}</td>
                <td>{{ blockLabel(a) }}</td>
                <td>{{ a.required_room_type ? ROOM_TYPE_LABELS[a.required_room_type] : '—' }}</td>
                <td>
                  <n-space>
                    <n-button size="tiny" @click="openEdit(a)">編輯</n-button>
                    <n-popconfirm @positive-click="removeAssignment(a)">
                      <template #trigger><n-button size="tiny" type="error" ghost>刪除</n-button></template>
                      確定刪除此配課?
                    </n-popconfirm>
                  </n-space>
                </td>
              </tr>
            </tbody>
          </table>
        </n-card>

        <n-card v-if="alternates.length" title="單雙週組" size="small" data-testid="alt-list">
          <n-text depth="3" style="display: block; margin-bottom: 8px">
            同一格單週、雙週輪流上兩門課(學期第一週為單週)。單週、雙週各配一筆,節數與連堂要相同。
          </n-text>
          <n-space vertical size="small">
            <n-space
              v-for="u in alternates" :key="u.id" align="center" justify="space-between"
              :data-testid="`alt-${u.name}`"
            >
              <n-space align="center" size="small">
                <strong>{{ u.name }}</strong>
                <template v-for="w in (['odd', 'even'] as const)" :key="w">
                  <n-tag v-if="weeksOf(u)[w]" size="small" type="success">
                    {{ WEEK_LABELS[w] }}:{{ weeksOf(u)[w]!.subject.name }}
                    {{ weeksOf(u)[w]!.teachers.map((t) => t.name).join('、') }}
                  </n-tag>
                  <n-button
                    v-else size="tiny" type="warning" dashed :data-testid="`alt-add-${w}`"
                    @click="openCreateWeek(u, w, weeksOf(u)[w === 'odd' ? 'even' : 'odd'])"
                  >
                    + 新增{{ WEEK_LABELS[w] }}的課
                  </n-button>
                </template>
              </n-space>
              <n-popconfirm @positive-click="removeGroup(u)">
                <template #trigger><n-button size="tiny" type="error" ghost>刪除</n-button></template>
                刪除單雙週組將一併移除其配課,確定?
              </n-popconfirm>
            </n-space>
          </n-space>
        </n-card>

        <n-card v-if="groups.length" title="跑班群組" size="small">
          <n-space vertical size="small">
            <n-space v-for="g in groups" :key="g.id" align="center" justify="space-between">
              <n-text>
                <strong>{{ g.name }}</strong>
                <n-text depth="3" style="margin-left: 8px">
                  {{ g.classes.map((c) => `${c.grade}年${c.name}`).join('、') }}
                </n-text>
              </n-text>
              <n-popconfirm @positive-click="removeGroup(g)">
                <template #trigger><n-button size="tiny" type="error" ghost>刪除群組</n-button></template>
                刪除群組將一併移除其配課,確定?
              </n-popconfirm>
            </n-space>
          </n-space>
        </n-card>
      </n-space>

      <!-- 側欄:鐘點統計 -->
      <div class="sidebar">
        <n-card title="教師鐘點" size="small" data-testid="teacher-load">
          <n-empty v-if="loads.length === 0" description="尚無教師" size="small" />
          <table v-else class="data-table compact">
            <thead><tr><th>教師</th><th>已配/應授</th><th>狀態</th></tr></thead>
            <tbody>
              <tr v-for="l in loads" :key="l.teacher_id">
                <td>{{ l.name }}</td>
                <td>{{ num(l.assigned) }} / {{ l.target }}</td>
                <td>
                  <n-tag size="tiny" :type="loadTagType(l)">
                    {{ loadTagText(l) }}
                  </n-tag>
                </td>
              </tr>
            </tbody>
          </table>
        </n-card>

        <n-card title="班級節數警告" size="small" style="margin-top: 16px">
          <n-empty v-if="overCapacity.length === 0" description="各班配課未超出可排節次" size="small" />
          <n-space v-else vertical size="small" data-testid="class-warning">
            <n-alert v-for="c in overCapacity" :key="c.class_id" type="warning" :show-icon="false">
              {{ c.grade }}年{{ c.name }}:配課 {{ c.assigned }} 節 &gt; 可排 {{ c.capacity }} 節
            </n-alert>
          </n-space>
        </n-card>
      </div>
    </div>

    <!-- 配課 modal -->
    <n-modal v-model:show="show" preset="card" :title="editingId ? '編輯配課' : '新增配課'" style="max-width: 520px">
      <n-space vertical>
        <n-text>排課對象</n-text>
        <n-radio-group v-model:value="form.target">
          <n-radio-button value="single">單一班級</n-radio-button>
          <n-radio-button value="group">跑班群組</n-radio-button>
          <n-radio-button value="alternate" data-testid="a-target-alt">單雙週組</n-radio-button>
        </n-radio-group>
        <n-select
          v-if="form.target === 'single'" v-model:value="form.class_id"
          data-testid="a-class" :options="classOptions" placeholder="選擇班級" filterable
        />
        <n-select
          v-else-if="form.target === 'group'" v-model:value="form.scheduling_unit_id"
          :options="groupOptions" placeholder="選擇跑班群組(需先建立)"
        />
        <template v-else>
          <n-select
            v-model:value="form.scheduling_unit_id" data-testid="a-alt-unit"
            :options="alternateOptions" placeholder="選擇單雙週組(需先建立)"
          />
          <n-radio-group v-model:value="form.week_parity" data-testid="a-week">
            <n-radio-button value="odd">單週</n-radio-button>
            <n-radio-button value="even">雙週</n-radio-button>
          </n-radio-group>
        </template>

        <n-text>科目</n-text>
        <n-select v-model:value="form.subject_id" data-testid="a-subject" :options="subjectOptions" filterable placeholder="選擇科目" />

        <n-text>授課教師(可多位協同,第一位預設主教)</n-text>
        <n-select v-model:value="form.teacher_ids" data-testid="a-teachers" multiple :options="teacherOptions" filterable placeholder="選擇教師" />
        <n-select
          v-if="form.teacher_ids.length > 1" v-model:value="form.lead_teacher_id"
          :options="leadOptions" placeholder="指定主教教師"
        />

        <n-space>
          <n-space vertical style="flex: 1">
            <n-text>每週節數</n-text>
            <n-input-number v-model:value="form.periods_per_week" data-testid="a-periods" :min="1" :max="40" />
          </n-space>
        </n-space>

        <n-space align="center" justify="space-between">
          <n-text>連堂規則</n-text>
          <n-button size="tiny" dashed data-testid="a-add-block" @click="addBlock">+ 新增連堂</n-button>
        </n-space>
        <n-space v-for="(b, i) in form.block_rules" :key="i" align="center">
          <n-input-number
            v-model:value="b.block_size" :data-testid="`a-block-size-${i}`"
            :min="2" :max="4" style="width: 110px"
          />
          <n-text>連堂 ×</n-text>
          <n-input-number
            v-model:value="b.count_per_week" :data-testid="`a-block-count-${i}`"
            :min="1" style="width: 110px"
          />
          <n-text>次/週</n-text>
          <n-button size="tiny" type="error" ghost @click="removeBlock(i)">移除</n-button>
        </n-space>

        <n-divider style="margin: 4px 0" />
        <n-text>場地需求(選填)</n-text>
        <n-space>
          <n-select v-model:value="form.required_room_type" :options="roomTypeOptions" clearable placeholder="場地類型" style="flex: 1" />
          <n-select v-model:value="form.room_id" :options="roomOptions" clearable placeholder="指定場地" style="flex: 1" />
        </n-space>
        <n-checkbox v-model:checked="form.lock_room">鎖定場地(排課不得更動)</n-checkbox>

        <n-button type="primary" data-testid="a-save" @click="save">儲存</n-button>
      </n-space>
    </n-modal>

    <!-- 單雙週組 modal -->
    <n-modal v-model:show="altShow" preset="card" title="新增單雙週組" style="max-width: 460px">
      <n-space vertical>
        <n-text depth="3">
          同一格單週、雙週輪流上兩門課,例如週一三、四節單週生科、雙週資科。
          一組放一個班;建好後再新增單週、雙週各一筆配課。
        </n-text>
        <n-text>班級</n-text>
        <n-select
          v-model:value="altClass" data-testid="alt-class" :options="classOptions"
          filterable placeholder="選擇班級"
        />
        <n-button type="primary" data-testid="alt-save" @click="saveAlternate">建立</n-button>
      </n-space>
    </n-modal>

    <!-- 跑班群組 modal -->
    <n-modal v-model:show="groupShow" preset="card" title="新增跑班群組" style="max-width: 460px">
      <n-space vertical>
        <n-text>群組名稱</n-text>
        <n-select
          v-model:value="groupForm.name" data-testid="group-name" filterable tag
          :options="[{ label: '高二多元選修', value: '高二多元選修' }, { label: '綜高學程', value: '綜高學程' }]"
          placeholder="輸入或選擇群組名稱"
        />
        <n-text>成員班級(至少 2 班,須使用同一節次表)</n-text>
        <n-select v-model:value="groupForm.class_ids" data-testid="group-classes" multiple :options="classOptions" filterable placeholder="選擇班級" />
        <n-button type="primary" data-testid="group-save" @click="saveGroup">建立</n-button>
      </n-space>
    </n-modal>
  </n-space>
</template>

<style scoped>
.layout { display: flex; gap: 24px; align-items: flex-start; }
.sidebar { width: 320px; flex-shrink: 0; }
.data-table { border-collapse: collapse; width: 100%; }
.data-table th, .data-table td { border: 1px solid var(--n-border-color, #e0e0e0); padding: 6px 8px; text-align: left; }
.data-table th { background: rgba(128,128,128,0.08); font-weight: 600; }
.data-table.compact th, .data-table.compact td { padding: 4px 6px; font-size: 13px; }
@media (max-width: 900px) { .layout { flex-direction: column; } .sidebar { width: 100%; } }
</style>
