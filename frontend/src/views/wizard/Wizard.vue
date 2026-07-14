<script setup lang="ts">
import {
  NButton, NCard, NGrid, NGridItem, NInputNumber, NResult, NSelect, NSpace, NStatistic,
  NStep, NSteps, NText, useMessage,
} from 'naive-ui'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import { createSemester, getSemester, listTemplates } from '@/api/semesters'
import { PRIMARY } from '@/theme'
import type { Semester, Template } from '@/api/semesters'
import { getSemesterSummary } from '@/api/wizard'
import type { SemesterSummary } from '@/api/wizard'
import { useWizardStore } from '@/stores/wizard'
import ImportTab from '@/views/basedata/ImportTab.vue'

const router = useRouter()
const message = useMessage()
const wizard = useWizardStore()

const step = ref(0)
const templates = ref<Template[]>([])
const templateKey = ref<string | null>(null)
const year = ref(115)
const term = ref(1)
const semesterId = ref<number | null>(null)
const semester = ref<Semester | null>(null)
const summary = ref<SemesterSummary | null>(null)
const busy = ref(false)

const termOptions = [
  { label: '第 1 學期', value: 1 },
  { label: '第 2 學期', value: 2 },
]

onMounted(async () => {
  templates.value = await listTemplates()
  if (!wizard.loaded) await wizard.fetch()
  if (wizard.state) {
    step.value = wizard.state.current_step
    semesterId.value = wizard.state.semester_id
    if (semesterId.value) await loadSemester(semesterId.value)
  }
})

async function loadSemester(id: number) {
  semester.value = await getSemester(id)
  summary.value = await getSemesterSummary(id)
}

async function persistStep() {
  await wizard.patch({ current_step: step.value })
}

async function goNext() {
  // 第 2 步(學年學期)→ 建立學期
  if (step.value === 1 && !semesterId.value) {
    if (!templateKey.value) {
      message.warning('請先於上一步選擇學制範本')
      return
    }
    busy.value = true
    try {
      const sem = await createSemester({
        academic_year: year.value, term: term.value, template_key: templateKey.value,
      })
      semesterId.value = sem.id
      await wizard.patch({ semester_id: sem.id })
      await loadSemester(sem.id)
    } catch (e) {
      message.error((e as ApiError).detail || '建立學期失敗')
      busy.value = false
      return
    }
    busy.value = false
  }
  step.value = Math.min(step.value + 1, 4)
  if (step.value === 4 && semesterId.value) await loadSemester(semesterId.value)
  await persistStep()
}

async function goPrev() {
  step.value = Math.max(step.value - 1, 0)
  await persistStep()
}

async function finish() {
  await wizard.patch({ completed: true })
  message.success('初始設定完成')
  router.push({ name: 'basedata' })
}

async function skip() {
  await wizard.patch({ completed: true })
  router.push({ name: 'dashboard' })
}

function openPeriodEditor() {
  const table = semester.value?.period_tables.find((t) => t.is_default)
  if (table) router.push({ name: 'period-table-editor', params: { id: table.id } })
}
</script>

<template>
  <div style="max-width: 860px; margin: 24px auto; padding: 0 16px">
    <n-space vertical size="large">
      <n-space justify="space-between" align="center">
        <h1 style="margin: 0">設定精靈</h1>
        <n-button quaternary @click="skip">略過,稍後再設定</n-button>
      </n-space>

      <n-steps :current="step + 1" size="small">
        <n-step title="學制範本" />
        <n-step title="學年學期" />
        <n-step title="節次表" />
        <n-step title="匯入資料" />
        <n-step title="完成" />
      </n-steps>

      <n-card>
        <!-- Step 0:學制範本 -->
        <template v-if="step === 0">
          <n-text>請選擇貴校的學制,系統將自動帶入對應的節次表與科目清單。</n-text>
          <n-grid :cols="2" :x-gap="12" :y-gap="12" style="margin-top: 16px">
            <n-grid-item v-for="t in templates" :key="t.key">
              <n-card
                hoverable
                :data-testid="`tpl-${t.key}`"
                :style="{
                  cursor: 'pointer',
                  borderColor: templateKey === t.key ? 'var(--n-color-target)' : undefined,
                  outline: templateKey === t.key ? `2px solid ${PRIMARY}` : 'none',
                }"
                @click="templateKey = t.key"
              >
                <strong>{{ t.name }}</strong>
                <div><n-text depth="3">{{ t.minutes_per_period }} 分/節 · {{ t.subject_count }} 科</n-text></div>
              </n-card>
            </n-grid-item>
          </n-grid>
        </template>

        <!-- Step 1:學年學期 -->
        <template v-else-if="step === 1">
          <n-space vertical>
            <n-text>設定本學期的學年度與學期別。</n-text>
            <n-space align="center">
              <n-text>學年度</n-text>
              <n-input-number v-model:value="year" data-testid="wizard-year" :min="100" :max="200" :disabled="!!semesterId" style="width: 120px" />
              <n-select v-model:value="term" :options="termOptions" :disabled="!!semesterId" style="width: 140px" />
            </n-space>
            <n-text v-if="semesterId" type="success">已建立:{{ semester?.label }}</n-text>
          </n-space>
        </template>

        <!-- Step 2:節次表 -->
        <template v-else-if="step === 2">
          <n-space vertical>
            <n-text>已依範本帶入預設節次表。可先確認,若需調整(如週三下午不排課)可開啟編輯器。</n-text>
            <div v-if="semester">
              <n-text strong>{{ semester.period_tables[0]?.name }}</n-text>
              <n-text depth="3">
                (共 {{ semester.period_tables[0]?.periods.length ?? 0 }} 格,每週
                {{ semester.period_tables[0]?.num_weekdays ?? 5 }} 天)
              </n-text>
            </div>
            <n-button @click="openPeriodEditor">開啟節次表編輯器</n-button>
            <n-text depth="3">提示:離開編輯器後回到本精靈會自動回到此步驟。</n-text>
          </n-space>
        </template>

        <!-- Step 3:匯入資料 -->
        <template v-else-if="step === 3">
          <n-space vertical>
            <n-text>下載範本填寫後上傳,批次建立教師、班級與科目(可略過,稍後於基礎資料補建)。</n-text>
            <ImportTab v-if="semesterId" :semester-id="semesterId" />
          </n-space>
        </template>

        <!-- Step 4:完成 -->
        <template v-else>
          <n-result status="success" title="初始設定即將完成" description="以下是目前已建立的資料摘要">
            <template #footer>
              <n-space justify="center" size="large">
                <n-statistic label="科目" :value="summary?.subjects ?? 0" />
                <n-statistic label="教師" :value="summary?.teachers ?? 0" />
                <n-statistic label="班級" :value="summary?.classes ?? 0" />
                <n-statistic label="場地" :value="summary?.rooms ?? 0" />
              </n-space>
            </template>
          </n-result>
        </template>
      </n-card>

      <n-space justify="space-between">
        <n-button data-testid="wizard-prev" :disabled="step === 0" @click="goPrev">上一步</n-button>
        <n-button v-if="step < 4" data-testid="wizard-next" type="primary" :loading="busy" @click="goNext">
          下一步
        </n-button>
        <n-button v-else data-testid="wizard-finish" type="primary" @click="finish">
          完成,前往基礎資料
        </n-button>
      </n-space>
    </n-space>
  </div>
</template>
