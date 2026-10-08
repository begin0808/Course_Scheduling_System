<script setup lang="ts">
import {
  NAlert, NButton, NCard, NEmpty, NInput, NModal, NPopconfirm, NSelect, NSpace, NTag, NText,
  useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import { listSemesters } from '@/api/semesters'
import type { SemesterListItem } from '@/api/semesters'
import {
  STATUS_LABELS, checkTimetable, createTimetable, deleteTimetable, duplicateTimetable,
  listTimetables, publishIssues, publishReport, publishTimetable, renameTimetable,
} from '@/api/timetables'
import type { CheckIssue, Completeness, TimetableBrief } from '@/api/timetables'

const message = useMessage()

const semesters = ref<SemesterListItem[]>([])
const sid = ref<number | null>(null)
const items = ref<TimetableBrief[]>([])
const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))

const statusType: Record<string, 'default' | 'success' | 'warning'> = {
  draft: 'warning', published: 'success', archived: 'default',
}

async function reload() {
  if (sid.value) items.value = await listTimetables(sid.value)
}
async function onSemesterChange(id: number) {
  sid.value = id
  await reload()
}
onMounted(async () => {
  semesters.value = await listSemesters()
  if (semesters.value.length) await onSemesterChange(semesters.value[0].id)
})

async function onCreate() {
  if (!sid.value) return
  await createTimetable(sid.value, `草稿${String.fromCharCode(65 + items.value.length)}`)
  message.success('已建立草稿')
  await reload()
}
async function onDuplicate(t: TimetableBrief) {
  await duplicateTimetable(t.id, `${t.name} 複本`)
  message.success('已複製為新草稿')
  await reload()
}
async function onDelete(id: number) {
  await deleteTimetable(id)
  message.success('已刪除')
  await reload()
}

// 改名
const renameShow = ref(false)
const renameTarget = ref<TimetableBrief | null>(null)
const renameValue = ref('')
function openRename(t: TimetableBrief) {
  renameTarget.value = t
  renameValue.value = t.name
  renameShow.value = true
}
async function onRename() {
  if (!renameTarget.value || !renameValue.value) return
  await renameTimetable(renameTarget.value.id, renameValue.value)
  renameShow.value = false
  message.success('已改名')
  await reload()
}

// 發布(未排完或有衝突 → 警告清單 → 可強制發布);「檢查課表」共用同一個視窗,只是沒有發布鈕
const warnShow = ref(false)
const warnMode = ref<'publish' | 'check'>('publish')
const report = ref<Completeness | null>(null)
const issues = ref<CheckIssue[]>([])
const publishTarget = ref<TimetableBrief | null>(null)
const incomplete = computed(() => !!report.value && !report.value.complete)
const warnTitle = computed(() => {
  const name = publishTarget.value ? `「${publishTarget.value.name}」` : ''
  if (issues.value.length && incomplete.value) return `${name}課表有衝突,且尚有課務未排完`
  return issues.value.length ? `${name}課表有衝突` : `${name}尚有課務未排完`
})
/** 違規依類別(教師衝堂、教師不可排時段…)分組,後端已排好順序。 */
const issueGroups = computed(() => {
  const groups: { label: string; items: CheckIssue[] }[] = []
  for (const i of issues.value) {
    const last = groups[groups.length - 1]
    if (last && last.label === i.label) last.items.push(i)
    else groups.push({ label: i.label, items: [i] })
  }
  return groups
})

function warnStale(n?: number) {
  if (n && n > 0) {
    message.warning(
      `有 ${n} 筆今日之後的調代課是依先前課表安排的,請至今日看板/調代課紀錄重新檢視`,
      { duration: 8000 })
  }
}

async function onPublish(t: TimetableBrief) {
  publishTarget.value = t
  try {
    const r = await publishTimetable(t.id)
    message.success(`已發布「${t.name}」`)
    warnStale(r.stale_affected)
    await reload()
  } catch (e) {
    const r = publishReport((e as ApiError).detail)
    if (r) {
      report.value = r
      issues.value = publishIssues((e as ApiError).detail)
      warnMode.value = 'publish'
      warnShow.value = true
    } else {
      message.error((e as ApiError).detail as string || '發布失敗')
    }
  }
}
async function onForcePublish() {
  if (!publishTarget.value) return
  try {
    const r = await publishTimetable(publishTarget.value.id, true)
    warnShow.value = false
    const left = [issues.value.length ? '衝突' : '', incomplete.value ? '未排完課務' : '']
      .filter(Boolean).join('與')
    message.success(`已強制發布(仍有${left})`)
    warnStale(r.stale_affected)
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail as string || '發布失敗')
  }
}

/** 檢查課表(不改狀態):課務有沒有排完、有沒有衝堂等違規。有違規就開清單。 */
const checkText = ref('')
const checkOk = ref(false)
async function onCheck(t: TimetableBrief) {
  const r = await checkTimetable(t.id)
  const c = r.completeness
  const done = c.complete
    ? `課務已排完(${c.placed}/${c.required} 節)`
    : `尚有 ${c.remaining} 節未排(${c.placed}/${c.required})`
  const clash = r.issues.length ? `,有 ${r.issues.length} 項衝突` : ',沒有衝突'
  checkText.value = `「${t.name}」${done}${clash}`
  checkOk.value = r.ok
  if (r.issues.length) {
    publishTarget.value = t
    report.value = c
    issues.value = r.issues
    warnMode.value = 'check'
    warnShow.value = true
  }
}
</script>

<template>
  <n-space vertical size="large">
    <n-space align="center">
      <h1 style="margin: 0">版本與發布</h1>
      <n-select
        :value="sid" :options="semesterOptions" placeholder="選擇學期"
        style="width: 220px" @update:value="onSemesterChange"
      />
      <n-button type="primary" size="small" data-testid="v-new" @click="onCreate">新增草稿</n-button>
    </n-space>

    <n-alert type="info" :show-icon="true">
      同學期可有多份草稿並存,但至多一份「已發布」。發布新版本時,舊的已發布課表會自動轉為已封存。
      已發布/已封存的課表為快照,不可再編輯;要修改請先複製為新草稿。
    </n-alert>

    <n-alert
      v-if="checkText" :type="checkOk ? 'success' : 'warning'" closable
      data-testid="v-check-text" @close="checkText = ''"
    >
      {{ checkText }}
    </n-alert>

    <n-card size="small">
      <n-empty v-if="items.length === 0" description="尚無課表版本" />
      <table v-else class="data-table">
        <thead>
          <tr><th>名稱</th><th>狀態</th><th>已排格位</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="t in items" :key="t.id" :data-testid="`v-row-${t.name}`">
            <td>{{ t.name }}</td>
            <td>
              <n-tag :type="statusType[t.status]" size="small" :data-testid="`v-status-${t.name}`">
                {{ STATUS_LABELS[t.status] ?? t.status }}
              </n-tag>
            </td>
            <td>{{ t.entry_count }}</td>
            <td>
              <n-space>
                <n-button size="tiny" data-testid="v-check" @click="onCheck(t)">檢查課表</n-button>
                <n-button
                  v-if="t.status === 'draft'" size="tiny" type="primary"
                  data-testid="v-publish" @click="onPublish(t)"
                >
                  發布
                </n-button>
                <n-button size="tiny" data-testid="v-duplicate" @click="onDuplicate(t)">複製</n-button>
                <n-button size="tiny" @click="openRename(t)">改名</n-button>
                <n-popconfirm @positive-click="onDelete(t.id)">
                  <template #trigger><n-button size="tiny" type="error" ghost>刪除</n-button></template>
                  確定刪除此課表版本?其格位將一併移除。
                </n-popconfirm>
              </n-space>
            </td>
          </tr>
        </tbody>
      </table>
    </n-card>

    <n-modal v-model:show="renameShow" preset="card" title="課表改名" style="max-width: 400px">
      <n-space vertical>
        <n-input v-model:value="renameValue" data-testid="v-rename-input" />
        <n-button type="primary" data-testid="v-rename-save" @click="onRename">儲存</n-button>
      </n-space>
    </n-modal>

    <n-modal
      v-model:show="warnShow" preset="card" :title="warnTitle"
      style="max-width: 680px"
    >
      <n-space vertical>
        <!-- 衝突:課表排好之後又改了規則或配課(不可排時段、任課教師、每日上限…)才會出現 -->
        <template v-if="issues.length">
          <n-alert type="error" :show-icon="true">
            共 {{ issues.length }} 項衝突。通常是課表排好之後,又改了教師的不可排時段、配課的教師或節數。
            <template v-if="warnMode === 'publish'">仍可強制發布,但課表會照現在的樣子公布。</template>
          </n-alert>
          <div data-testid="v-issues" class="issues">
            <div v-for="g in issueGroups" :key="g.label" class="issue-group">
              <div class="issue-label">{{ g.label }}({{ g.items.length }})</div>
              <ul>
                <li v-for="(i, k) in g.items" :key="k" data-testid="v-issue">{{ i.message }}</li>
              </ul>
            </div>
          </div>
        </template>
        <n-alert v-if="incomplete" type="warning" :show-icon="true">
          共 {{ report?.remaining }} 節未排入(已排 {{ report?.placed }} / 應排 {{ report?.required }} 節)。
          <template v-if="warnMode === 'publish'">仍可強制發布,未排課務將不出現在課表上。</template>
        </n-alert>
        <table v-if="incomplete" class="data-table" data-testid="v-unplaced">
          <thead>
            <tr><th>班級</th><th>科目</th><th>教師</th><th>未排節數</th><th>原因</th></tr>
          </thead>
          <tbody>
            <tr v-for="u in report?.unplaced ?? []" :key="u.course_assignment_id">
              <td>{{ u.classes.join('、') }}</td>
              <td>{{ u.subject }}</td>
              <td>{{ u.teachers.join('、') }}</td>
              <td><n-text type="error">{{ u.remaining }}</n-text> / {{ u.required }}</td>
              <!-- 自動排課留下的原因(手動未排完則無);草稿發布後仍查得到 -->
              <td>{{ u.reason || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <n-space justify="end">
          <n-button data-testid="v-warn-close" @click="warnShow = false">
            {{ warnMode === 'publish' ? '取消' : '關閉' }}
          </n-button>
          <n-button
            v-if="warnMode === 'publish'" type="warning"
            data-testid="v-force-publish" @click="onForcePublish"
          >
            仍要發布
          </n-button>
        </n-space>
      </n-space>
    </n-modal>
  </n-space>
</template>

<style scoped>
.issues { max-height: 320px; overflow-y: auto; }
.issue-group + .issue-group { margin-top: 8px; }
.issue-label { font-weight: 600; }
.issues ul { margin: 4px 0 0; padding-left: 20px; }
.data-table { border-collapse: collapse; width: 100%; }
.data-table th, .data-table td { border: 1px solid var(--n-border-color, #e0e0e0); padding: 8px 10px; text-align: left; }
.data-table th { background: rgba(128,128,128,0.08); font-weight: 600; }
</style>
