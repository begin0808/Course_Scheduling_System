// 簡易 API client。所有請求帶 cookie(credentials: include)以維持 session。

export interface ApiError extends Error {
  status: number
  detail?: string
}

// 全域 401 處理器(由 main.ts 註冊):session 過期/被撤銷時清除登入狀態並導回登入頁。
// 認證管理端點(/auth/*)的 401 由呼叫端自行處理,不觸發全域導向,避免重導迴圈。
let unauthorizedHandler: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void): void {
  unauthorizedHandler = fn
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!resp.ok) {
    let detail: string | undefined
    try {
      detail = (await resp.json())?.detail
    } catch {
      detail = undefined
    }
    if (resp.status === 401 && !path.startsWith('/auth/')) {
      unauthorizedHandler?.()
    }
    const err = new Error(detail || `API 錯誤 ${resp.status}`) as ApiError
    err.status = resp.status
    err.detail = detail
    throw err
  }
  if (resp.status === 204) return undefined as T
  return resp.json() as Promise<T>
}

export const apiGet = <T>(path: string): Promise<T> => request<T>('GET', path)
export const apiPost = <T>(path: string, body?: unknown): Promise<T> =>
  request<T>('POST', path, body)
export const apiPut = <T>(path: string, body?: unknown): Promise<T> =>
  request<T>('PUT', path, body)
