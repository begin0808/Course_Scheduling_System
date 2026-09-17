// 系統版本與新版本提醒(v1.2.3)。

import { apiGet } from '@/api/client'

export interface UpdateStatus {
  enabled: boolean // false = 管理者在 .env 關閉了新版本檢查
  current: string // 目前版本,如 v1.2.3;自行從原始碼建置為 dev
  latest: string
  latest_url: string
  published_at: string
  checked_at: string
  update_available: boolean
  error: string // 最近一次查詢失敗的原因(例如主機不能連外)
}

export const RELEASES_URL = 'https://github.com/begin0808/Course_Scheduling_System/releases'
export const UPGRADE_GUIDE_URL =
  'https://github.com/begin0808/Course_Scheduling_System/blob/main/docs/deploy/upgrade.md'

export const getVersion = (): Promise<{ version: string }> => apiGet('/system/version')

/** 管理員專用。refresh = 「立即檢查」(後端限制至少間隔一分鐘) */
export const getUpdateStatus = (refresh = false): Promise<UpdateStatus> =>
  apiGet(`/system/update${refresh ? '?refresh=true' : ''}`)
