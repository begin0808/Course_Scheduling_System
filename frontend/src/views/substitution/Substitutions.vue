<script setup lang="ts">
import {
  NAlert, NButton, NCard, NEmpty, NSelect, NSpace, NSwitch, NTag, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import { listLeaves } from '@/api/leaves'
import type { AffectedPeriod, LeaveRequest } from '@/api/leaves'
import { listSemesters } from '@/api/semesters'
import { listTeachers } from '@/api/basedata'
import type { Teacher } from '@/api/basedata'
import {
  assignSubstitution, clearSubstitution, getRecommendations, getSwapOptions,
  listSubstitutionTypes,
} from '@/api/substitutions'
import type {
  Candidate, Recommendation, SwapOption, SwapOptions, SwapPartner,
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
const teachers = ref<Teacher[]>([])
// 調課:展開中節次的可對調清單。swapTeacherId 為空 = 只看也教這個班的老師
const swapOpen = ref(false)
const swap = ref<SwapOptions | null>(null)
const loadingSwap = ref(false)
const swapTeacherId = ref<number | null>(null)
// 找幾週:換節次、換假單都沿用組長上次選的(常和隔三週調的學校,每次都要重選很煩)
const swapWeeks = ref(2)
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

// 只顯示還有待處理節次的假單(已全部處理或已銷假的收起來)
const activeLeaves = computed(() =>
  leaves.value.filter((l) => l.status === 'registered' && l.affected_count > 0))

async function reload() {
  if (!sid.value) return
  leaves.value = await listLeaves(sid.value)
}

function resetSwap() {
  swapOpen.value = false
  swap.value = null
  swapTeacherId.value = null
  swapExpanded.value = new Set()
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
  ;[semesters.value, types.value] = await Promise.all([listSemesters(), listSubstitutionTypes()])
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
  loadingRec.value = true
  try {
    rec.value = await getRecommendations(p.id)
  } finally {
    loadingRec.value = false
  }
}

async function assign(p: AffectedPeriod, type: string, candidate?: Candidate) {
  try {
    await assignSubstitution(p.id, {
      type,
      handler_teacher_id: candidate?.teacher_id ?? null,
      counts_toward_hours: type === 'substitute' ? countsHours.value : null,
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
  if (swapOpen.value && !swap.value) await loadSwap(p)
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

async function undo(p: AffectedPeriod) {
  await clearSubstitution(p.id)
  message.info('已撤回處置,退回待處理')
  await reload()
}

const STATUS: Record<AffectedPeriod['status'], { type: string; label: string }> = {
  pending: { type: 'warning', label: '待處理' },
  resolved: { type: 'success', label: '已確認' },
  completed: { type: 'info', label: '已完成' },
  cancelled: { type: 'default', label: '已取消' },
}

function candidateTagType(c: Candidate): string {
  if (c.same_subject) return 'success'
  if (c.at_school_that_day) return 'info'
  return 'default'
}
</script>

<template>
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
        :title="`${l.teacher_name} · ${l.leave_type_label} · 待處理 ${l.pending_count} 節`"
      >
        <n-space vertical size="small">
          <div v-for="p in l.affected_periods" :key="p.id" data-testid="sub-period">
            <n-space align="center" :wrap="false">
              <n-tag size="small" :type="STATUS[p.status].type as never">
                {{ STATUS[p.status].label }}
              </n-tag>
              <n-text style="min-width: 260px">
                {{ withWeekday(p.date) }} {{ p.period_name }} ·
                {{ p.class_names }} {{ p.subject_name }}
                <n-text v-if="p.room_name" depth="3">@{{ p.room_name }}</n-text>
              </n-text>
              <n-text v-if="p.handler_name" type="success" data-testid="sub-handler">
                → {{ p.handler_name }}
              </n-text>
              <n-button
                v-if="p.status === 'pending'" size="small" type="primary"
                data-testid="sub-handle" @click="openPeriod(p)"
              >
                {{ openId === p.id ? '收合' : '處理' }}
              </n-button>
              <n-button
                v-else-if="p.status === 'resolved'" size="small" tertiary
                data-testid="sub-undo" @click="undo(p)"
              >
                撤回
              </n-button>
            </n-space>

            <!-- 展開:代課推薦 + 其他處置 -->
            <n-card
              v-if="openId === p.id" size="small" embedded style="margin: 8px 0 8px 40px"
              data-testid="sub-panel"
            >
              <n-space vertical size="small">
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
                  <n-button
                    size="tiny" :type="swapOpen ? 'primary' : 'default'"
                    data-testid="sub-swap" @click="toggleSwap(p)"
                  >
                    調課
                  </n-button>
                  <n-button size="tiny" data-testid="sub-merge" @click="assign(p, 'merge')">
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
      </n-card>
    </template>
  </n-space>
</template>

<style scoped>
.swap { margin-top: 8px; padding-top: 8px; border-top: 1px dashed rgba(128, 128, 128, 0.35); }
.swap-intro { display: block; margin-bottom: 6px; }
.swap-partner { margin: 6px 0; }
.swap-note { display: block; margin: 4px 0 0 12px; }
.swap-block { margin-left: 4px; opacity: 0.7; }
</style>
