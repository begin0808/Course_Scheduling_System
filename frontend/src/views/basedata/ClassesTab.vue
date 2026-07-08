<script setup lang="ts">
import {
  NButton, NInput, NInputNumber, NModal, NPopconfirm, NSelect, NSpace, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  TRACK_LABELS, createClassUnit, deleteClassUnit, listClassUnits, listTeachers, updateClassUnit,
} from '@/api/basedata'
import type { ClassTrack, ClassUnit, Teacher } from '@/api/basedata'

const props = defineProps<{ semesterId: number }>()
const message = useMessage()

const items = ref<ClassUnit[]>([])
const teachers = ref<Teacher[]>([])
const search = ref('')

const trackOptions = (Object.keys(TRACK_LABELS) as ClassTrack[]).map((t) => ({
  label: TRACK_LABELS[t], value: t,
}))
const teacherOptions = computed(() => teachers.value.map((t) => ({ label: t.name, value: t.id })))

async function reload() {
  items.value = await listClassUnits(props.semesterId, search.value || undefined)
}
onMounted(async () => {
  teachers.value = await listTeachers(props.semesterId)
  await reload()
})

const show = ref(false)
const editingId = ref<number | null>(null)
const form = ref<{
  grade: number; name: string; track: ClassTrack; department: string
  student_count: number | null; homeroom_teacher_id: number | null
}>({ grade: 1, name: '', track: 'elementary', department: '', student_count: null, homeroom_teacher_id: null })

// 技高才顯示群科欄位
const showDepartment = computed(() => form.value.track === 'vocational')

function openCreate() {
  editingId.value = null
  form.value = { grade: 1, name: '', track: 'elementary', department: '', student_count: null, homeroom_teacher_id: null }
  show.value = true
}
function openEdit(c: ClassUnit) {
  editingId.value = c.id
  form.value = {
    grade: c.grade, name: c.name, track: c.track, department: c.department ?? '',
    student_count: c.student_count, homeroom_teacher_id: c.homeroom_teacher_id,
  }
  show.value = true
}

async function save() {
  if (!form.value.name) {
    message.warning('請輸入班名')
    return
  }
  const body = {
    grade: form.value.grade,
    name: form.value.name,
    track: form.value.track,
    department: showDepartment.value ? form.value.department || null : null,
    student_count: form.value.student_count,
    homeroom_teacher_id: form.value.homeroom_teacher_id,
  }
  try {
    if (editingId.value) await updateClassUnit(editingId.value, body)
    else await createClassUnit(props.semesterId, body)
    show.value = false
    message.success('已儲存')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '儲存失敗')
  }
}

async function remove(c: ClassUnit) {
  try {
    await deleteClassUnit(c.id)
    message.success('已刪除')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '刪除失敗')
  }
}
</script>

<template>
  <n-space vertical>
    <n-space>
      <n-input v-model:value="search" placeholder="搜尋班名" clearable style="width: 200px" @input="reload" />
      <n-button type="primary" @click="openCreate">新增班級</n-button>
    </n-space>

    <table class="data-table">
      <thead>
        <tr><th>年級</th><th>班名</th><th>學制</th><th>群科</th><th>導師</th><th>人數</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="c in items" :key="c.id">
          <td>{{ c.grade }}</td>
          <td>{{ c.name }}</td>
          <td>{{ TRACK_LABELS[c.track] }}</td>
          <td>{{ c.department || '—' }}</td>
          <td>{{ c.homeroom_teacher?.name || '—' }}</td>
          <td>{{ c.student_count ?? '—' }}</td>
          <td>
            <n-space>
              <n-button size="tiny" @click="openEdit(c)">編輯</n-button>
              <n-popconfirm @positive-click="remove(c)">
                <template #trigger><n-button size="tiny" type="error" ghost>刪除</n-button></template>
                確定刪除此班級?
              </n-popconfirm>
            </n-space>
          </td>
        </tr>
        <tr v-if="items.length === 0"><td colspan="7"><n-text depth="3">尚無班級</n-text></td></tr>
      </tbody>
    </table>

    <n-modal v-model:show="show" preset="card" :title="editingId ? '編輯班級' : '新增班級'" style="max-width: 440px">
      <n-space vertical>
        <n-space>
          <n-space vertical>
            <n-text>年級</n-text>
            <n-input-number v-model:value="form.grade" :min="1" :max="12" style="width: 120px" />
          </n-space>
          <n-space vertical style="flex: 1">
            <n-text>班名</n-text>
            <n-input v-model:value="form.name" placeholder="如:忠、甲、301" />
          </n-space>
        </n-space>
        <n-text>學制</n-text>
        <n-select v-model:value="form.track" :options="trackOptions" />
        <template v-if="showDepartment">
          <n-text>群科(技高)</n-text>
          <n-input v-model:value="form.department" placeholder="如:機械科" />
        </template>
        <n-text>導師(選填)</n-text>
        <n-select
          v-model:value="form.homeroom_teacher_id"
          :options="teacherOptions"
          clearable
          placeholder="（未指定）"
        />
        <n-text>人數(選填)</n-text>
        <n-input-number v-model:value="form.student_count" :min="0" />
        <n-button type="primary" @click="save">儲存</n-button>
      </n-space>
    </n-modal>
  </n-space>
</template>

<style scoped>
.data-table { border-collapse: collapse; width: 100%; }
.data-table th, .data-table td { border: 1px solid var(--n-border-color, #e0e0e0); padding: 8px 10px; text-align: left; }
.data-table th { background: rgba(128,128,128,0.08); font-weight: 600; }
</style>
