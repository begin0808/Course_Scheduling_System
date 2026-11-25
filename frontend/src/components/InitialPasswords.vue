<script setup lang="ts">
/**
 * 系統產生的初始密碼(v1.6.0):建立或重設帳號時密碼留空,系統為每個帳號產生不同的隨機密碼,
 * **只在這一次顯示**(資料庫只存雜湊,之後查不到)。組長在這裡抄下、下載清單或列印通知單發給老師。
 *
 * 先前留空一律用同一組寫在公開原始碼裡的預設密碼,知道帳號的人就能搶先登入。
 */
import { NAlert, NButton, NModal, NSpace, NText, useMessage } from 'naive-ui'

export interface InitialAccount {
  name: string
  username: string
  password: string
}

const props = defineProps<{ accounts: InitialAccount[], title?: string }>()
const show = defineModel<boolean>('show', { required: true })
const message = useMessage()

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string))

async function onCopy() {
  const text = props.accounts.map((a) => `${a.name}\t${a.username}\t${a.password}`).join('\n')
  try {
    await navigator.clipboard.writeText(`姓名\t帳號\t初始密碼\n${text}`)
    message.success('已複製,可以直接貼到 Excel')
  } catch {
    message.error('瀏覽器不允許複製,請改用「下載清單」')
  }
}

function onDownload() {
  // CSV 加 BOM,Excel 直接開啟中文不會亂碼;欄位加引號避免逗號拆欄
  const q = (s: string) => `"${s.replace(/"/g, '""')}"`
  const rows = [['姓名', '帳號', '初始密碼'], ...props.accounts.map((a) => [a.name, a.username, a.password])]
  const csv = '﻿' + rows.map((r) => r.map(q).join(',')).join('\r\n')
  const href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = href
  link.download = '帳號初始密碼.csv'
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(href)
}

function onPrint() {
  const site = esc(window.location.origin)
  const slips = props.accounts.map((a) => `
    <div class="slip">
      <h3>排課與調代課系統 登入帳號</h3>
      <table>
        <tr><th>姓名</th><td>${esc(a.name)}</td></tr>
        <tr><th>帳號</th><td class="mono">${esc(a.username)}</td></tr>
        <tr><th>初始密碼</th><td class="mono">${esc(a.password)}</td></tr>
        <tr><th>登入網址</th><td class="mono">${site}</td></tr>
      </table>
      <p>第一次登入時,系統會要求您設定自己的新密碼。請勿將這張通知單交給他人。</p>
    </div>`).join('')
  const win = window.open('', '_blank')
  if (!win) {
    message.error('瀏覽器擋下了新視窗,請允許彈出視窗後再按一次')
    return
  }
  win.document.write(`<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
    <title>登入帳號通知單</title><style>
    body{font-family:"Microsoft JhengHei","Noto Sans TC",sans-serif;margin:16px}
    .slip{border:1px dashed #888;padding:12px 16px;margin-bottom:12px;page-break-inside:avoid}
    h3{margin:0 0 8px;font-size:16px} table{border-collapse:collapse}
    th{text-align:left;padding:3px 12px 3px 0;font-weight:normal;color:#555;white-space:nowrap}
    td{padding:3px 0;font-size:15px} .mono{font-family:Consolas,monospace;font-size:16px;letter-spacing:1px}
    p{margin:8px 0 0;font-size:13px;color:#333}
    </style></head><body>${slips}</body></html>`)
  win.document.close()
  win.focus()
  win.print()
}
</script>

<template>
  <n-modal
    v-model:show="show" preset="card" :title="title ?? '初始密碼'" style="max-width: 640px"
    :mask-closable="false" :close-on-esc="false" data-testid="initial-passwords"
  >
    <n-space vertical>
      <n-alert type="warning" :show-icon="true">
        密碼由系統為每個帳號隨機產生,<strong>只顯示這一次</strong>,關閉後就查不到了。
        請先下載清單或列印通知單發給本人;忘記了可以再「重設密碼」。對方第一次登入時要設定自己的新密碼。
      </n-alert>
      <div style="max-height: 340px; overflow: auto">
        <table class="pw-table">
          <thead><tr><th>姓名</th><th>帳號</th><th>初始密碼</th></tr></thead>
          <tbody>
            <tr v-for="a in accounts" :key="a.username" data-testid="initial-password-row">
              <td>{{ a.name }}</td>
              <td class="mono">{{ a.username }}</td>
              <td class="mono" data-testid="initial-password">{{ a.password }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <n-space>
        <n-button data-testid="initial-passwords-copy" @click="onCopy">複製</n-button>
        <n-button data-testid="initial-passwords-download" @click="onDownload">下載清單(Excel 可開)</n-button>
        <n-button data-testid="initial-passwords-print" @click="onPrint">列印通知單</n-button>
        <n-button type="primary" data-testid="initial-passwords-close" @click="show = false">
          我已記下,關閉
        </n-button>
      </n-space>
      <n-text depth="3" style="font-size: 12px">
        通知單一人一張,寫有姓名、帳號、初始密碼與登入網址,可裁開發給老師。
      </n-text>
    </n-space>
  </n-modal>
</template>

<style scoped>
.pw-table { border-collapse: collapse; width: 100%; }
.pw-table th, .pw-table td { border-bottom: 1px solid var(--n-border-color, #e5e5e5); padding: 6px 10px; text-align: left; }
.pw-table th { font-weight: normal; color: #666; }
.mono { font-family: Consolas, 'Courier New', monospace; letter-spacing: 1px; }
</style>
