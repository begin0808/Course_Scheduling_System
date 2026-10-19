// 帳號與角色管理(v1.3.1,限系統管理員)。

import { apiGet, apiPost, apiPut, request } from '@/api/client'

/** 可在帳號管理指派的角色;教師身分由教師資料的登入帳號決定 */
export type ManagedRole = 'scheduler' | 'director' | 'admin'
export const ROLE_LABELS: Record<string, string> = {
  admin: '系統管理員',
  director: '教務主任',
  scheduler: '教學組長',
  teacher: '教師',
}
export const MANAGED_ROLES: ManagedRole[] = ['scheduler', 'director', 'admin']

export interface UserAccount {
  id: number
  username: string
  display_name: string
  roles: string[]
  is_active: boolean
  must_change_password: boolean
  teacher_names: string[]
}

export const listUsers = () => apiGet<UserAccount[]>('/users')
export const createUser = (body: {
  username: string; display_name: string; password: string; roles: ManagedRole[]
}) => apiPost<UserAccount>('/users', body)
export const setUserRoles = (id: number, roles: ManagedRole[]) =>
  apiPut<UserAccount>(`/users/${id}/roles`, { roles })
export const renameUser = (id: number, displayName: string) =>
  request<UserAccount>('PATCH', `/users/${id}`, { display_name: displayName })
export const resetUserPassword = (id: number, password: string) =>
  apiPost<UserAccount>(`/users/${id}/reset-password`, { password })
export const setUserActive = (id: number, isActive: boolean) =>
  apiPost<UserAccount>(`/users/${id}/active`, { is_active: isActive })
