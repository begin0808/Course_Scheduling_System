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
  use_tls: boolean
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

export const saveSmtp = (body: Omit<SmtpSettings, 'configured' | 'has_password'>
  & { password: string }): Promise<SmtpSettings> => apiPut('/settings/smtp', body)
