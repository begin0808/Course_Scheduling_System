// 系統版本與新版本提醒(v1.2.3)。

import { apiGet, apiPost } from '@/api/client'

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

// 原始碼位置(v1.4.1 起 AGPL-3.0):登入頁與側邊欄的「原始碼」連結指向這裡。
// AGPL 第 13 條要求透過網路提供服務時,要讓使用者拿得到原始碼;
// 改過程式再提供給別人使用的人,要把這裡改成自己改過的原始碼位置。
export const SOURCE_URL = 'https://github.com/begin0808/Course_Scheduling_System'
export const RELEASES_URL = 'https://github.com/begin0808/Course_Scheduling_System/releases'
export const UPGRADE_GUIDE_URL =
  'https://github.com/begin0808/Course_Scheduling_System/blob/main/docs/deploy/upgrade.md'

export const getVersion = (): Promise<{ version: string }> => apiGet('/system/version')

/** 管理員專用。refresh = 「立即檢查」(後端限制至少間隔一分鐘) */
/** 資料表結構升級後的一次性提示(v1.3.0):升級前自動備份的檔名,或備份失敗的原因 */
export interface UpgradeNotice {
  version: string
  at: string
  backup: string
  error: string
}
export const getUpgradeNotice = (): Promise<UpgradeNotice | null> => apiGet('/system/upgrade-notice')
export const dismissUpgradeNotice = (): Promise<void> => apiPost('/system/upgrade-notice/dismiss')

export const getUpdateStatus = (refresh = false): Promise<UpdateStatus> =>
  apiGet(`/system/update${refresh ? '?refresh=true' : ''}`)
