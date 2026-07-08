// Excel 匯入 API:範本下載、上傳匯入。

export type ImportEntity = 'subjects' | 'teachers' | 'classes'

export interface ImportResult {
  imported: number
  errors: string[]
}

export const ENTITY_LABELS: Record<ImportEntity, string> = {
  subjects: '科目',
  teachers: '教師',
  classes: '班級',
}

/** 下載範本檔並觸發瀏覽器儲存。 */
export async function downloadTemplate(entity: ImportEntity): Promise<void> {
  const resp = await fetch(`/api/import/templates/${entity}`, { credentials: 'include' })
  if (!resp.ok) throw new Error('範本下載失敗')
  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${entity}_template.xlsx`
  a.click()
  URL.revokeObjectURL(url)
}

/** 上傳 Excel 檔匯入。回傳匯入結果(含錯誤清單)。 */
export async function uploadImport(
  entity: ImportEntity,
  semesterId: number,
  file: File,
  createAccounts = false,
): Promise<ImportResult> {
  const form = new FormData()
  form.append('file', file)
  let url = `/api/import/${entity}?semester_id=${semesterId}`
  if (createAccounts) url += '&create_accounts=true'
  const resp = await fetch(url, { method: 'POST', credentials: 'include', body: form })
  if (!resp.ok) {
    let detail = '匯入失敗'
    try {
      detail = (await resp.json())?.detail ?? detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return resp.json() as Promise<ImportResult>
}
