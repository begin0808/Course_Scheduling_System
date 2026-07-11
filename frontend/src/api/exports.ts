// 課表匯出下載(M5-1)。以 fetch 取回 blob,好處理載入狀態、錯誤與中文檔名。

export type ExportFmt = 'xlsx' | 'pdf' | 'png'
export type ExportView = 'class' | 'teacher' | 'room'

function filenameFrom(cd: string | null, fallback: string): string {
  const m = cd ? /filename\*=UTF-8''([^;]+)/.exec(cd) : null
  return m ? decodeURIComponent(m[1]) : fallback
}

async function download(path: string, fallback: string): Promise<void> {
  const resp = await fetch(`/api${path}`, { credentials: 'include' })
  if (!resp.ok) {
    let detail: string | undefined
    try { detail = (await resp.json())?.detail } catch { detail = undefined }
    throw new Error(detail || `匯出失敗(${resp.status})`)
  }
  const blob = await resp.blob()
  const name = filenameFrom(resp.headers.get('Content-Disposition'), fallback)
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(href)
}

export const exportTimetable = (
  semesterId: number, view: ExportView, targetId: number, fmt: ExportFmt,
): Promise<void> =>
  download(
    `/export/timetable?semester_id=${semesterId}&view=${view}&target_id=${targetId}&fmt=${fmt}`,
    `課表.${fmt}`)

export const exportSchoolWorkbook = (semesterId: number): Promise<void> =>
  download(`/export/school.xlsx?semester_id=${semesterId}`, '全校課表總表.xlsx')

export const exportBatchZip = (semesterId: number): Promise<void> =>
  download(`/export/batch.zip?semester_id=${semesterId}`, '全校班級課表.zip')
