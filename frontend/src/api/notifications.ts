// 通知:教師端鈴鐺/確認,組長看板/再次提醒(M4-3)。

import { apiGet, apiPost, apiPut } from '@/api/client'

export interface Notification {
  id: number
  type: string
  title: string
  body: string
  link: string
  created_at: string
  read_at: string | null
  acknowledged_at: string | null
}

export interface NotificationList {
  items: Notification[]
  unread: number
}

export interface BoardEntry {
  id: number
  type: string
  title: string
  teacher_id: number | null
  teacher_name: string
  created_at: string
  read_at: string | null
  acknowledged_at: string | null
}

export interface SmtpSettings {
  host: string
  port: number
  user: string
  sender: string
  configured: boolean
  has_password: boolean
}

export const myNotifications = (semesterId: number): Promise<NotificationList> =>
  apiGet(`/notifications/mine?semester_id=${semesterId}`)

export const myUnreadCount = (semesterId: number): Promise<{ unread: number }> =>
  apiGet(`/notifications/mine/unread-count?semester_id=${semesterId}`)

export const markRead = (id: number): Promise<Notification> =>
  apiPost(`/notifications/${id}/read`)

export const acknowledge = (id: number): Promise<Notification> =>
  apiPost(`/notifications/${id}/acknowledge`)

export const notificationBoard = (
  semesterId: number,
  opts: { unacknowledgedOnly?: boolean } = {},
): Promise<BoardEntry[]> =>
  apiGet(`/notifications?semester_id=${semesterId}`
    + (opts.unacknowledgedOnly ? '&unacknowledged_only=true' : ''))

export const remind = (id: number): Promise<Notification> =>
  apiPost(`/notifications/${id}/remind`)

export const getSmtp = (): Promise<SmtpSettings> => apiGet('/settings/smtp')

// 密碼沒填(null)就不送,後端沿用已存的密碼
export const saveSmtp = ({ password, ...rest }: Omit<SmtpSettings, 'configured' | 'has_password'>
  & { password: string | null }): Promise<SmtpSettings> =>
  apiPut('/settings/smtp', password ? { ...rest, password } : rest)

/** 用已儲存的 SMTP 設定寄一封測試信;失敗時錯誤訊息會寫出可能原因(v1.5.1)。 */
export const testSmtp = (to: string): Promise<{ sent: boolean, to: string }> =>
  apiPost('/settings/smtp/test', { to })
