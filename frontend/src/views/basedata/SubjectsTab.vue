<script setup lang="ts">
import {
  NButton, NCheckbox, NInput, NInputNumber, NModal, NPopconfirm, NSelect, NSpace, NTag, NText,
  useMessage,
} from 'naive-ui'
import { onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  ROOM_TYPE_LABELS, createSubject, deleteSubject, listSubjects, updateSubject,
} from '@/api/basedata'
import type { RoomType, Subject } from '@/api/basedata'

const props = defineProps<{ semesterId: number }>()
const message = useMessage()

const items = ref<Subject[]>([])
const search = ref('')

const roomTypeOptions = (Object.keys(ROOM_TYPE_LABELS) as RoomType[]).map((t) => ({
  label: ROOM_TYPE_LABELS[t], value: t,
}))

async function reload() {
  items.value = await listSubjects(props.semesterId, search.value || undefined)
}
onMounted(reload)

const show = ref(false)
const editingId = ref<number | null>(null)
const form = ref<{
  name: string
  domain: string
  required_room_type: RoomType | null
  default_block_size: number
  is_major: boolean
}>({ name: '', domain: '', required_room_type: null, default_block_size: 1, is_major: false })

function openCreate() {
  editingId.value = null
  form.value = { name: '', domain: '', required_room_type: null, default_block_size: 1, is_major: false }
  show.value = true
}
function openEdit(s: Subject) {
  editingId.value = s.id
  form.value = {
    name: s.name, domain: s.domain ?? '',
    required_room_type: s.required_room_type, default_block_size: s.default_block_size,
    is_major: s.is_major,
  }
  show.value = true
}

async function save() {
  if (!form.value.name) {
    message.warning('請輸入科目名稱')
    return
  }
  const body = {
    name: form.value.name,
    domain: form.value.domain || null,
    required_room_type: form.value.required_room_type,
    default_block_size: form.value.default_block_size,
    is_major: form.value.is_major,
  }
  try {
    if (editingId.value) await updateSubject(editingId.value, body)
    else await createSubject(props.semesterId, body)
    show.value = false
    message.success('已儲存')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '儲存失敗')
  }
}

async function remove(s: Subject) {
  try {
    await deleteSubject(s.id)
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
      <n-input v-model:value="search" placeholder="搜尋科目名稱" clearable style="width: 200px" @input="reload" />
      <n-button type="primary" @click="openCreate">新增科目</n-button>
    </n-space>

    <table class="data-table">
      <thead>
        <tr><th>名稱</th><th>領域/群別</th><th>需要場地</th><th>預設連堂</th><th>主科</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="s in items" :key="s.id">
          <td>{{ s.name }}</td>
          <td>{{ s.domain || '—' }}</td>
          <td>{{ s.required_room_type ? ROOM_TYPE_LABELS[s.required_room_type] : '不限' }}</td>
          <td>{{ s.default_block_size > 1 ? `${s.default_block_size} 連堂` : '一般' }}</td>
          <td>
            <n-tag v-if="s.is_major" size="small" type="info" :data-testid="`sub-major-${s.name}`">主科</n-tag>
            <span v-else>—</span>
          </td>
          <td>
            <n-space>
              <n-button size="tiny" @click="openEdit(s)">編輯</n-button>
              <n-popconfirm @positive-click="remove(s)">
                <template #trigger><n-button size="tiny" type="error" ghost>刪除</n-button></template>
                確定刪除此科目?
              </n-popconfirm>
            </n-space>
          </td>
        </tr>
        <tr v-if="items.length === 0"><td colspan="6"><n-text depth="3">尚無科目</n-text></td></tr>
      </tbody>
    </table>

    <n-modal v-model:show="show" preset="card" :title="editingId ? '編輯科目' : '新增科目'" style="max-width: 420px">
      <n-space vertical>
        <n-text>名稱</n-text>
        <n-input v-model:value="form.name" data-testid="sub-name" placeholder="如:數學" />
        <n-text>領域/群別(選填)</n-text>
        <n-input v-model:value="form.domain" placeholder="如:數學領域" />
        <n-text>需要場地類型(選填)</n-text>
        <n-select v-model:value="form.required_room_type" :options="roomTypeOptions" clearable placeholder="不限" />
        <n-text>預設連堂長度</n-text>
        <n-input-number v-model:value="form.default_block_size" :min="1" :max="8" />
        <n-checkbox v-model:checked="form.is_major" data-testid="sub-is-major">
          主科(自動排課會盡量排在上午)
        </n-checkbox>
        <n-button type="primary" data-testid="sub-save" @click="save">儲存</n-button>
      </n-space>
    </n-modal>
  </n-space>
</template>

<style scoped>
.data-table { border-collapse: collapse; width: 100%; }
.data-table th, .data-table td { border: 1px solid var(--n-border-color, #e0e0e0); padding: 8px 10px; text-align: left; }
.data-table th { background: rgba(128,128,128,0.08); font-weight: 600; }
</style>
