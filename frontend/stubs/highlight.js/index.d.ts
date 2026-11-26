// naive-ui 的 use-hljs.d.ts 只取用 HLJSApi 的 highlight 與 getLanguage 兩個型別。
// 本系統沒有使用程式碼高亮(n-code),所以只需要型別讓 vue-tsc 通過。
export interface HighlightResult {
  value: string
  language?: string
}
export interface HLJSApi {
  highlight(code: string, options: { language: string, ignoreIllegals?: boolean }): HighlightResult
  getLanguage(name: string): object | undefined
}
