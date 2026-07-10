<script setup lang="ts">
import {
  NAlert, NButton, NCard, NCheckbox, NCheckboxGroup, NEmpty, NInputNumber, NPopconfirm, NProgress,
  NSelect, NSpace, NTag, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import { listSemesters } from '@/api/semesters'
import type { SemesterListItem } from '@/api/semesters'
import {
  cancelSolveJob, getSolveJob, listRelaxable, preflight, startAutoSchedule, stopSolveJob,
} from '@/api/solver'
import type {
  PreflightIssue, PreflightReport, RelaxableOption, SolveJob,
} from '@/api/solver'
import { listTimetables } from '@/api/timetables'
import type { TimetableBrief } from '@/api/timetables'

const message = useMessage()
const router = useRouter()

const POLL_MS = 2000

const semesters = ref<SemesterListItem[]>([])
const sid = ref<number | null>(null)
const drafts = ref<TimetableBrief[]>([])
const sourceId = ref<number | null>(null)
const minutes = ref(10) // timeout 預設 10 分鐘

const check = ref<PreflightReport | null>(null)
const job = ref<SolveJob | null>(null)
const blockingIssues = ref<PreflightIssue[]>([])
const starting = ref(false)

const relaxable = ref<RelaxableOption[]>([])
const allowPartial = ref(false)
const relax = ref<string[]>([])

let timer: ReturnType<typeof setInterval> | null = null

const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))
const draftOptions = computed(() =>
  drafts.value.map((t) => ({ label: `${t.name}(${t.entry_count} 格)`, value: t.id })))

const running = computed(() => job.value?.status === 'queued' || job.value?.status === 'running')
const explaining = computed(() => running.value && job.value?.phase === 'explaining')
const conflict = computed(() => job.value?.conflict ?? null)
const conflictCauses = computed(() => conflict.value?.causes ?? [])
const unscheduled = computed(() => job.value?.unscheduled ?? [])

// 進行中顯示「已用掉多少時間預算」;結束後一律填滿——提前結束時 elapsed 可能只有 1%,
// 進度條停在最左邊卻寫著「已完成」會讓人以為排壞了。
const progressPercent = computed(() => {
  if (!job.value) return 0
  if (!running.value) return 100
  return Math.min(100, Math.round((job.value.elapsed / job.value.max_seconds) * 100))
})

const statusTagType = computed(() => {
  if (running.value) return 'info'
  if (job.value?.status === 'finished') return 'success'
  if (job.value?.status === 'cancelled') return 'warning'
  return 'error'
})

const STATUS_LABELS: Record<string, string> = {
  queued: '排隊中', running: '排課中', finished: '已完成', failed: '失敗', cancelled: '已取消',
}
const statusLabel = computed(() =>
  (explaining.value ? '定位無解原因中' : STATUS_LABELS[job.value?.status ?? ''] ?? ''))

const codeName = (code: string) => relaxable.value.find((o) => o.code === code)?.name ?? code

const elapsedText = computed(() => {
  const s = job.value?.elapsed ?? 0
  return s < 1 ? '不到 1 秒' : `${Math.round(s)} 秒`
})
const unplacedPeriods = computed(() => unscheduled.value.reduce((n, u) => n + u.periods, 0))

function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}
onUnmounted(stopPolling)

async function reload() {
  if (!sid.value) return
  const all = await listTimetables(sid.value)
  drafts.value = all.filter((t) => t.status === 'draft')
  sourceId.value = drafts.value[0]?.id ?? null
  check.value = await preflight(sid.value)
}

async function onSemesterChange(id: number) {
  sid.value = id
  job.value = null
  blockingIssues.value = []
  stopPolling()
  await reload()
}

onMounted(async () => {
  ;[semesters.value, relaxable.value] = await Promise.all([listSemesters(), listRelaxable()])
  if (semesters.value.length) await onSemesterChange(semesters.value[0].id)
})

async function poll() {
  if (!job.value) return
  try {
    job.value = await getSolveJob(job.value.job_id)
  } catch {
    stopPolling()
    return
  }
  if (!running.value) {
    stopPolling()
    if (job.value.status === 'finished') message.success(`已產生「${job.value.result_name}」`)
    if (job.value.status === 'cancelled') message.info('已取消排課')
    if (job.value.status === 'failed') message.error(job.value.error ?? '排課失敗')
    await reload()
  }
}

async function onStart() {
  if (!sourceId.value) return
  starting.value = true
  blockingIssues.value = []
  try {
    const { job_id } = await startAutoSchedule(sourceId.value, minutes.value * 60, {
      allowPartial: allowPartial.value,
      relax: allowPartial.value ? relax.value : [],
    })
    job.value = await getSolveJob(job_id)
    stopPolling()
    timer = setInterval(poll, POLL_MS)
  } catch (e) {
    const detail = (e as ApiError).detail as unknown
    if (detail && typeof detail === 'object' && 'issues' in detail) {
      blockingIssues.value = (detail as { issues: PreflightIssue[] }).issues
      message.error('資料未通過排課前置檢查')
    } else {
      message.error((e as ApiError).message || '無法啟動排課')
    }
  } finally {
    starting.value = false
  }
}

/** 照著衝突報告的建議重試:勾好可放寬的項目,直接再排一次。 */
async function onRetryPartial() {
  allowPartial.value = true
  relax.value = conflict.value?.relaxable_codes ?? []
  job.value = null
  await onStart()
}

async function onStop() {
  if (!job.value) return
  await stopSolveJob(job.value.job_id)
  message.info('已要求提前結束,將保留目前最佳解')
}
async function onCancel() {
  if (!job.value) return
  await cancelSolveJob(job.value.job_id)
  message.info('已要求取消')
}

function openResult() {
  router.push({ name: 'versions' })
}
</script>

<template>
  <n-space vertical size="large">
    <n-space align="center">
      <h2 style="margin: 0">自動排課</h2>
      <n-select
        :value="sid" :options="semesterOptions" style="width: 220px"
        placeholder="選擇學期" @update:value="onSemesterChange"
      />
    </n-space>

    <n-empty v-if="!sid" description="請先建立學期" />

    <template v-else>
      <!-- 排課前置檢查 -->
      <n-card v-if="check" title="排課前置檢查" size="small">
        <n-space vertical>
          <n-text depth="3">
            {{ check.class_count }} 班 · {{ check.teacher_count }} 位教師 ·
            {{ check.assignment_count }} 筆配課 · 共 {{ check.total_periods }} 節
          </n-text>
          <n-alert v-if="check.ok && check.warning_count === 0" type="success" :bordered="false">
            資料檢查通過,可以開始排課
          </n-alert>
          <n-alert v-else :type="check.ok ? 'warning' : 'error'" :bordered="false">
            {{ check.error_count }} 項錯誤、{{ check.warning_count }} 項提醒
          </n-alert>
          <div v-for="i in check.issues" :key="i.code + i.subject_id" data-testid="pf-issue">
            <n-tag size="small" :type="i.level === 'error' ? 'error' : 'warning'">
              {{ i.level === 'error' ? '錯誤' : '提醒' }}
            </n-tag>
            <n-text style="margin-left: 8px">{{ i.message }}</n-text>
          </div>
        </n-space>
      </n-card>

      <!-- 啟動 -->
      <n-card title="開始排課" size="small">
        <n-space vertical>
          <n-space align="center">
            <n-text>來源草稿</n-text>
            <n-select
              v-model:value="sourceId" :options="draftOptions" style="width: 260px"
              placeholder="選擇草稿" data-testid="as-source" :disabled="running"
            />
            <n-text>排課時間上限</n-text>
            <n-input-number
              v-model:value="minutes" :min="1" :max="60" style="width: 120px"
              :disabled="running" data-testid="as-minutes"
            >
              <template #suffix>分鐘</template>
            </n-input-number>
            <n-button
              type="primary" :loading="starting" :disabled="!sourceId || running"
              data-testid="as-start" @click="onStart"
            >
              開始排課
            </n-button>
          </n-space>
          <n-text depth="3">
            鎖定的格位會維持原位;其餘已排的課會作為求解起點,結果寫成新草稿,來源草稿不動。
          </n-text>

          <n-checkbox v-model:checked="allowPartial" :disabled="running" data-testid="as-partial">
            允許部分排課(排不下的課列成清單,不要整個失敗)
          </n-checkbox>
          <n-space v-if="allowPartial" align="center" style="padding-left: 24px">
            <n-text depth="3">可放寬:</n-text>
            <n-checkbox-group v-model:value="relax" :disabled="running">
              <n-checkbox
                v-for="o in relaxable" :key="o.code" :value="o.code"
                :label="o.name" :data-testid="`as-relax-${o.code}`"
              />
            </n-checkbox-group>
          </n-space>
          <n-text v-if="allowPartial" depth="3" style="padding-left: 24px">
            班級、教師、場地的「同時段只能有一門課」不可放寬——那是物理限制,不是政策。
          </n-text>

          <n-alert v-if="blockingIssues.length" type="error" title="請先修正這些問題">
            <div v-for="i in blockingIssues" :key="i.code + i.subject_id" data-testid="as-blocking">
              {{ i.message }}
            </div>
          </n-alert>
        </n-space>
      </n-card>

      <!-- 進度 -->
      <n-card v-if="job" title="排課進度" size="small" data-testid="as-job">
        <n-space vertical>
          <n-space align="center">
            <n-tag :type="statusTagType" data-testid="as-status">{{ statusLabel }}</n-tag>
            <n-text>已耗時 {{ elapsedText }} / 上限 {{ job.max_seconds }} 秒</n-text>
            <n-text v-if="running || job.solutions" data-testid="as-solutions">
              已找到 {{ job.solutions }} 個解
            </n-text>
            <!-- 部分排課的目標值被「未排入」的高額懲罰灌爆(一節 = 10000),
                 拿給人看只會以為排壞了;真正該看的是未排幾節。 -->
            <n-text v-if="job.partial && !running">未排 {{ unplacedPeriods }} 節</n-text>
            <n-text v-else-if="job.objective !== null">目前目標值 {{ Math.round(job.objective) }}</n-text>
          </n-space>

          <n-progress
            type="line" :percentage="progressPercent"
            :status="job.status === 'failed' ? 'error'
              : job.status === 'cancelled' ? 'warning'
                : running ? 'default' : 'success'"
            :processing="running"
          />

          <n-space v-if="running && !explaining">
            <n-button
              type="primary" ghost :disabled="job.solutions === 0"
              data-testid="as-stop" @click="onStop"
            >
              提前結束(取目前最佳解)
            </n-button>
            <n-popconfirm @positive-click="onCancel">
              <template #trigger>
                <n-button type="error" ghost data-testid="as-cancel">取消排課</n-button>
              </template>
              取消後不會產生結果草稿,確定?
            </n-popconfirm>
          </n-space>

          <n-text v-if="explaining" depth="3" data-testid="as-explaining">
            排不出來。正在逐項試解,找出是哪幾件事湊在一起造成的……
          </n-text>

          <!-- 定位不出具體原因時(例如硬約束其實可解、只是軟約束最佳化太慢),仍要給一句人話 -->
          <n-alert
            v-if="job.status === 'failed' && !conflictCauses.length"
            type="error" data-testid="as-error"
          >
            {{ job.error }}
          </n-alert>

          <!-- 無解衝突定位:不只說「排不出來」,說是誰、差幾節、鬆開哪一個就好 -->
          <n-alert
            v-if="conflict && conflictCauses.length" type="error"
            :title="conflict.headline" data-testid="as-conflict"
          >
            <n-space vertical size="small">
              <div v-for="(c, k) in conflictCauses" :key="k" data-testid="as-cause">
                <n-tag size="small" :bordered="false" :type="c.relaxable ? 'warning' : 'error'">
                  {{ c.scope_name }}
                </n-tag>
                <n-text style="margin-left: 8px">{{ c.message }}</n-text>
                <div style="padding-left: 8px">
                  <n-text depth="3">建議:{{ c.suggestion }}</n-text>
                </div>
              </div>
              <n-text v-if="!conflict.complete" depth="3">
                (時間有限,可能還有其他原因未列出)
              </n-text>
              <n-button
                v-if="conflict.relaxable_codes.length" type="primary" ghost size="small"
                data-testid="as-retry-partial" @click="onRetryPartial"
              >
                改用部分排課(放寬{{ conflict.relaxable_codes.map(codeName).join('、') }})
              </n-button>
            </n-space>
          </n-alert>

          <n-alert v-if="job.status === 'finished'" type="success" data-testid="as-done">
            已產生新草稿「{{ job.result_name }}」
            <n-button text type="primary" style="margin-left: 8px" @click="openResult">
              前往版本與發布
            </n-button>
          </n-alert>

          <!-- 未排清單:部分排課的另一半交付物 -->
          <n-alert
            v-if="unscheduled.length" type="warning" title="以下課務未能排入,請人工處理"
            data-testid="as-unscheduled"
          >
            <table class="data-table">
              <thead>
                <tr><th>科目</th><th>班級</th><th>未排節數</th></tr>
              </thead>
              <tbody>
                <tr v-for="u in unscheduled" :key="u.assignment_id">
                  <td>{{ u.subject_name }}</td>
                  <td>{{ u.class_names.join('、') }}</td>
                  <td>{{ u.periods }} 節</td>
                </tr>
              </tbody>
            </table>
          </n-alert>

          <!-- 軟約束達成度 -->
          <table v-if="job.report" class="data-table" data-testid="as-report">
            <thead>
              <tr><th>軟約束</th><th>權重</th><th>達成</th><th>未達成明細</th></tr>
            </thead>
            <tbody>
              <tr v-for="i in job.report.items" :key="i.code">
                <td>{{ i.code }} {{ i.name }}</td>
                <td>{{ i.weight === 0 ? '關閉' : i.weight }}</td>
                <td>
                  {{ i.satisfied }} / {{ i.opportunities }}
                  <n-text :depth="3">({{ Math.round(i.rate * 100) }}%)</n-text>
                </td>
                <td>
                  <n-text v-if="!i.details.length" depth="3">—</n-text>
                  <div v-for="(d, k) in i.details.slice(0, 3)" v-else :key="k">{{ d }}</div>
                  <n-text v-if="i.details.length > 3" depth="3">
                    …等 {{ i.violations }} 項
                  </n-text>
                </td>
              </tr>
            </tbody>
          </table>
        </n-space>
      </n-card>
    </template>
  </n-space>
</template>

<style scoped>
.data-table { border-collapse: collapse; width: 100%; }
.data-table th, .data-table td {
  border: 1px solid var(--n-border-color, #e0e0e0); padding: 6px 10px; text-align: left;
  vertical-align: top;
}
.data-table th { background: rgba(128, 128, 128, 0.08); font-weight: 600; }
</style>
