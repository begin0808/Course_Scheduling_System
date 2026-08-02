<script setup lang="ts">
import {
  NAlert, NButton, NCard, NCheckbox, NInput, NInputNumber, NPopconfirm, NSpace, NTag, NText,
  NUpload,
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
import {
  demoDataStatus, getSchedulingSettings, getSchoolSettings, loadDemoData,
  saveSchedulingSettings, saveSchoolSettings,
} from '@/api/assignments'
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

const maxOvertime = ref(8)
const savingScheduling = ref(false)

const schoolName = ref('')
const savingSchool = ref(false)

async function onSaveSchool() {
  if (!schoolName.value.trim()) { message.warning('請輸入校名'); return }
  savingSchool.value = true
  try {
    schoolName.value = (await saveSchoolSettings({ school_name: schoolName.value })).school_name
    message.success('已更新校名')
  } catch (e) {
    message.error((e as ApiError).message || '儲存失敗')
  } finally {
    savingSchool.value = false
  }
}

onMounted(async () => {
  if (!isAdmin()) return
  const s = await getSmtp()
  smtp.value = { host: s.host, port: s.port, user: s.user, password: '', sender: s.sender, use_tls: s.use_tls }
  configured.value = s.configured
  hasPassword.value = s.has_password
  maxOvertime.value = (await getSchedulingSettings()).max_overtime
  schoolName.value = (await getSchoolSettings()).school_name
  const demo = await demoDataStatus()
  demoAvailable.value = demo.available
  demoReason.value = demo.reason
  demoSchool.value = demo.school_name
  await reloadBackups()
})

// ── 示範資料 ──
const demoAvailable = ref(false)
const demoReason = ref('')
const demoSchool = ref('')
const loadingDemo = ref(false)

async function onLoadDemo() {
  loadingDemo.value = true
  try {
    const r = await loadDemoData()
    schoolName.value = r.school_name
    demoAvailable.value = false
    demoReason.value = '示範資料已載入。'
    message.success(
      `已建立 ${r.classes} 班、${r.teachers} 位教師、${r.assignments} 筆配課`
      + `(共 ${r.total_periods} 節)。可以到「自動排課」試跑了。`,
      { duration: 8000 },
    )
  } catch (e) {
    message.error((e as ApiError).message || '載入失敗')
  } finally {
    loadingDemo.value = false
  }
}

async function onSaveScheduling() {
  savingScheduling.value = true
  try {
    const s = await saveSchedulingSettings({ max_overtime: maxOvertime.value })
    maxOvertime.value = s.max_overtime
    message.success('已儲存排課設定')
  } catch (e) {
    message.error((e as ApiError).message || '儲存失敗')
  } finally {
    savingScheduling.value = false
  }
}

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

    <n-card v-if="isAdmin()" title="學校資訊" data-testid="school-card">
      <n-space vertical>
        <n-text depth="3">
          校名會顯示在介面、匯出的課表(Excel / PDF / PNG)、代課通知信與 A4 公告單上。
          改完立即生效,不需重新啟動。
        </n-text>
        <n-space align="center">
          <n-text style="width: 72px">校名</n-text>
          <n-input
            v-model:value="schoolName" placeholder="如:臺南市市立敦品國中"
            style="width: 280px" data-testid="school-name"
          />
          <n-button
            type="primary" :loading="savingSchool" data-testid="school-save"
            @click="onSaveSchool"
          >
            儲存
          </n-button>
        </n-space>
      </n-space>
    </n-card>

    <n-card v-if="isAdmin() && demoAvailable" title="示範資料" data-testid="demo-card">
      <n-space vertical>
        <n-text depth="3">
          一鍵建立一所完整的示範國中「{{ demoSchool || '示範國中' }}」,讓你不必先手 key
          資料就能試用全部功能:三個年級共 18 班(701~706、801~806、901~906)、
          48 位教師(含導師、兼行政、外聘)、24 個分科科目、384 筆配課,
          以及專科教室與場地。建好後可直接到「自動排課」試跑。
        </n-text>
        <n-alert type="warning" :show-icon="false">
          僅限「全新、尚未建立任何學期」的系統。示範資料是虛構的,
          <strong>請勿在正式使用的系統上載入</strong>。
        </n-alert>
        <div>
          <n-button
            type="primary" :loading="loadingDemo"
            data-testid="demo-load" @click="onLoadDemo"
          >
            載入示範資料
          </n-button>
        </div>
      </n-space>
    </n-card>

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

    <n-card v-if="isAdmin()" title="排課設定" data-testid="scheduling-card">
      <n-space vertical>
        <n-text depth="3">
          超鐘點上限依各縣市/各校規定自訂。上限是「應授節數 + N」——應授本身因身分而異
          (例:臺南市國文科專任 16 節、兼任導師 11 節、兼任主任 6 節),固定值對誰都不合適。
        </n-text>
        <n-space align="center">
          <span>超鐘點上限</span>
          <n-input-number
            v-model:value="maxOvertime" :min="0" :max="20" style="width: 120px"
            data-testid="max-overtime"
          />
          <n-text depth="3">節(0 = 不限制)</n-text>
        </n-space>
        <n-text depth="3" style="font-size: 12px">
          超過上限的配課會被擋下。未填「基本鐘點」的教師不受此限——那代表資料尚未建立,
          而非真的不用上課。
        </n-text>
        <div>
          <n-button
            type="primary" :loading="savingScheduling" data-testid="scheduling-save"
            @click="onSaveScheduling"
          >
            儲存排課設定
          </n-button>
        </div>
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
