<script setup lang="ts">
import {
  NButton, NDivider, NInput, NInputNumber, NModal, NPopconfirm, NSelect, NSpace, NSwitch, NTag, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  createTeacher, createTeacherAccount, deleteTeacher, listBindableAccounts, listSubjects,
  listTeachers, resetTeacherPassword, updateTeacher,
} from '@/api/basedata'
import type { BindableAccount, Subject, Teacher } from '@/api/basedata'
import TeacherTimeRules from './TeacherTimeRules.vue'

const props = defineProps<{ semesterId: number }>()
const message = useMessage()

const items = ref<Teacher[]>([])
const subjects = ref<Subject[]>([])
const accounts = ref<BindableAccount[]>([])
const search = ref('')
const subjectOptions = computed(() => subjects.value.map((s) => ({ label: s.name, value: s.id })))
const accountOptions = computed(() =>
  accounts.value.map((a) => ({ label: `${a.display_name}(${a.username})`, value: a.id })),
)

async function reload() {
  items.value = await listTeachers(props.semesterId, search.value || undefined)
}
onMounted(async () => {
  subjects.value = await listSubjects(props.semesterId)
  await reload()
})

const show = ref(false)
const editingId = ref<number | null>(null)
interface TeacherForm {
  name: string; base_periods: number; admin_title: string; admin_reduction: number
  is_external: boolean; is_active: boolean; subject_ids: number[]
  email: string; phone: string; line_id: string; user_id: number | null
}
function emptyForm(): TeacherForm {
  return {
    name: '', base_periods: 0, admin_title: '', admin_reduction: 0,
    is_external: false, is_active: true, subject_ids: [],
    email: '', phone: '', line_id: '', user_id: null,
  }
}
const form = ref<TeacherForm>(emptyForm())

// 事後補開登入帳號(匯入時沒勾、或後來才要用系統的老師);savedUserId 是「已存檔」的綁定,
// 下拉選單改了還沒存不算,重設密碼要以存檔狀態為準
const savedUserId = ref<number | null>(null)
const newUsername = ref('')
const newPassword = ref('')
const accountBusy = ref(false)
const boundAccount = computed(() =>
  accounts.value.find((a) => a.id === savedUserId.value) ?? null)

async function onCreateAccount() {
  const username = newUsername.value.trim()
  if (!username || editingId.value === null) {
    message.warning('請輸入登入帳號')
    return
  }
  accountBusy.value = true
  try {
    const acc = await createTeacherAccount(editingId.value, username, newPassword.value || undefined)
    savedUserId.value = acc.id
    form.value.user_id = acc.id
    newUsername.value = ''
    message.success(newPassword.value
      ? `已建立帳號 ${acc.username},密碼為你剛才輸入的值;老師首次登入須自行修改`
      : `已建立帳號 ${acc.username},使用系統預設密碼;老師首次登入須自行修改`)
    newPassword.value = ''
    await loadAccounts(editingId.value)
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '建立帳號失敗')
  } finally {
    accountBusy.value = false
  }
}

async function onResetPassword() {
  if (editingId.value === null) return
  accountBusy.value = true
  try {
    await resetTeacherPassword(editingId.value, newPassword.value || undefined)
    message.success(newPassword.value
      ? '密碼已重設為你剛才輸入的值;老師下次登入須自行修改'
      : '密碼已重設為系統預設密碼;老師下次登入須自行修改')
    newPassword.value = ''
  } catch (e) {
    message.error((e as ApiError).detail || '重設密碼失敗')
  } finally {
    accountBusy.value = false
  }
}

async function loadAccounts(currentTeacherId?: number) {
  accounts.value = await listBindableAccounts(props.semesterId, currentTeacherId)
}

async function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  savedUserId.value = null
  newUsername.value = ''
  newPassword.value = ''
  await loadAccounts()
  show.value = true
}
async function openEdit(t: Teacher) {
  editingId.value = t.id
  form.value = {
    name: t.name, base_periods: t.base_periods, admin_title: t.admin_title ?? '',
    admin_reduction: t.admin_reduction, is_external: t.is_external, is_active: t.is_active,
    subject_ids: t.subjects.map((s) => s.id),
    email: t.email ?? '', phone: t.phone ?? '', line_id: t.line_id ?? '', user_id: t.user_id,
  }
  savedUserId.value = t.user_id
  newUsername.value = ''
  newPassword.value = ''
  await loadAccounts(t.id)
  show.value = true
}

async function save() {
  if (!form.value.name) {
    message.warning('請輸入教師姓名')
    return
  }
  const body = {
    ...form.value,
    admin_title: form.value.admin_title || null,
    email: form.value.email || null,
    phone: form.value.phone || null,
    line_id: form.value.line_id || null,
  }
  try {
    if (editingId.value) await updateTeacher(editingId.value, body)
    else await createTeacher(props.semesterId, body)
    show.value = false
    message.success('已儲存')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '儲存失敗')
  }
}

async function remove(t: Teacher) {
  try {
    await deleteTeacher(t.id)
    message.success('已刪除')
    await reload()
  } catch (e) {
    message.error((e as ApiError).detail || '刪除失敗')
  }
}

// 時段規則
const rulesShow = ref(false)
const rulesTeacher = ref<Teacher | null>(null)
function openRules(t: Teacher) {
  rulesTeacher.value = t
  rulesShow.value = true
}
</script>

<template>
  <n-space vertical>
    <n-space>
      <n-input v-model:value="search" placeholder="搜尋教師姓名" clearable style="width: 200px" @input="reload" />
      <n-button type="primary" data-testid="teacher-add" @click="openCreate">新增教師</n-button>
    </n-space>

    <table class="data-table">
      <thead>
        <tr><th>姓名</th><th>任教科目</th><th>基本鐘點</th><th>行政</th><th>帳號</th><th>狀態</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="t in items" :key="t.id">
          <td>
            {{ t.name }}
            <n-tag v-if="t.is_external" size="tiny" type="warning" style="margin-left: 4px">外聘</n-tag>
          </td>
          <td>
            <n-space size="small">
              <n-tag v-for="s in t.subjects" :key="s.id" size="small">{{ s.name }}</n-tag>
              <n-text v-if="t.subjects.length === 0" depth="3">—</n-text>
            </n-space>
          </td>
          <td>{{ t.base_periods }}</td>
          <td>{{ t.admin_title ? `${t.admin_title}(減 ${t.admin_reduction})` : '—' }}</td>
          <td>
            <n-tag v-if="t.user_id" size="small" type="info">已綁定</n-tag>
            <n-text v-else depth="3">—</n-text>
          </td>
          <td>
            <n-tag :type="t.is_active ? 'success' : 'default'" size="small">
              {{ t.is_active ? '在職' : '離職' }}
            </n-tag>
          </td>
          <td>
            <n-space>
              <n-button size="tiny" data-testid="teacher-edit" @click="openEdit(t)">編輯</n-button>
              <n-button size="tiny" @click="openRules(t)">時段規則</n-button>
              <n-popconfirm @positive-click="remove(t)">
                <template #trigger><n-button size="tiny" type="error" ghost>刪除</n-button></template>
                確定刪除此教師?
              </n-popconfirm>
            </n-space>
          </td>
        </tr>
        <tr v-if="items.length === 0"><td colspan="7"><n-text depth="3">尚無教師</n-text></td></tr>
      </tbody>
    </table>

    <n-modal v-model:show="show" preset="card" :title="editingId ? '編輯教師' : '新增教師'" style="max-width: 460px">
      <n-space vertical>
        <n-text>姓名</n-text>
        <n-input v-model:value="form.name" data-testid="teacher-name" placeholder="如:王小明" />
        <n-text>任教科目</n-text>
        <n-select v-model:value="form.subject_ids" multiple :options="subjectOptions" placeholder="可多選" />
        <n-space>
          <n-space vertical style="flex: 1">
            <n-text>基本鐘點</n-text>
            <n-input-number v-model:value="form.base_periods" :min="0" />
          </n-space>
          <n-space vertical style="flex: 1">
            <n-text>行政減課</n-text>
            <n-input-number v-model:value="form.admin_reduction" :min="0" />
          </n-space>
        </n-space>
        <n-text>行政職稱(選填)</n-text>
        <n-input v-model:value="form.admin_title" placeholder="如:教學組長" />
        <n-space align="center">
          <n-text>外聘/業界師資</n-text>
          <n-switch v-model:value="form.is_external" />
          <n-text style="margin-left: 16px">在職</n-text>
          <n-switch v-model:value="form.is_active" />
        </n-space>

        <n-divider style="margin: 4px 0" title-placement="left">
          <n-text depth="3" style="font-size: 12px">聯絡資訊(選填,供調代課通知)</n-text>
        </n-divider>
        <n-space>
          <n-space vertical style="flex: 1">
            <n-text>Email</n-text>
            <n-input v-model:value="form.email" data-testid="teacher-email" placeholder="通知寄送用" />
          </n-space>
          <n-space vertical style="flex: 1">
            <n-text>手機</n-text>
            <n-input v-model:value="form.phone" placeholder="人工聯絡用" />
          </n-space>
        </n-space>
        <n-text>LINE ID(選填,人工聯絡用)</n-text>
        <n-input v-model:value="form.line_id" placeholder="LINE ID" />
        <n-text>綁定登入帳號(選填)</n-text>
        <n-select
          v-model:value="form.user_id"
          data-testid="teacher-account"
          :options="accountOptions"
          clearable
          placeholder="綁定後此教師可用該帳號登入查課表/請假"
        />

        <!-- 匯入時沒建帳號的老師,在這裡直接補一個;已經有帳號的則可重設密碼 -->
        <template v-if="editingId !== null">
          <n-divider style="margin: 4px 0" />
          <template v-if="boundAccount">
            <n-text>登入帳號:<b>{{ boundAccount.username }}</b></n-text>
            <n-space align="center">
              <n-input
                key="reset-password"
                v-model:value="newPassword" type="password" show-password-on="click"
                placeholder="新密碼(留空=系統預設密碼)" style="width: 230px"
                data-testid="teacher-reset-password"
              />
              <n-popconfirm @positive-click="onResetPassword">
                <template #trigger>
                  <n-button size="small" :loading="accountBusy" data-testid="teacher-reset-submit">
                    重設密碼
                  </n-button>
                </template>
                重設後這位老師目前的登入狀態會失效,下次登入必須自行改密碼。確定重設?
              </n-popconfirm>
            </n-space>
          </template>
          <template v-else>
            <n-text depth="3">沒有帳號?直接建立一個(自動綁定這位老師,首次登入須改密碼)</n-text>
            <n-space align="center">
              <n-input
                key="new-username"
                v-model:value="newUsername" placeholder="登入帳號" style="width: 160px"
                data-testid="teacher-new-username"
              />
              <n-input
                key="new-password"
                v-model:value="newPassword" type="password" show-password-on="click"
                placeholder="預設密碼(留空=系統預設)" style="width: 210px"
                data-testid="teacher-new-password"
              />
              <n-button
                size="small" :loading="accountBusy"
                data-testid="teacher-create-account" @click="onCreateAccount"
              >
                建立帳號
              </n-button>
            </n-space>
          </template>
        </template>

        <n-button type="primary" data-testid="teacher-save" @click="save">儲存</n-button>
      </n-space>
    </n-modal>

    <n-modal
      v-model:show="rulesShow"
      preset="card"
      :title="`時段規則:${rulesTeacher?.name}`"
      style="max-width: 640px"
    >
      <TeacherTimeRules
        v-if="rulesTeacher"
        :teacher-id="rulesTeacher.id"
        :semester-id="semesterId"
        @saved="rulesShow = false"
      />
    </n-modal>
  </n-space>
</template>

<style scoped>
.data-table { border-collapse: collapse; width: 100%; }
.data-table th, .data-table td { border: 1px solid var(--n-border-color, #e0e0e0); padding: 8px 10px; text-align: left; }
.data-table th { background: rgba(128,128,128,0.08); font-weight: 600; }
</style>
