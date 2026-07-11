// 資料庫備份與還原(M5-2,管理員專用)。

import { apiDelete, apiGet, apiPost } from '@/api/client'

export interface Backup {
  name: string
  size_bytes: number
  created_at: string
  reason: string
  reason_label: string
}

export interface RestoreResult {
  restored_from: string
  presafe_backup: string
}

export const listBackups = (): Promise<Backup[]> => apiGet('/backups')
export const createBackup = (): Promise<Backup> => apiPost('/backups')
export const deleteBackup = (name: string): Promise<{ deleted: string }> =>
  apiDelete(`/backups/${encodeURIComponent(name)}`)
export const restoreBackup = (name: string): Promise<RestoreResult> =>
  apiPost(`/backups/${encodeURIComponent(name)}/restore`)

export async function restoreUpload(file: File): Promise<RestoreResult> {
  const fd = new FormData()
  fd.append('file', file)
  const resp = await fetch('/api/backups/restore-upload',
    { method: 'POST', credentials: 'include', body: fd })
  if (!resp.ok) {
    let detail: string | undefined
    try { detail = (await resp.json())?.detail } catch { detail = undefined }
    throw new Error(detail || `還原失敗(${resp.status})`)
  }
  return resp.json()
}

export async function downloadBackup(name: string): Promise<void> {
  const resp = await fetch(`/api/backups/${encodeURIComponent(name)}/download`,
    { credentials: 'include' })
  if (!resp.ok) throw new Error(`下載失敗(${resp.status})`)
  const blob = await resp.blob()
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(href)
}
