<script setup lang="ts">
import {
  NButton, NCard, NCheckbox, NInput, NInputNumber, NPopconfirm, NSpace, NTag, NText, NUpload,
  useDialog, useMessage,
} from 'naive-ui'
import type { UploadCustomRequestOptions } from 'naive-ui'
import { h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import {
  createBackup, deleteBackup, downloadBackup, listBackups, restoreBackup, restoreUpload,
} from '@/api/backups'
import type { Backup, RestoreResult } from '@/api/backups'
import { getSmtp, saveSmtp } from '@/api/notifications'
import { resetWizard } from '@/api/wizard'
import { useAuthStore } from '@/stores/auth'
import { useWizardStore } from '@/stores/wizard'

const router = useRouter()
const message = useMessage()
const dialog = useDialog()
const wizard = useWizardStore()
const auth = useAuthStore()

const isAdmin = () => auth.hasRole('admin')

// ── 備份與還原 ──
const backups = ref<Backup[]>([])
const busy = ref(false)

function humanSize(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

async function reloadBackups() {
  if (!isAdmin()) return
  backups.value = await listBackups()
}

async function onCreateBackup() {
  busy.value = true
  try {
    await createBackup()
    message.success('已建立備份')
    await reloadBackups()
  } catch (e) {
    message.error((e as ApiError).message || '備份失敗')
  } finally {
    busy.value = false
  }
}

async function onDeleteBackup(name: string) {
  await deleteBackup(name)
  message.success('已刪除備份')
  await reloadBackups()
}

async function redirectToLogin() {
  await auth.logout().catch(() => {})
  router.push({ name: 'login' })
}

async function afterRestore(r: RestoreResult) {
  // 還原後所有 session 已失效,需重新登入。若有可忽略的警告,先以對話框讓管理員看見
  // (訊息在導向登入頁後會消失,警告不能只用一閃即逝的 toast)。
  if (r.warnings.length > 0) {
    dialog.warning({
      title: '還原完成,但有可忽略的警告',
      content: () => h('div', [
        h('p', `現狀已備份為 ${r.presafe_backup}。以下警告不影響資料,通常為跨版本的設定參數:`),
        ...r.warnings.map((w) => h('p', { style: 'font-size:12px;color:#999;margin:4px 0' }, w)),
      ]),
      positiveText: '知道了,重新登入',
      maskClosable: false,
      onPositiveClick: redirectToLogin,
      onClose: redirectToLogin,
    })
    return
  }
  message.success(`還原完成(現狀已備份為 ${r.presafe_backup}),請重新登入`)
  await redirectToLogin()
}

async function onRestore(name: string) {
  busy.value = true
  try {
    const r = await restoreBackup(name)
    await afterRestore(r)
  } catch (e) {
    message.error((e as ApiError).message || '還原失敗')
  } finally {
    busy.value = false
  }
}

async function onUploadRestore({ file, onFinish, onError }: UploadCustomRequestOptions) {
  busy.value = true
  try {
    const r = await restoreUpload(file.file as File)
    onFinish()
    await afterRestore(r)
  } catch (e) {
    onError()
    message.error((e as Error).message || '上傳還原失敗')
  } finally {
    busy.value = false
  }
}

const smtp = ref({
  host: '', port: 25, user: '', password: '', sender: '', use_tls: false,
})
const configured = ref(false)
const hasPassword = ref(false)
const savingSmtp = ref(false)

onMounted(async () => {
  if (!isAdmin()) return
  const s = await getSmtp()
  smtp.value = { host: s.host, port: s.port, user: s.user, password: '', sender: s.sender, use_tls: s.use_tls }
  configured.value = s.configured
  hasPassword.value = s.has_password
  await reloadBackups()
})

async function onSaveSmtp() {
  savingSmtp.value = true
  try {
    const s = await saveSmtp(smtp.value)
    configured.value = s.configured
    hasPassword.value = s.has_password
    smtp.value.password = ''
    message.success('已儲存 SMTP 設定')
  } catch (e) {
    message.error((e as ApiError).message || '儲存失敗')
  } finally {
    savingSmtp.value = false
  }
}

async function onResetWizard() {
  await resetWizard()
  await wizard.fetch()
  message.success('已重新啟動設定精靈')
  router.push({ name: 'wizard' })
}
</script>

<template>
  <n-space vertical size="large">
    <h1 style="margin: 0">系統管理</h1>

    <n-card v-if="isAdmin()" title="通知信件(SMTP)" data-testid="smtp-card">
      <n-space vertical>
        <n-space align="center">
          <n-text depth="3">
            設定後,調代課通知除站內外會加寄 Email;未設定時系統照常運作,僅站內通知。
          </n-text>
          <n-tag :type="configured ? 'success' : 'default'" data-testid="smtp-status">
            {{ configured ? '已設定' : '未設定' }}
          </n-tag>
        </n-space>
        <n-space align="center" :wrap="true">
          <n-text style="width: 72px">主機</n-text>
          <n-input
            v-model:value="smtp.host" placeholder="smtp.example.com" style="width: 220px"
            data-testid="smtp-host"
          />
          <n-text>連接埠</n-text>
          <n-input-number v-model:value="smtp.port" :min="1" :max="65535" style="width: 110px" />
          <n-checkbox v-model:checked="smtp.use_tls">使用 TLS</n-checkbox>
        </n-space>
        <n-space align="center" :wrap="true">
          <n-text style="width: 72px">寄件人</n-text>
          <n-input
            v-model:value="smtp.sender" placeholder="noreply@school.edu.tw"
            style="width: 220px" data-testid="smtp-sender"
          />
          <n-text>帳號</n-text>
          <n-input v-model:value="smtp.user" placeholder="(選填)" style="width: 160px" />
          <n-text>密碼</n-text>
          <n-input
            v-model:value="smtp.password" type="password"
            :placeholder="hasPassword ? '(已設定,留空不變更)' : '(選填)'" style="width: 160px"
          />
        </n-space>
        <div>
          <n-button
            type="primary" :loading="savingSmtp" data-testid="smtp-save" @click="onSaveSmtp"
          >
            儲存 SMTP 設定
          </n-button>
        </div>
      </n-space>
    </n-card>

    <n-card v-if="isAdmin()" title="資料備份與還原" data-testid="backup-card">
      <n-space vertical>
        <n-space align="center">
          <n-text depth="3">
            每日凌晨自動備份(保留 30 份);也可立即備份、下載保存,或上傳備份檔還原。
            還原前系統會自動先備份現狀,還原後所有人需重新登入。
          </n-text>
        </n-space>
        <n-space align="center">
          <n-button
            type="primary" :loading="busy" data-testid="backup-now" @click="onCreateBackup"
          >
            立即備份
          </n-button>
          <n-upload
            :custom-request="onUploadRestore" :show-file-list="false" accept=".dump"
            :disabled="busy"
          >
            <n-button :disabled="busy" data-testid="backup-upload">上傳備份檔並還原</n-button>
          </n-upload>
        </n-space>

        <n-text v-if="!backups.length" depth="3">尚無備份。</n-text>
        <table v-else class="data-table" data-testid="backup-table">
          <thead>
            <tr><th>時間</th><th>來源</th><th>大小</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="b in backups" :key="b.name" data-testid="backup-row">
              <td>{{ new Date(b.created_at).toLocaleString('zh-TW', { hour12: false }) }}</td>
              <td><n-tag size="small">{{ b.reason_label }}</n-tag></td>
              <td>{{ humanSize(b.size_bytes) }}</td>
              <td>
                <n-space size="small">
                  <n-button size="tiny" @click="downloadBackup(b.name)">下載</n-button>
                  <n-popconfirm @positive-click="() => onRestore(b.name)">
                    <template #trigger>
                      <n-button size="tiny" type="warning" data-testid="backup-restore">
                        還原
                      </n-button>
                    </template>
                    還原將覆蓋目前所有資料(現狀會先自動備份),確定?
                  </n-popconfirm>
                  <n-popconfirm @positive-click="() => onDeleteBackup(b.name)">
                    <template #trigger>
                      <n-button size="tiny" tertiary>刪除</n-button>
                    </template>
                    確定刪除此備份?
                  </n-popconfirm>
                </n-space>
              </td>
            </tr>
          </tbody>
        </table>
      </n-space>
    </n-card>

    <n-card title="設定精靈">
      <n-space vertical>
        <n-text depth="3">重新執行首次設定的引導流程(不會刪除既有資料)。</n-text>
        <n-popconfirm @positive-click="onResetWizard">
          <template #trigger>
            <n-button>重新啟動設定精靈</n-button>
          </template>
          確定重新啟動設定精靈?
        </n-popconfirm>
      </n-space>
    </n-card>
  </n-space>
</template>

<style scoped>
.data-table { border-collapse: collapse; width: 100%; }
.data-table th, .data-table td {
  border: 1px solid var(--n-border-color, #e0e0e0); padding: 6px 10px; text-align: left;
}
.data-table th { background: rgba(128, 128, 128, 0.08); font-weight: 600; }
</style>
