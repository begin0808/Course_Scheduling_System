<script setup lang="ts">
// 停課日(v1.4.19,組長回報:「停課日在哪邊可以設定?」)
import {
  NAlert, NButton, NCheckbox, NCheckboxGroup, NDatePicker, NEmpty, NInput, NInputNumber, NModal,
  NPopconfirm, NRadio, NRadioGroup, NSelect, NSpace, NTag, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import { listClassUnits } from '@/api/basedata'
import type { ClassUnit } from '@/api/basedata'
import { listSemesters, defaultSemester } from '@/api/semesters'
import type { SemesterPick } from '@/api/semesters'
import {
  createSuspension, deleteSuspension, listSuspensions, updateSuspension,
} from '@/api/suspensions'
import type { Suspension, SuspensionIn } from '@/api/suspensions'
import { dateRangeText, gradeGroups } from './suspensionText'

const message = useMessage()
const semesters = ref<SemesterPick[]>([])
const sid = ref<number | null>(null)
const items = ref<Suspension[]>([])
const classes = ref<ClassUnit[]>([])

const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))
const groups = computed(() => gradeGroups(classes.value))

function toISODate(ts: number): string {
  const d = new Date(ts)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function parseISODate(iso: string): number {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).getTime()
}
function todayTs(): number {
  const d = new Date()
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

async function reload() {
  if (sid.value === null) return
  items.value = await listSuspensions(sid.value)
}

async function onSemesterChange(id: number) {
  sid.value = id
  ;[classes.value] = await Promise.all([listClassUnits(id), reload()])
}

onMounted(async () => {
  semesters.value = await listSemesters()
  if (semesters.value.length) await onSemesterChange(defaultSemester(semesters.value).id)
})

// ── 新增/編輯 ──
const show = ref(false)
const editingId = ref<number | null>(null)
const range = ref<[number, number]>([todayTs(), todayTs()])
const target = ref<'school' | 'classes'>('school')
const classIds = ref<number[]>([])
const span = ref<'all' | 'periods'>('all')
const fromOrdinal = ref<number | null>(null)
const toOrdinal = ref<number | null>(null)
const reason = ref('')

const conflicts = ref<string[]>([])
const showConflicts = ref(false)

function openCreate() {
  editingId.value = null
  range.value = [todayTs(), todayTs()]
  target.value = 'school'
  classIds.value = []
  span.value = 'all'
  fromOrdinal.value = null
  toOrdinal.value = null
  reason.value = ''
  show.value = true
}

function openEdit(s: Suspension) {
  editingId.value = s.id
  range.value = [parseISODate(s.start_date), parseISODate(s.end_date)]
  target.value = s.whole_school ? 'school' : 'classes'
  classIds.value = [...s.class_ids]
  span.value = s.all_day ? 'all' : 'periods'
  fromOrdinal.value = s.from_ordinal
  toOrdinal.value = s.to_ordinal
  reason.value = s.reason
  show.value = true
}

function gradeState(ids: number[]): 'all' | 'some' | 'none' {
  const picked = ids.filter((id) => classIds.value.includes(id)).length
  if (picked === 0) return 'none'
  return picked === ids.length ? 'all' : 'some'
}

/** 勾年級 = 勾整個年級的班;再按一次取消 */
function toggleGrade(ids: number[]) {
  if (gradeState(ids) === 'all') {
    classIds.value = classIds.value.filter((id) => !ids.includes(id))
  } else {
    classIds.value = [...new Set([...classIds.value, ...ids])]
  }
}

async function save() {
  if (sid.value === null) return
  if (target.value === 'classes' && !classIds.value.length) {
    message.warning('請勾選停課的年級或班級')
    return
  }
  if (span.value === 'periods' && !fromOrdinal.value) {
    message.warning('請填從第幾節開始停課')
    return
  }
  const body: SuspensionIn = {
    start_date: toISODate(range.value[0]),
    end_date: toISODate(range.value[1]),
    whole_school: target.value === 'school',
    class_ids: target.value === 'school' ? [] : classIds.value,
    all_day: span.value === 'all',
    from_ordinal: span.value === 'all' ? null : fromOrdinal.value,
    to_ordinal: span.value === 'all' ? null : (toOrdinal.value ?? fromOrdinal.value),
    reason: reason.value.trim(),
  }
  try {
    const saved = editingId.value
      ? await updateSuspension(editingId.value, body)
      : await createSuspension(sid.value, body)
    show.value = false
    message.success('已儲存')
    await reload()
    if (saved.conflicts.length) {
      conflicts.value = saved.conflicts
      showConflicts.value = true
    }
  } catch (e) {
    message.error((e as ApiError).detail || '儲存失敗')
  }
}

async function remove(s: Suspension) {
  try {
    await deleteSuspension(s.id)
    message.success('已刪除')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '刪除失敗')
  }
}
</script>

<template>
  <!-- 視窗放在 n-space 外面(見調代課處理頁的說明) -->
  <div>
    <n-space vertical size="large">
      <n-space align="center">
        <h2 style="margin: 0">停課日</h2>
        <n-select
          :value="sid" :options="semesterOptions" style="width: 220px"
          placeholder="選擇學期" @update:value="onSemesterChange"
        />
        <n-button v-if="sid" type="primary" data-testid="susp-new" @click="openCreate">新增停課</n-button>
      </n-space>

      <n-alert type="info" :show-icon="false">
        校慶補假、颱風假、段考下午、戶外教學、探索活動……設定哪幾天、哪些班、哪幾節不上課。
        停課的課:請假時不必找人代課、整天停課的班不必代導、不能拿來調課補課;
        巡堂表、週課表、教師週總表會標「停課」。
      </n-alert>

      <n-empty v-if="!sid" description="請先建立學期" />
      <table v-else class="data-table" data-testid="susp-table">
        <thead>
          <tr><th>日期</th><th>對象</th><th>節次</th><th>說明</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="s in items" :key="s.id" data-testid="susp-row">
            <td>{{ dateRangeText(s.start_date, s.end_date) }}</td>
            <td>{{ s.target_text }}</td>
            <td>{{ s.period_text }}</td>
            <td>{{ s.reason || '—' }}</td>
            <td>
              <n-space>
                <n-button size="tiny" @click="openEdit(s)">編輯</n-button>
                <n-popconfirm @positive-click="remove(s)">
                  <template #trigger><n-button size="tiny" type="error" ghost>刪除</n-button></template>
                  確定刪除這筆停課?
                </n-popconfirm>
              </n-space>
            </td>
          </tr>
          <tr v-if="items.length === 0"><td colspan="5"><n-text depth="3">尚未設定停課日</n-text></td></tr>
        </tbody>
      </table>
    </n-space>

    <n-modal
      v-model:show="show" preset="card" :title="editingId ? '編輯停課' : '新增停課'"
      style="max-width: 560px" data-testid="susp-modal"
    >
      <n-space vertical>
        <n-text strong>日期</n-text>
        <n-date-picker v-model:value="range" type="daterange" data-testid="susp-range" />

        <n-text strong>對象</n-text>
        <n-radio-group v-model:value="target">
          <n-radio value="school" data-testid="susp-school">全校</n-radio>
          <n-radio value="classes" data-testid="susp-classes">指定年級或班級</n-radio>
        </n-radio-group>
        <div v-if="target === 'classes'" class="grades">
          <div v-for="g in groups" :key="g.key" class="grade-row">
            <n-checkbox
              :checked="gradeState(g.classes.map((c) => c.id)) === 'all'"
              :indeterminate="gradeState(g.classes.map((c) => c.id)) === 'some'"
              :data-testid="`susp-grade-${g.key}`"
              @update:checked="toggleGrade(g.classes.map((c) => c.id))"
            >
              <strong>{{ g.label }}</strong>
            </n-checkbox>
            <n-checkbox-group v-model:value="classIds">
              <n-space size="small">
                <n-checkbox v-for="c in g.classes" :key="c.id" :value="c.id" :label="c.name" />
              </n-space>
            </n-checkbox-group>
          </div>
          <n-text v-if="!groups.length" depth="3">這個學期還沒有班級</n-text>
        </div>

        <n-text strong>節次</n-text>
        <n-radio-group v-model:value="span">
          <n-radio value="all" data-testid="susp-all-day">整天</n-radio>
          <n-radio value="periods" data-testid="susp-periods">指定節次</n-radio>
        </n-radio-group>
        <n-space v-if="span === 'periods'" align="center">
          <span>第</span>
          <n-input-number v-model:value="fromOrdinal" :min="1" :max="20" style="width: 90px" data-testid="susp-from" />
          <span>節到第</span>
          <n-input-number v-model:value="toOrdinal" :min="1" :max="20" style="width: 90px" placeholder="同一節" data-testid="susp-to" />
          <span>節</span>
        </n-space>
        <n-text v-if="span === 'periods'" depth="3">
          第幾節只算一般上課節次,不含早自習、午休;國中小兩部作息不同時,各依自己的節次表。
        </n-text>

        <n-text strong>說明</n-text>
        <n-input v-model:value="reason" maxlength="64" placeholder="例如:校慶補假、探索活動、颱風假" data-testid="susp-reason" />

        <n-button type="primary" data-testid="susp-save" @click="save">儲存</n-button>
      </n-space>
    </n-modal>

    <n-modal
      v-model:show="showConflicts" preset="card" title="停課時段裡已經有安排" style="max-width: 560px"
      data-testid="susp-conflicts"
    >
      <n-space vertical>
        <n-text>
          以下調代課在停課之前就安排好了,系統沒有自動更改(可能已經通知老師)。
          請到「調代課處理」撤回,或把那一節改成「不處理(當天停課)」。
        </n-text>
        <n-space vertical size="small">
          <n-tag v-for="c in conflicts" :key="c" type="warning">{{ c }}</n-tag>
        </n-space>
        <n-button @click="showConflicts = false">知道了</n-button>
      </n-space>
    </n-modal>
  </div>
</template>

<style scoped>
.data-table { border-collapse: collapse; width: 100%; }
.data-table th, .data-table td { border: 1px solid var(--n-border-color, #e0e0e0); padding: 8px 10px; text-align: left; }
.data-table th { background: rgba(128,128,128,0.08); font-weight: 600; }
.grades { display: flex; flex-direction: column; gap: 8px; padding-left: 8px; }
.grade-row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
</style>
