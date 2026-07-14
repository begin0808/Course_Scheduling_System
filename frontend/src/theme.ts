import type { GlobalThemeOverrides } from 'naive-ui'

// 主色調深至白字對比 ≥ 4.5:1(WCAG AA 正常文字,1.4.3)。
//
// Naive 預設的 #18a058 配白字只有 ~3.4:1——那只達到 1.4.11「非文字元件」的 3:1 底線,
// 而按鈕上的字就是文字。這裡把主色壓深到通過 AA,色相不動(仍是同一支綠),
// 整體設計不受影響。hover 是使用者實際會停在上面讀字的狀態,同樣要達標。
//
//   #0d7a43 → 5.41:1(預設)
//   #0e8449 → 4.76:1(hover;比預設亮一階但仍達 AA)
//   #0a6337 → 7.0:1 (pressed)
export const PRIMARY = '#0d7a43'
export const PRIMARY_HOVER = '#0e8449'
export const PRIMARY_PRESSED = '#0a6337'

export const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: PRIMARY,
    primaryColorHover: PRIMARY_HOVER,
    primaryColorPressed: PRIMARY_PRESSED,
    primaryColorSuppl: PRIMARY_HOVER,
  },
}
