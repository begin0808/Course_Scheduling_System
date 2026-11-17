// 停課日頁的文字與年級分組(v1.4.19)

import { TRACK_LABELS } from '@/api/basedata'
import type { ClassUnit } from '@/api/basedata'

const DIGITS = '零一二三四五六七八九十'

export interface GradeGroup {
  key: string
  label: string // 「七年級」;國中小並存時「國中七年級」
  classes: ClassUnit[]
}

/** 班級依學制、年級分組(畫面上一次勾整個年級);年級小的在前。 */
export function gradeGroups(classes: ClassUnit[]): GradeGroup[] {
  const tracks = new Set(classes.map((c) => c.track))
  const map = new Map<string, GradeGroup>()
  const sorted = [...classes].sort((a, b) => a.grade - b.grade || a.name.localeCompare(b.name))
  for (const c of sorted) {
    const key = `${c.track}-${c.grade}`
    if (!map.has(key)) {
      const grade = c.grade >= 0 && c.grade <= 10 ? DIGITS[c.grade] : String(c.grade)
      const prefix = tracks.size > 1 ? TRACK_LABELS[c.track] ?? '' : ''
      map.set(key, { key, label: `${prefix}${grade}年級`, classes: [] })
    }
    map.get(key)!.classes.push(c)
  }
  return [...map.values()]
}

function md(iso: string): string {
  const [, m, d] = iso.split('-').map(Number)
  return `${m}/${d}`
}

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']

/** 「11/20(五)」或「11/20(五)~11/24(二)」 */
export function dateRangeText(start: string, end: string): string {
  const one = (iso: string) => {
    const [y, m, d] = iso.split('-').map(Number)
    return `${md(iso)}(${WEEKDAYS[new Date(y, m - 1, d).getDay()]})`
  }
  return start === end ? one(start) : `${one(start)}~${one(end)}`
}
