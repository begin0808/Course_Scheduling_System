# 替代套件(stubs)

這裡的套件透過 `package.json` 的 `overrides` 取代某些間接相依,讓正式網頁與相依清單不含沒用到的程式。

| 套件 | 被誰間接引用 | 為什麼換掉 |
|---|---|---|
| `highlight.js` | naive-ui | naive-ui 只在型別定義(`use-hljs.d.ts`)用到它;本系統沒有使用程式碼高亮元件,建置出的網頁原本也沒打包它。數發部 2026-11 第三方元件掃描標記了 highlight.js 11.11.1 的中風險弱點,換成只含型別的替代套件後就不在相依清單裡(v1.7.0)。 |

日後若真的要用 naive-ui 的程式碼高亮(`n-code`),要先移除這裡的 override、改裝正式版的 highlight.js。
