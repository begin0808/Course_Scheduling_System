<script setup lang="ts">
import {
  NButton, NCard, NDivider, NEmpty, NInputNumber, NModal, NPopconfirm,
  NSelect, NSpace, NTag, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import {
  STATUS_LABELS, createPeriodTable, createSemester, deletePeriodTable,
  deleteSemester, listSemesters, listTemplates,
} from '@/api/semesters'
import type { SemesterListItem, Semester, Template } from '@/api/semesters'
import { getSemester } from '@/api/semesters'

const message = useMessage()
const router = useRouter()

const semesters = ref<Semester[]>([])
const templates = ref<Template[]>([])
const loading = ref(false)

// 建立學期表單
const form = ref({ academic_year: 115, term: 1, template_key: null as string | null })
const templateOptions = computed(() => [
  { label: '空白(不帶入節次表)', value: '' },
  ...templates.value.map((t) => ({ label: `${t.name}(${t.minutes_per_period} 分/節)`, value: t.key })),
])
const termOptions = [
  { label: '第 1 學期', value: 1 },
  { label: '第 2 學期', value: 2 },
]

async function reload() {
  loading.value = true
  try {
    const items = await listSemesters()
    // 逐一取回含節次表的完整資料
    semesters.value = await Promise.all(items.map((s: SemesterListItem) => getSemester(s.id)))
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  templates.value = await listTemplates()
  await reload()
})

async function onCreateSemester() {
  try {
    await createSemester({
      academic_year: form.value.academic_year,
      term: form.value.term,
      template_key: form.value.template_key || null,
    })
    message.success('學期已建立')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '建立失敗')
  }
}

async function onDeleteSemester(id: number) {
  await deleteSemester(id)
  message.success('學期已刪除')
  await reload()
}

// 新增節次表 modal
const showAddTable = ref(false)
const addTableTarget = ref<number | null>(null)
const addTableForm = ref({ name: '', template_key: null as string | null, is_default: false })

function openAddTable(semesterId: number) {
  addTableTarget.value = semesterId
  addTableForm.value = { name: '', template_key: null, is_default: false }
  showAddTable.value = true
}

async function onAddTable() {
  if (!addTableForm.value.name) {
    message.warning('請輸入節次表名稱')
    return
  }
  try {
    await createPeriodTable(addTableTarget.value!, {
      name: addTableForm.value.name,
      template_key: addTableForm.value.template_key || null,
      is_default: addTableForm.value.is_default,
    })
    showAddTable.value = false
    message.success('節次表已新增')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '新增失敗')
  }
}

async function onDeleteTable(id: number) {
  await deletePeriodTable(id)
  message.success('節次表已刪除')
  await reload()
}

function editTable(id: number) {
  router.push({ name: 'period-table-editor', params: { id } })
}

const statusType: Record<string, 'default' | 'success' | 'warning'> = {
  preparing: 'warning',
  active: 'success',
  archived: 'default',
}
</script>

<template>
  <n-space vertical size="large">
    <h1 style="margin: 0">學期與節次表</h1>

    <n-card title="建立學期">
      <n-space align="center" :wrap="true">
        <n-text>學年度</n-text>
        <n-input-number v-model:value="form.academic_year" :min="100" :max="200" style="width: 120px" />
        <n-select v-model:value="form.term" :options="termOptions" style="width: 130px" />
        <n-text>學制範本</n-text>
        <n-select
          v-model:value="form.template_key"
          :options="templateOptions"
          placeholder="選擇學制範本"
          style="width: 220px"
        />
        <n-button type="primary" @click="onCreateSemester">建立</n-button>
      </n-space>
    </n-card>

    <n-empty v-if="!loading && semesters.length === 0" description="尚未建立任何學期" />

    <n-card v-for="sem in semesters" :key="sem.id">
      <n-space justify="space-between" align="center">
        <n-space align="center">
          <strong>{{ sem.label }}</strong>
          <n-tag :type="statusType[sem.status]" size="small">{{ STATUS_LABELS[sem.status] }}</n-tag>
        </n-space>
        <n-popconfirm @positive-click="onDeleteSemester(sem.id)">
          <template #trigger>
            <n-button size="tiny" type="error" ghost>刪除學期</n-button>
          </template>
          確定刪除此學期?其節次表將一併移除。
        </n-popconfirm>
      </n-space>

      <n-divider style="margin: 12px 0" />

      <n-space vertical size="small">
        <n-space
          v-for="table in sem.period_tables"
          :key="table.id"
          align="center"
          justify="space-between"
        >
          <n-space align="center">
            <n-text>{{ table.name }}</n-text>
            <n-tag v-if="table.is_default" type="success" size="tiny">預設</n-tag>
            <n-text depth="3">共 {{ table.periods.length }} 格</n-text>
          </n-space>
          <n-space>
            <n-button size="tiny" @click="editTable(table.id)">編輯節次表</n-button>
            <n-popconfirm @positive-click="onDeleteTable(table.id)">
              <template #trigger>
                <n-button size="tiny" type="error" ghost>刪除</n-button>
              </template>
              確定刪除此節次表?
            </n-popconfirm>
          </n-space>
        </n-space>
        <n-button size="small" dashed @click="openAddTable(sem.id)">+ 新增節次表</n-button>
      </n-space>
    </n-card>

    <n-modal
      v-model:show="showAddTable"
      preset="card"
      title="新增節次表"
      style="max-width: 440px"
    >
      <n-space vertical>
        <n-text>名稱</n-text>
        <n-select
          v-model:value="addTableForm.name"
          filterable
          tag
          :options="[
            { label: '高中部節次表', value: '高中部節次表' },
            { label: '國中部節次表', value: '國中部節次表' },
          ]"
          placeholder="輸入或選擇名稱"
        />
        <n-text>帶入學制範本(選填)</n-text>
        <n-select
          v-model:value="addTableForm.template_key"
          :options="templateOptions"
          placeholder="不帶入則建立空表"
        />
        <n-button type="primary" @click="onAddTable">建立</n-button>
      </n-space>
    </n-modal>
  </n-space>
</template>
