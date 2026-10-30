<script setup lang="ts">
import {
  NAlert, NButton, NCard, NEmpty, NModal, NSelect, NSpace, NSwitch, NTag, NText, useMessage,
} from 'naive-ui'
import type { SelectGroupOption, SelectOption } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import { assignCover, clearCover, getCoverOptions, openCoverSlips } from '@/api/homeroomCovers'
import type { CoverOption } from '@/api/homeroomCovers'
import { listLeaves } from '@/api/leaves'
import type { AffectedPeriod, HomeroomCover, LeaveRequest } from '@/api/leaves'
import { listSemesters } from '@/api/semesters'
import { listTeachers } from '@/api/basedata'
import type { Teacher } from '@/api/basedata'
import {
  assignSubstitution, assignSubstitutionBatch, clearSubstitution, getMergeOptions,
  getRecommendations, getSwapOptions, listFundingSources, listSubstitutionTypes, openSlips,
} from '@/api/substitutions'
import type {
  BatchSkip, Candidate, MergeOption, Recommendation, SwapOption, SwapOptions, SwapPartner,
} from '@/api/substitutions'

const message = useMessage()

const semesters = ref<{ id: number; label: string }[]>([])
const sid = ref<number | null>(null)
const leaves = ref<LeaveRequest[]>([])
const types = ref<Record<string, string>>({})
const openId = ref<number | null>(null) // 展開中的受影響節次
const rec = ref<Recommendation | null>(null)
const loadingRec = ref(false)
const countsHours = ref(true)
// 代課鐘點由誰支付:印在代課通知單上。預設依假別(事假自費、其餘公費),組長可改或自行輸入
const fundingOptions = ref<{ label: string; value: string }[]>([])
const funding = ref('')
const teachers = ref<Teacher[]>([])
// 調課:展開中節次的可對調清單。swapTeacherId 為空 = 只看也教這個班的老師
const swapOpen = ref(false)
const swap = ref<SwapOptions | null>(null)
const loadingSwap = ref(false)
const swapTeacherId = ref<number | null>(null)
// 找幾週:換節次、換假單都沿用組長上次選的(常和隔三週調的學校,每次都要重選很煩)
const swapWeeks = ref(2)
// 併班(v1.3.5):這一節正在上自己班的老師;選一位,把請假老師的班併過去
const mergeOpen = ref(false)
const mergeOptions = ref<MergeOption[] | null>(null)
const SWAP_WEEK_OPTIONS = [
  { label: '本週與下週', value: 2 },
  { label: '往後共 3 週', value: 3 },
  { label: '往後共 4 週', value: 4 },
]
// 一位老師兩週內可換的節次常有二、三十個;先只列同班的,其他班收起來(展開過的老師記在這裡)
const swapExpanded = ref<Set<number>>(new Set())

const WEEKDAYS = ['週日', '週一', '週二', '週三', '週四', '週五', '週六']
function withWeekday(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return `${iso}(${WEEKDAYS[new Date(y, m - 1, d).getDay()]})`
}
// 清單裡一次列十幾個日期,年份不必每個都重複
function shortDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return `${m}/${d}(${WEEKDAYS[new Date(y, m - 1, d).getDay()]})`
}

const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))

// 只顯示有節次或有代導的假單(已銷假的收起來)
const activeLeaves = computed(() =>
  leaves.value.filter((l) => l.status === 'registered'
    && (l.affected_count > 0 || l.homeroom_covers.length > 0)))

function leaveTitle(l: LeaveRequest): string {
  const parts = [l.teacher_name, l.leave_type_label]
  if (l.affected_count) parts.push(`待處理 ${l.pending_count} 節`)
  if (l.homeroom_covers.length) parts.push(`待代導 ${l.cover_pending_count} 天`)
  return parts.join(' · ')
}

async function reload() {
  if (!sid.value) return
  leaves.value = await listLeaves(sid.value)
}

function resetSwap() {
  swapOpen.value = false
  swap.value = null
  swapTeacherId.value = null
  swapExpanded.value = new Set()
  mergeOpen.value = false
  mergeOptions.value = null
}

/** 這位老師目前要顯示的節次:有同班的就先只列同班,其他班等組長展開 */
function visibleOptions(partner: SwapPartner): SwapOption[] {
  const same = partner.options.filter((o) => o.same_class)
  if (!same.length || swapExpanded.value.has(partner.teacher_id)) return partner.options
  return same
}

function hiddenCount(partner: SwapPartner): number {
  return partner.options.length - visibleOptions(partner).length
}

function expandPartner(partner: SwapPartner) {
  swapExpanded.value = new Set([...swapExpanded.value, partner.teacher_id])
}

async function onSemesterChange(id: number) {
  sid.value = id
  openId.value = null
  rec.value = null
  resetSwap()
  ;[teachers.value] = await Promise.all([listTeachers(id), reload()])
}

onMounted(async () => {
  const [sems, subTypes, fundings] = await Promise.all(
    [listSemesters(), listSubstitutionTypes(), listFundingSources()])
  ;[semesters.value, types.value] = [sems, subTypes]
  fundingOptions.value = fundings.map((f) => ({ label: f, value: f }))
  if (semesters.value.length) await onSemesterChange(semesters.value[0].id)
})

async function openPeriod(p: AffectedPeriod) {
  if (openId.value === p.id) {
    openId.value = null
    return
  }
  openId.value = p.id
  rec.value = null
  resetSwap()
  countsHours.value = true
  funding.value = defaultFunding(leaveOf(p))
  loadingRec.value = true
  try {
    rec.value = await getRecommendations(p.id)
  } finally {
    loadingRec.value = false
  }
}

// 事假請人代課由請假教師自付,其餘由學校經費支應(與後端預設一致;學校規定不一,可改)
function defaultFunding(l: LeaveRequest | undefined): string {
  if (!l) return ''
  return l.leave_type === 'personal' ? '自費代課' : '公費代課'
}

function leaveOf(p: AffectedPeriod): LeaveRequest | undefined {
  return leaves.value.find((l) => l.affected_periods.some((x) => x.id === p.id))
}

async function assign(p: AffectedPeriod, type: string, candidate?: Candidate) {
  try {
    await assignSubstitution(p.id, {
      type,
      handler_teacher_id: candidate?.teacher_id ?? null,
      counts_toward_hours: type === 'substitute' ? countsHours.value : null,
      funding_source: type === 'substitute' ? funding.value : '',
    })
    message.success(candidate
      ? `已指派 ${candidate.teacher_name} ${types.value[type]}`
      : `已設為${types.value[type]}`)
    openId.value = null
    await reload()
  } catch (e) {
    message.error((e as ApiError).message || '指派失敗')
  }
}

// 已處置的節次寫出「怎麼處置」:只寫「→ 陳師」分不出是代課還是調課,
// 調課還得知道請假的老師哪天要回來補課
function dispositionText(l: LeaveRequest, p: AffectedPeriod): string {
  if (!p.sub_type) return p.handler_name ? `→ ${p.handler_name}` : ''
  const label = types.value[p.sub_type] ?? p.sub_type
  const who = p.handler_name ? ` → ${p.handler_name}` : ''
  if (p.sub_type === 'swap' && p.swap_date) {
    return `${label}${who}(${l.teacher_name} ${shortDate(p.swap_date)} ${p.swap_period_name}補課)`
  }
  return `${label}${who}`
}

function swapIds(l: LeaveRequest): number[] {
  return l.affected_periods
    .filter((p) => p.sub_type === 'swap' && p.status !== 'cancelled')
    .map((p) => p.id)
}

// 代課單同時涵蓋併班(紙本格子標[併])
function substituteIds(l: LeaveRequest): number[] {
  return l.affected_periods
    .filter((p) => (p.sub_type === 'substitute' || p.sub_type === 'merge')
      && p.status !== 'cancelled')
    .map((p) => p.id)
}

function printSlips(kind: 'swap' | 'substitute', ids: number[]) {
  if (sid.value) openSlips(kind, sid.value, ids)
}

function swapTeacherOptions(l: LeaveRequest) {
  return teachers.value
    .filter((t) => t.is_active && t.id !== l.teacher_id)
    .map((t) => ({ label: t.name, value: t.id }))
}

async function loadSwap(p: AffectedPeriod) {
  loadingSwap.value = true
  try {
    swap.value = await getSwapOptions(p.id, swapTeacherId.value, swapWeeks.value)
  } finally {
    loadingSwap.value = false
  }
}

async function toggleSwap(p: AffectedPeriod) {
  swapOpen.value = !swapOpen.value
  mergeOpen.value = false
  if (swapOpen.value && !swap.value) await loadSwap(p)
}

async function toggleMerge(p: AffectedPeriod) {
  mergeOpen.value = !mergeOpen.value
  swapOpen.value = false
  if (mergeOpen.value && !mergeOptions.value) {
    mergeOptions.value = (await getMergeOptions(p.id)).options
  }
}

async function assignMerge(p: AffectedPeriod, o: MergeOption) {
  try {
    await assignSubstitution(p.id, { type: 'merge', handler_teacher_id: o.teacher_id })
    message.success(`已把 ${p.class_names} 併到 ${o.teacher_name} 的 ${o.class_names} 一起上`)
    openId.value = null
    resetSwap()
    await reload()
  } catch (e) {
    message.error((e as ApiError).message || '併班失敗')
  }
}

async function onSwapTeacherChange(p: AffectedPeriod, id: number | null) {
  swapTeacherId.value = id
  await loadSwap(p)
}

async function onSwapWeeksChange(p: AffectedPeriod, weeks: number) {
  swapWeeks.value = weeks
  await loadSwap(p)
}

async function assignSwap(
  l: LeaveRequest, p: AffectedPeriod, partner: SwapPartner, opt: SwapOption,
) {
  try {
    await assignSubstitution(p.id, {
      type: 'swap',
      handler_teacher_id: partner.teacher_id,
      swap_entry_id: opt.entry_id,
      swap_date: opt.date,
      swap_period_no: opt.period_no,
    })
    message.success(
      `已和 ${partner.teacher_name} 調課:${l.teacher_name} 於 ${withWeekday(opt.date)} `
      + `${opt.period_name}補 ${opt.class_names} ${opt.subject_name}`)
    openId.value = null
    resetSwap()
    await reload()
  } catch (e) {
    message.error((e as ApiError).message || '調課失敗')
  }
}

// 整批指派代課:導師請整天或好幾天假,同一位代課老師接下所有節次(日薪代課常見)。
// 逐節點要點幾十次;這裡一次派完,派不成的節次(代課老師那節有課)列出來另外找人。
const batchShow = ref(false)
const batchLeave = ref<LeaveRequest | null>(null)
const batchTeacher = ref<number | null>(null)
const batchFunding = ref('')
const batchDate = ref('') // 空字串 = 整張假單
const batchBusy = ref(false)
const batchSkipped = ref<BatchSkip[]>([])
const batchDone = ref<number | null>(null)

function pendingOf(l: LeaveRequest): AffectedPeriod[] {
  return l.affected_periods.filter((p) => p.status === 'pending')
}
const batchTeacherOptions = computed(() =>
  teachers.value
    .filter((t) => t.id !== batchLeave.value?.teacher_id && t.is_active)
    .map((t) => ({ label: t.name, value: t.id })))
const batchDateOptions = computed(() => {
  const l = batchLeave.value
  if (!l) return []
  const days = [...new Set(pendingOf(l).map((p) => p.date))].sort()
  return [
    { label: `整張假單(待處理 ${pendingOf(l).length} 節)`, value: '' },
    ...days.map((d) => ({
      label: `只派 ${withWeekday(d)}(${pendingOf(l).filter((p) => p.date === d).length} 節)`,
      value: d,
    })),
  ]
})
function openBatch(l: LeaveRequest) {
  batchLeave.value = l
  batchTeacher.value = null
  batchFunding.value = defaultFunding(l)
  batchDate.value = ''
  batchSkipped.value = []
  batchDone.value = null
  batchShow.value = true
}
async function runBatch() {
  if (!batchLeave.value || batchTeacher.value === null) return
  batchBusy.value = true
  try {
    const r = await assignSubstitutionBatch(batchLeave.value.id, {
      handler_teacher_id: batchTeacher.value,
      funding_source: batchFunding.value,
      date: batchDate.value || null,
    })
    batchDone.value = r.assigned
    batchSkipped.value = r.skipped
    openId.value = null
    await reload()
    // 視窗還開著(列出沒派成的節次)時,範圍選單上的「待處理 N 節」要跟著更新
    const id = batchLeave.value.id
    batchLeave.value = leaves.value.find((l) => l.id === id) ?? batchLeave.value
    if (r.skipped.length === 0) {
      message.success(`已指派 ${r.assigned} 節代課`)
      batchShow.value = false
    }
  } catch (e) {
    message.error((e as ApiError).message || '指派失敗')
  } finally {
    batchBusy.value = false
  }
}

async function undo(p: AffectedPeriod) {
  await clearSubstitution(p.id)
  message.info('已撤回處置,退回待處理')
  await reload()
}

// ── 代導(v1.4.0):導師請假那天由誰代他帶班。以天為單位,有課的老師也能代導 ──
const coverOpenId = ref<number | null>(null)
const coverOptions = ref<CoverOption[]>([])
const coverTeacher = ref<number | null>(null)
const coverBusy = ref(false)

// 下拉選單依序分組:同年級導師 → 該班任課老師 → 其他老師
const coverSelectOptions = computed(() => {
  const groups: (SelectGroupOption & { children: SelectOption[] })[] = []
  for (const o of coverOptions.value) {
    let g = groups.find((x) => x.key === o.group)
    if (!g) {
      g = { type: 'group', label: o.group_label, key: o.group, children: [] }
      groups.push(g)
    }
    g.children.push({
      label: o.note ? `${o.teacher_name}(${o.note})` : o.teacher_name, value: o.teacher_id,
    })
  }
  return groups
})

async function openCover(c: HomeroomCover) {
  if (coverOpenId.value === c.id) {
    coverOpenId.value = null
    return
  }
  coverOpenId.value = c.id
  coverTeacher.value = null
  coverOptions.value = (await getCoverOptions(c.id)).options
}

/** 同一張假單、同一班,除了這天以外還沒安排的日子 */
function restCount(l: LeaveRequest, c: HomeroomCover): number {
  return l.homeroom_covers.filter((x) => x.id !== c.id && x.class_name === c.class_name
    && x.status === 'pending').length
}

async function assignCoverTo(c: HomeroomCover, wholeLeave: boolean) {
  if (coverTeacher.value === null) return
  const name = coverOptions.value.find((o) => o.teacher_id === coverTeacher.value)?.teacher_name
  coverBusy.value = true
  try {
    const r = await assignCover(
      c.id, { handler_teacher_id: coverTeacher.value, whole_leave: wholeLeave })
    if (r.skipped.length) {
      message.warning(
        `已指派 ${name} 代導 ${r.assigned} 天;沒派成:`
        + r.skipped.map((x) => `${shortDate(x.date)}(${x.reason})`).join('、'),
        { duration: 8000 })
    } else {
      message.success(`已指派 ${name} 代導 ${c.class_name}(${r.assigned} 天)`)
    }
    coverOpenId.value = null
    await reload()
  } catch (e) {
    message.error((e as ApiError).message || '指派失敗')
  } finally {
    coverBusy.value = false
  }
}

async function markNoCover(c: HomeroomCover) {
  try {
    await assignCover(c.id, { no_cover: true })
    message.success(`${shortDate(c.date)} ${c.class_name} 設為不需代導`)
    coverOpenId.value = null
    await reload()
  } catch (e) {
    message.error((e as ApiError).message || '設定失敗')
  }
}

async function undoCover(c: HomeroomCover) {
  try {
    await clearCover(c.id)
    message.info('已撤回,退回待代導')
    await reload()
  } catch (e) {
    message.error((e as ApiError).message || '撤回失敗')
  }
}

function coverPrintIds(l: LeaveRequest): number[] {
  return l.homeroom_covers
    .filter((c) => c.handler_name && c.status !== 'cancelled')
    .map((c) => c.id)
}

function printCovers(ids: number[]) {
  if (sid.value) openCoverSlips(sid.value, ids)
}

const COVER_STATUS: Record<HomeroomCover['status'], { type: string; label: string }> = {
  pending: { type: 'warning', label: '待代導' },
  resolved: { type: 'success', label: '已安排' },
  completed: { type: 'info', label: '已完成' },
  cancelled: { type: 'default', label: '已取消' },
}

const STATUS: Record<AffectedPeriod['status'], { type: string; label: string }> = {
  pending: { type: 'warning', label: '待處理' },
  resolved: { type: 'success', label: '已確認' },
  completed: { type: 'info', label: '已完成' },
  cancelled: { type: 'default', label: '已取消' },
}

// 補登(v1.4.2):臨時找人代課、事後才登記請假,節次已經過了還是待處理。
// 補登不通知老師(已經去上過課了)、不能調課;補登後和其他過去的節次一樣不能再改
function statusOf(x: AffectedPeriod | HomeroomCover, table: typeof STATUS) {
  return x.status === 'pending' && x.is_past ? { type: 'error', label: '待補登' } : table[x.status]
}

const hasPastPending = computed(() =>
  !!batchLeave.value && pendingOf(batchLeave.value).some((p) => p.is_past))

function candidateTagType(c: Candidate): string {
  if (c.same_subject) return 'success'
  if (c.at_school_that_day) return 'info'
  return 'default'
}
</script>

<template>
  <!-- 視窗要放在 n-space 外面:n-space 會把每個子節點包一層沒有 key 的 div,假單卡片數量一變,
       視窗就跟著換位置重掛,正式建置下會關不掉(v1.2.14 在「學期與節次表」踩過)。 -->
  <div>
    <n-space vertical size="large">
      <n-space align="center">
        <h2 style="margin: 0">調代課處理</h2>
        <n-select
          :value="sid" :options="semesterOptions" style="width: 220px"
          placeholder="選擇學期" @update:value="onSemesterChange"
        />
      </n-space>

      <n-empty v-if="!sid" description="請先建立學期" />
      <n-empty v-else-if="!activeLeaves.length" description="目前沒有待處理的請假" />

      <template v-else>
        <n-card
          v-for="l in activeLeaves" :key="l.id" size="small" data-testid="sub-leave"
          :title="leaveTitle(l)"
        >
          <template
            v-if="pendingOf(l).length > 1 || swapIds(l).length || substituteIds(l).length
              || coverPrintIds(l).length"
            #header-extra
          >
            <n-space size="small">
              <n-button
                v-if="pendingOf(l).length > 1" size="small" type="primary" ghost
                data-testid="sub-batch-open" @click="openBatch(l)"
              >
                整批指派代課
              </n-button>
              <n-button
                v-if="swapIds(l).length" size="small" data-testid="sub-print-leave"
                @click="printSlips('swap', swapIds(l))"
              >
                列印調課單({{ swapIds(l).length }} 節)
              </n-button>
              <n-button
                v-if="substituteIds(l).length" size="small" data-testid="sub-print-leave-sub"
                @click="printSlips('substitute', substituteIds(l))"
              >
                列印代課單({{ substituteIds(l).length }} 節)
              </n-button>
              <n-button
                v-if="coverPrintIds(l).length" size="small" data-testid="sub-print-leave-cover"
                @click="printCovers(coverPrintIds(l))"
              >
                列印代導單({{ coverPrintIds(l).length }} 天)
              </n-button>
            </n-space>
          </template>
          <n-space vertical size="small">
            <div v-for="p in l.affected_periods" :key="p.id" data-testid="sub-period">
              <n-space align="center" :wrap="false">
                <n-tag size="small" :type="statusOf(p, STATUS).type as never" data-testid="sub-status">
                  {{ statusOf(p, STATUS).label }}
                </n-tag>
                <n-text style="min-width: 260px">
                  {{ withWeekday(p.date) }} {{ p.period_name }} ·
                  {{ p.class_names }} {{ p.subject_name }}
                  <n-text v-if="p.room_name" depth="3">@{{ p.room_name }}</n-text>
                </n-text>
                <n-text
                  v-if="p.sub_type || p.handler_name" type="success" data-testid="sub-handler"
                >
                  {{ dispositionText(l, p) }}
                </n-text>
                <n-button
                  v-if="p.status === 'pending'" size="small" type="primary"
                  data-testid="sub-handle" @click="openPeriod(p)"
                >
                  {{ openId === p.id ? '收合' : p.is_past ? '補登' : '處理' }}
                </n-button>
                <n-button
                  v-else-if="p.status === 'resolved'" size="small" tertiary
                  data-testid="sub-undo" @click="undo(p)"
                >
                  撤回
                </n-button>
                <n-button
                  v-if="p.sub_type === 'swap' && p.status !== 'cancelled'" size="small" tertiary
                  data-testid="sub-print-slip" @click="printSlips('swap', [p.id])"
                >
                  列印調課單
                </n-button>
                <n-button
                  v-if="(p.sub_type === 'substitute' || p.sub_type === 'merge')
                    && p.status !== 'cancelled'"
                  size="small" tertiary
                  data-testid="sub-print-slip-sub" @click="printSlips('substitute', [p.id])"
                >
                  列印代課單
                </n-button>
              </n-space>

              <!-- 展開:代課推薦 + 其他處置 -->
              <n-card
                v-if="openId === p.id" size="small" embedded style="margin: 8px 0 8px 40px"
                data-testid="sub-panel"
              >
                <n-space vertical size="small">
                  <n-alert v-if="p.is_past" type="info" :bordered="false" data-testid="sub-backfill-hint">
                    這一節已經過了:補登後直接列入代課鐘點統計,不會通知老師。
                    補登後就不能再修改或撤回,請確認後再按。
                  </n-alert>
                  <n-text v-if="loadingRec" depth="3">計算可代教師中…</n-text>

                  <template v-else-if="rec">
                    <n-alert
                      v-if="!rec.candidates.length" type="warning" :bordered="false"
                      data-testid="sub-nocandidate"
                    >
                      {{ rec.no_candidate_hint }}
                    </n-alert>

                    <template v-else>
                      <n-space align="center">
                        <n-text depth="3">代課鐘點</n-text>
                        <n-switch v-model:value="countsHours" size="small" />
                        <n-text depth="3">{{ countsHours ? '計入' : '不計' }}</n-text>
                        <n-text depth="3">計費方式</n-text>
                        <n-select
                          v-model:value="funding" size="small" style="width: 150px"
                          filterable tag :options="fundingOptions"
                          data-testid="sub-funding"
                        />
                      </n-space>
                      <div
                        v-for="c in rec.candidates" :key="c.teacher_id"
                        data-testid="sub-candidate"
                      >
                        <n-space align="center" :wrap="false">
                          <n-button
                            size="small" type="primary" ghost
                            data-testid="sub-pick" @click="assign(p, 'substitute', c)"
                          >
                            指派 {{ c.teacher_name }}
                          </n-button>
                          <n-tag size="small" :type="candidateTagType(c) as never">
                            {{ c.reasons.join(' · ') }}
                          </n-tag>
                        </n-space>
                      </div>
                    </template>
                  </template>

                  <n-space size="small" style="margin-top: 8px">
                    <n-text depth="3">或改採:</n-text>
                    <!-- 調課要安排之後的補課節次,已經過去的節次無法補登調課 -->
                    <n-button
                      v-if="!p.is_past"
                      size="tiny" :type="swapOpen ? 'primary' : 'default'"
                      data-testid="sub-swap" @click="toggleSwap(p)"
                    >
                      調課
                    </n-button>
                    <n-button
                      size="tiny" :type="mergeOpen ? 'primary' : 'default'"
                      data-testid="sub-merge" @click="toggleMerge(p)"
                    >
                      併班
                    </n-button>
                    <n-button
                      size="tiny" data-testid="sub-selfstudy" @click="assign(p, 'self_study')"
                    >
                      自習
                    </n-button>
                    <n-button size="tiny" data-testid="sub-cancel" @click="assign(p, 'cancel')">
                      不處理
                    </n-button>
                  </n-space>

                  <!-- 併班:把這班併到這一節正在上課的老師那裡一起上(v1.3.5) -->
                  <div v-if="mergeOpen" class="swap" data-testid="sub-merge-panel">
                    <n-text depth="3" class="swap-intro">
                      併班 = 把 {{ p.class_names }} 併到這一節正在上課的老師班上一起上(不另計代課鐘點)。
                      同年級的排前面;沒有課的老師請用上面的「代課」。
                    </n-text>
                    <n-text v-if="mergeOptions && !mergeOptions.length" depth="3" data-testid="sub-merge-empty">
                      這一節沒有其他老師在上課,無法併班;可改用代課或自習。
                    </n-text>
                    <div v-for="o in mergeOptions ?? []" :key="`${o.teacher_id}-${o.class_names}`" class="swap-partner">
                      <n-space align="center" size="small">
                        <n-button
                          size="small" type="primary" ghost data-testid="sub-merge-pick"
                          @click="assignMerge(p, o)"
                        >
                          併到 {{ o.teacher_name }}({{ o.class_names }})
                        </n-button>
                        <n-text>{{ o.subject_name }}</n-text>
                        <n-tag v-if="o.same_grade" size="small" type="success">同年級</n-tag>
                        <n-tag v-if="o.same_subject" size="small" type="info">同科目</n-tag>
                      </n-space>
                    </div>
                  </div>

                  <!-- 調課:乙來上這一節,甲在往後幾週內補回乙的一節 -->
                  <div v-if="swapOpen" class="swap" data-testid="sub-swap-panel">
                    <n-text depth="3" class="swap-intro">
                      調課 = 請另一位老師來上這一節,{{ l.teacher_name }}再找一天補回對方的一節(不計代課鐘點)。
                      <template v-if="swap">
                        以下是 {{ shortDate(swap.date_from) }} 到 {{ shortDate(swap.date_to) }}
                        之間,雙方都有空的節次,點一下就成立。
                      </template>
                    </n-text>
                    <n-space align="center" size="small" style="margin-bottom: 6px">
                      <n-select
                        :value="swapTeacherId" :options="swapTeacherOptions(l)" filterable clearable
                        size="small" style="width: 200px" placeholder="只看也教這班的老師"
                        data-testid="sub-swap-teacher"
                        @update:value="(v: number | null) => onSwapTeacherChange(p, v)"
                      />
                      <n-text depth="3">也可以指定其他老師</n-text>
                      <n-text depth="3" style="margin-left: 12px">範圍</n-text>
                      <n-select
                        :value="swapWeeks" :options="SWAP_WEEK_OPTIONS" size="small"
                        style="width: 140px" data-testid="sub-swap-weeks"
                        @update:value="(v: number) => onSwapWeeksChange(p, v)"
                      />
                    </n-space>

                    <n-text v-if="loadingSwap" depth="3">尋找可對調的節次…</n-text>
                    <template v-else-if="swap">
                      <n-alert
                        v-if="!swap.partners.length" type="info" :bordered="false"
                        data-testid="sub-swap-empty"
                      >
                        {{ swapTeacherId
                          ? '這位老師目前無法對調(可能已停用)。'
                          : '沒有其他老師也教這個班,可以從上方指定一位老師看看。' }}
                      </n-alert>
                      <div
                        v-for="partner in swap.partners" :key="partner.teacher_id"
                        class="swap-partner" data-testid="sub-swap-partner"
                      >
                        <n-space align="center" size="small">
                          <b>{{ partner.teacher_name }}</b>
                          <n-tag v-if="partner.teaches_same_class" size="small" type="success">
                            也教這班
                          </n-tag>
                        </n-space>
                        <n-text v-if="partner.blocked_reason" depth="3" class="swap-note">
                          無法對調:{{ partner.blocked_reason }}
                        </n-text>
                        <n-text v-else-if="!partner.options.length" depth="3" class="swap-note">
                          這段期間找不到雙方都有空的節次,可試著放寬週數
                        </n-text>
                        <n-space v-else size="small" class="swap-note">
                          <n-button
                            v-for="opt in visibleOptions(partner)"
                            :key="`${opt.entry_id}-${opt.date}-${opt.period_no}`"
                            size="small" :type="opt.same_class ? 'primary' : 'default'" ghost
                            data-testid="sub-swap-option" @click="assignSwap(l, p, partner, opt)"
                          >
                            {{ shortDate(opt.date) }} {{ opt.period_name }} ·
                            {{ opt.class_names }} {{ opt.subject_name }}
                            <span v-if="opt.in_block" class="swap-block">(連堂之一)</span>
                          </n-button>
                          <n-button
                            v-if="hiddenCount(partner)" size="small" text type="primary"
                            data-testid="sub-swap-more" @click="expandPartner(partner)"
                          >
                            顯示其他班級的 {{ hiddenCount(partner) }} 個節次
                          </n-button>
                        </n-space>
                      </div>
                    </template>
                  </div>
                </n-space>
              </n-card>
            </div>
          </n-space>

          <!-- 代導(v1.4.0):請假的是導師,他帶的班每天要有人帶 -->
          <div
            v-if="l.homeroom_covers.length" :class="['covers', { 'covers-sep': l.affected_count }]"
            data-testid="sub-covers"
          >
            <n-text strong>代導</n-text>
            <n-text depth="3">({{ l.teacher_name }} 是導師,請假期間每天要有人帶班)</n-text>
            <div v-for="c in l.homeroom_covers" :key="c.id" class="cover" data-testid="sub-cover">
              <n-space align="center" :wrap="false">
                <n-tag
                  size="small" :type="statusOf(c, COVER_STATUS).type as never"
                  data-testid="sub-cover-status"
                >
                  {{ statusOf(c, COVER_STATUS).label }}
                </n-tag>
                <n-text style="min-width: 260px">
                  {{ withWeekday(c.date) }} {{ c.part_label }} · {{ c.class_name }}
                </n-text>
                <n-text
                  v-if="c.no_cover || c.handler_name" type="success"
                  data-testid="sub-cover-handler"
                >
                  {{ c.no_cover ? '不需代導' : `代導 → ${c.handler_name}` }}
                </n-text>
                <n-button
                  v-if="c.status === 'pending'" size="small" type="primary"
                  data-testid="sub-cover-handle" @click="openCover(c)"
                >
                  {{ coverOpenId === c.id ? '收合' : c.is_past ? '補登代導' : '安排代導' }}
                </n-button>
                <n-button
                  v-else-if="c.status === 'resolved'" size="small" tertiary
                  data-testid="sub-cover-undo" @click="undoCover(c)"
                >
                  撤回
                </n-button>
                <n-button
                  v-if="c.handler_name && c.status !== 'cancelled'" size="small" tertiary
                  data-testid="sub-cover-print" @click="printCovers([c.id])"
                >
                  列印代導單
                </n-button>
              </n-space>

              <n-card
                v-if="coverOpenId === c.id" size="small" embedded style="margin: 8px 0 8px 40px"
                data-testid="sub-cover-panel"
              >
                <n-space vertical size="small">
                  <n-alert v-if="c.is_past" type="info" :bordered="false" data-testid="sub-cover-backfill-hint">
                    這一天已經過了:補登後直接列入代導統計,不會通知老師。補登後就不能再修改或撤回。
                  </n-alert>
                  <n-text depth="3">
                    代導不是上課,有課的老師也可以代導;當天整天請假的老師不會列出。
                  </n-text>
                  <n-space align="center">
                    <n-select
                      v-model:value="coverTeacher" :options="coverSelectOptions" filterable
                      placeholder="選擇代導老師(可打字搜尋)" style="width: 300px"
                      data-testid="sub-cover-teacher"
                    />
                    <n-button
                      size="small" type="primary" :disabled="coverTeacher === null"
                      :loading="coverBusy" data-testid="sub-cover-assign"
                      @click="assignCoverTo(c, false)"
                    >
                      指派這一天
                    </n-button>
                    <n-button
                      v-if="restCount(l, c)" size="small" type="primary" ghost
                      :disabled="coverTeacher === null" :loading="coverBusy"
                      data-testid="sub-cover-assign-all" @click="assignCoverTo(c, true)"
                    >
                      指派整段({{ restCount(l, c) + 1 }} 天)
                    </n-button>
                  </n-space>
                  <n-space size="small" align="center">
                    <n-text depth="3">或</n-text>
                    <n-button size="tiny" data-testid="sub-cover-none" @click="markNoCover(c)">
                      不需代導
                    </n-button>
                    <n-text depth="3">(例如整班校外教學)</n-text>
                  </n-space>
                </n-space>
              </n-card>
            </div>
          </div>
        </n-card>
      </template>
    </n-space>

    <n-modal
      v-model:show="batchShow" preset="card" style="max-width: 560px"
      :title="`整批指派代課:${batchLeave?.teacher_name ?? ''}`" data-testid="sub-batch"
    >
      <n-space vertical>
        <n-text depth="3">
          把這張假單還沒處理的節次,一次指派給同一位代課老師。已經處理過的節次不會更動;
          代課老師自己有課的節次會跳過,並列出來讓你另外找人。
        </n-text>
        <n-text v-if="hasPastPending" depth="3" data-testid="sub-batch-backfill">
          已經過去、還沒處理的節次會一併補登:直接列入鐘點統計,不會通知老師。
        </n-text>
        <n-space align="center">
          <n-text style="min-width: 70px">代課老師</n-text>
          <n-select
            v-model:value="batchTeacher" :options="batchTeacherOptions" filterable
            placeholder="選擇教師" style="width: 240px" data-testid="sub-batch-teacher"
          />
        </n-space>
        <n-space align="center">
          <n-text style="min-width: 70px">計費方式</n-text>
          <n-select
            v-model:value="batchFunding" :options="fundingOptions" filterable tag
            style="width: 240px" data-testid="sub-batch-funding"
          />
        </n-space>
        <n-space align="center">
          <n-text style="min-width: 70px">範圍</n-text>
          <n-select
            v-model:value="batchDate" :options="batchDateOptions"
            style="width: 320px" data-testid="sub-batch-date"
          />
        </n-space>

        <n-alert
          v-if="batchSkipped.length" type="warning" :show-icon="true"
          :title="`已指派 ${batchDone} 節;有 ${batchSkipped.length} 節沒有派成`"
          data-testid="sub-batch-skipped"
        >
          <ul class="batch-skips">
            <li v-for="s in batchSkipped" :key="s.affected_period_id" data-testid="sub-batch-skip">
              {{ withWeekday(s.date) }} {{ s.period_name }} · {{ s.class_names }} {{ s.subject_name }}
              ——{{ s.reason }}
            </li>
          </ul>
          這幾節仍是「待處理」,請關閉視窗後個別處理。
        </n-alert>

        <n-space justify="end">
          <n-button data-testid="sub-batch-close" @click="batchShow = false">
            {{ batchSkipped.length ? '關閉' : '取消' }}
          </n-button>
          <n-button
            v-if="!batchSkipped.length" type="primary" :loading="batchBusy"
            :disabled="batchTeacher === null" data-testid="sub-batch-run" @click="runBatch"
          >
            指派
          </n-button>
        </n-space>
      </n-space>
    </n-modal>
  </div>
</template>

<style scoped>
.batch-skips { margin: 4px 0 6px; padding-left: 20px; }
.covers-sep { margin-top: 12px; padding-top: 8px; border-top: 1px dashed rgba(128, 128, 128, 0.35); }
.cover { margin-top: 6px; }
.swap { margin-top: 8px; padding-top: 8px; border-top: 1px dashed rgba(128, 128, 128, 0.35); }
.swap-intro { display: block; margin-bottom: 6px; }
.swap-partner { margin: 6px 0; }
.swap-note { display: block; margin: 4px 0 0 12px; }
.swap-block { margin-left: 4px; opacity: 0.7; }
</style>
