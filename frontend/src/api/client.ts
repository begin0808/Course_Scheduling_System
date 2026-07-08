// 簡易 API client。所有請求帶 cookie(credentials: include)以維持 session。

export interface ApiError extends Error {
  status: number
  detail?: string
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
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
