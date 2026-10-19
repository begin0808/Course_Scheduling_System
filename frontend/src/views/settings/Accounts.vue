<script setup lang="ts">
// 帳號管理(v1.3.1,限系統管理員):教學組長、教務主任的帳號與角色在這裡設定。
// 先前畫面上無處可設,填了「行政職稱」登入後仍是教師(使用者來信詢問)。
import {
  NAlert, NButton, NCard, NCheckbox, NCheckboxGroup, NEmpty, NInput, NModal, NPopconfirm,
  NRadioButton, NRadioGroup, NSpace, NTag, NText, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import {
  MANAGED_ROLES, ROLE_LABELS, createUser, listUsers, renameUser, resetUserPassword, setUserActive,
  setUserRoles,
} from '@/api/users'
import type { ManagedRole, UserAccount } from '@/api/users'
import { useAuthStore } from '@/stores/auth'

const message = useMessage()
const auth = useAuthStore()

const users = ref<UserAccount[]>([])
const scope = ref<'staff' | 'all'>('staff')
const keyword = ref('')

const isStaff = (u: UserAccount) => u.roles.some((r) => r !== 'teacher')
const shown = computed(() => {
  const k = keyword.value.trim()
  return users.value.filter((u) =>
    (scope.value === 'all' || isStaff(u))
    && (!k || [u.username, u.display_name, ...u.teacher_names].some((x) => x.includes(k))))
    // 啟用中的排前面:停用的帳號留著是為了歷史紀錄,平常不需要看到
    .sort((a, b) => Number(b.is_active) - Number(a.is_active))
})

async function reload() {
  users.value = await listUsers()
}
onMounted(reload)

function errorText(e: unknown, fallback: string): string {
  return (e as ApiError).message || fallback
}
const isMe = (u: UserAccount) => u.username === auth.user?.username

// ── 新增帳號 ──
const createShow = ref(false)
const form = ref({ username: '', display_name: '', password: '', roles: ['scheduler'] as ManagedRole[] })
function openCreate() {
  form.value = { username: '', display_name: '', password: '', roles: ['scheduler'] }
  createShow.value = true
}
async function onCreate() {
  if (!form.value.username.trim()) return message.warning('請輸入登入帳號')
  if (!form.value.roles.length) return message.warning('請至少勾選一個身分')
  try {
    const u = await createUser(form.value)
    createShow.value = false
    message.success(`已建立「${u.display_name}」的帳號,對方第一次登入時要自行改密碼`)
    await reload()
  } catch (e) {
    message.error(errorText(e, '建立失敗'))
  }
}

// ── 設定身分 ──
const rolesShow = ref(false)
const target = ref<UserAccount | null>(null)
const roles = ref<ManagedRole[]>([])
const displayName = ref('')
function openRoles(u: UserAccount) {
  target.value = u
  roles.value = u.roles.filter((r): r is ManagedRole => (MANAGED_ROLES as string[]).includes(r))
  displayName.value = u.display_name
  rolesShow.value = true
}
async function onSaveRoles() {
  if (!target.value) return
  try {
    if (displayName.value.trim() && displayName.value.trim() !== target.value.display_name) {
      await renameUser(target.value.id, displayName.value.trim())
    }
    await setUserRoles(target.value.id, roles.value)
    rolesShow.value = false
    message.success('已更新,對方重新整理頁面後就會看到新的選單')
    await reload()
  } catch (e) {
    message.error(errorText(e, '儲存失敗'))
  }
}

// ── 重設密碼 ──
const pwShow = ref(false)
const newPassword = ref('')
function openPassword(u: UserAccount) {
  target.value = u
  newPassword.value = ''
  pwShow.value = true
}
async function onResetPassword() {
  if (!target.value) return
  try {
    await resetUserPassword(target.value.id, newPassword.value)
    pwShow.value = false
    message.success('已重設密碼,對方下次登入時要自行改密碼')
    await reload()
  } catch (e) {
    message.error(errorText(e, '重設失敗'))
  }
}

async function onToggleActive(u: UserAccount) {
  try {
    await setUserActive(u.id, !u.is_active)
    message.success(u.is_active ? '已停用,對方立刻無法登入' : '已重新啟用')
    await reload()
  } catch (e) {
    message.error(errorText(e, '操作失敗'))
  }
}
</script>

<template>
  <!-- 視窗放在 n-space 外面:n-space 裡有 v-for 時,正式建置下視窗會關不掉(v1.2.14 踩過) -->
  <div>
    <n-space vertical size="large">
      <n-space align="center" justify="space-between">
        <h1 style="margin: 0">帳號管理</h1>
        <n-button type="primary" data-testid="acc-add" @click="openCreate">新增帳號</n-button>
      </n-space>

      <n-alert type="info" :show-icon="true">
        教學組長、教務主任的帳號在這裡設定。教師資料裡的「行政職稱」只用在減課與顯示,不會改變登入權限。
        <ul style="margin: 6px 0 0; padding-left: 20px">
          <li>
            <b>組長本身也是教師</b>(已經有教師帳號):切到「全部帳號」找到他,按「設定身分」勾選「教學組長」。
            同一個帳號就能查自己的課表、也能排課,不用兩組帳密。
          </li>
          <li><b>另外開一個行政帳號</b>:按右上角「新增帳號」。</li>
          <li>不再使用的帳號請「停用」:立刻無法登入,帳號與請假、調代課紀錄都保留。</li>
        </ul>
      </n-alert>

      <n-space align="center">
        <n-radio-group v-model:value="scope" data-testid="acc-scope">
          <n-radio-button value="staff">行政帳號</n-radio-button>
          <n-radio-button value="all">全部帳號</n-radio-button>
        </n-radio-group>
        <n-input
          v-model:value="keyword" clearable placeholder="搜尋帳號、名稱或教師姓名"
          style="width: 240px" data-testid="acc-search"
        />
      </n-space>

      <n-card size="small">
        <n-empty v-if="shown.length === 0" description="沒有符合的帳號" />
        <table v-else class="data-table" data-testid="acc-table">
          <thead>
            <tr><th>登入帳號</th><th>名稱</th><th>身分</th><th>綁定教師</th><th>狀態</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="u in shown" :key="u.id" :data-testid="`acc-row-${u.username}`">
              <td>{{ u.username }}<n-text v-if="isMe(u)" depth="3">(你)</n-text></td>
              <td>{{ u.display_name }}</td>
              <td>
                <n-space size="small">
                  <n-tag
                    v-for="r in u.roles" :key="r" size="small"
                    :type="r === 'teacher' ? 'default' : r === 'admin' ? 'error' : 'success'"
                  >
                    {{ ROLE_LABELS[r] ?? r }}
                  </n-tag>
                </n-space>
              </td>
              <td>{{ u.teacher_names.join('、') || '—' }}</td>
              <td>
                <n-tag size="small" :type="u.is_active ? 'success' : 'default'">
                  {{ u.is_active ? '啟用' : '停用' }}
                </n-tag>
                <n-tag v-if="u.must_change_password && u.is_active" size="small" type="warning" style="margin-left: 4px">
                  待改密碼
                </n-tag>
              </td>
              <td>
                <n-space size="small">
                  <n-button size="tiny" data-testid="acc-roles" @click="openRoles(u)">設定身分</n-button>
                  <n-button
                    v-if="!isMe(u)" size="tiny" data-testid="acc-password" @click="openPassword(u)"
                  >
                    重設密碼
                  </n-button>
                  <n-popconfirm v-if="!isMe(u)" @positive-click="onToggleActive(u)">
                    <template #trigger>
                      <n-button size="tiny" :type="u.is_active ? 'error' : 'primary'" ghost data-testid="acc-active">
                        {{ u.is_active ? '停用' : '啟用' }}
                      </n-button>
                    </template>
                    {{ u.is_active ? '停用後對方立刻無法登入(帳號與紀錄都保留),確定?' : '重新啟用這個帳號?' }}
                  </n-popconfirm>
                </n-space>
              </td>
            </tr>
          </tbody>
        </table>
      </n-card>
    </n-space>

    <n-modal v-model:show="createShow" preset="card" title="新增帳號" style="max-width: 460px">
      <n-space vertical>
        <n-text>登入帳號</n-text>
        <n-input v-model:value="form.username" placeholder="例如 chen01" data-testid="acc-new-username" />
        <n-text>名稱(顯示在右上角)</n-text>
        <n-input v-model:value="form.display_name" placeholder="例如 陳組長" data-testid="acc-new-name" />
        <n-text>初始密碼</n-text>
        <n-input
          v-model:value="form.password" type="password" show-password-on="click"
          placeholder="留空使用系統預設密碼(與匯入教師相同)" data-testid="acc-new-password"
        />
        <n-text>身分</n-text>
        <n-checkbox-group v-model:value="form.roles" data-testid="acc-new-roles">
          <n-space>
            <n-checkbox v-for="r in MANAGED_ROLES" :key="r" :value="r" :label="ROLE_LABELS[r]" />
          </n-space>
        </n-checkbox-group>
        <n-text depth="3" style="font-size: 12px">對方第一次登入時,系統會要求他自行設定新密碼。</n-text>
        <n-button type="primary" data-testid="acc-new-save" @click="onCreate">建立</n-button>
      </n-space>
    </n-modal>

    <n-modal v-model:show="rolesShow" preset="card" :title="`設定身分:${target?.username ?? ''}`" style="max-width: 460px">
      <n-space vertical>
        <n-text>名稱</n-text>
        <n-input v-model:value="displayName" data-testid="acc-edit-name" />
        <n-text>身分</n-text>
        <n-checkbox-group v-model:value="roles" data-testid="acc-edit-roles">
          <n-space>
            <n-checkbox v-for="r in MANAGED_ROLES" :key="r" :value="r" :label="ROLE_LABELS[r]" />
          </n-space>
        </n-checkbox-group>
        <n-text v-if="target?.roles.includes('teacher')" depth="3" style="font-size: 12px">
          這個帳號綁定了教師資料({{ target.teacher_names.join('、') }}),「教師」身分會保留,
          仍可查自己的課表、自己請假。
        </n-text>
        <n-text depth="3" style="font-size: 12px">
          教學組長:基礎資料、配課、排課、調代課。教務主任:檢視各項資料、處理調代課(基礎資料與排課的修改由組長操作)。
          系統管理員:全部功能,含備份、系統設定與帳號管理。
        </n-text>
        <n-button type="primary" data-testid="acc-edit-save" @click="onSaveRoles">儲存</n-button>
      </n-space>
    </n-modal>

    <n-modal v-model:show="pwShow" preset="card" :title="`重設密碼:${target?.username ?? ''}`" style="max-width: 420px">
      <n-space vertical>
        <n-input
          v-model:value="newPassword" type="password" show-password-on="click"
          placeholder="留空使用系統預設密碼" data-testid="acc-pw-input"
        />
        <n-text depth="3" style="font-size: 12px">
          重設後對方目前的登入會立即失效,下次登入時要自行設定新密碼。
        </n-text>
        <n-button type="primary" data-testid="acc-pw-save" @click="onResetPassword">重設</n-button>
      </n-space>
    </n-modal>
  </div>
</template>

<style scoped>
.data-table { border-collapse: collapse; width: 100%; }
.data-table th, .data-table td {
  border: 1px solid var(--n-border-color, #e0e0e0); padding: 6px 10px; text-align: left;
}
.data-table th { background: rgba(128, 128, 128, 0.08); font-weight: 600; white-space: nowrap; }
</style>
