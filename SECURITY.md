# 資安政策 Security Policy

## 支援的版本

只有**最新發行版**會收到資安修正。請先確認問題在最新版仍然存在([Releases](https://github.com/begin0808/Course_Scheduling_System/releases))。

## 回報資安問題

**請不要在公開的 issue 回報資安問題。** 公開之後,還沒升級的學校就暴露在風險中。

請改用 GitHub 的私下通報:到本專案的 **Security** 分頁 → **Report a vulnerability**([直接連結](https://github.com/begin0808/Course_Scheduling_System/security/advisories/new))。只有維護者看得到。

回報時請盡量附上:

- 受影響的版本
- 重現步驟(指令、請求內容)
- 可能的影響

## 處理方式

- 收到後會盡快回覆,確認問題並評估影響。
- 修正後發布新版,並在 CHANGELOG 與 Release 說明修了什麼;回報者願意的話會列名致謝。
- 修正發布、學校有時間升級之後,才公開細節。

## 安全設計

- 容器不以 root 執行:映像以 `USER` 指定一般使用者(api、worker 為 `app`,web 為 `caddy`),容器一啟動就沒有 root 權限(v1.7.0)。
- 系統套件釘選版本(Debian 套件寫明版本號),每次建置裝到的都相同(v1.7.0)。
- 程式碼不內建任何密碼或金鑰:資料庫密碼由安裝程式隨機產生;沒設管理員密碼時,第一次啟動以沒人知道的隨機密碼建立帳號,
  再由主機管理者用重設指令自己輸入密碼,密碼不會出現在畫面或紀錄裡(v1.7.0);
  沒設 `SECRET_KEY` 時自動產生隨機金鑰。沒有共用的帳號預設密碼:建立或重設帳號時密碼留空,為每個帳號產生不同的
  隨機初始密碼,只顯示一次(v1.6.0)。系統產生的密碼在首次登入時強制更改。
- 資料庫與 Redis 不對外開放埠號,只在 Docker 內部網路使用。
- 登入連續失敗 5 次鎖定 15 分鐘(含同時大量送出的情況);session cookie 為 HttpOnly,走 HTTPS 時加上 Secure。
- 寄信一律加密(STARTTLS 或 SMTPS)並驗證郵件伺服器憑證,不提供明文寄送(v1.6.0)。
- CI 對前端(`npm audit`)與後端(`pip-audit`)第三方套件做弱點檢查,有中風險以上的已知弱點就不發布映像。
- v1.5.0、v1.6.0、v1.7.0、v1.7.1 依數位發展部公共程式平臺的源碼檢測(Fortify)與第三方元件掃描(Mend)報告完成修補。
  檢測用的程式碼壓縮檔(排除測試與開發工具,附排除清單)可用 `python scripts/make_scan_bundle.py <版本>` 產生,
  也附在每個版本的 GitHub Release。

---

**English:** Please do not report security issues in public issues. Use GitHub's private vulnerability reporting instead: **Security** tab → **Report a vulnerability** ([direct link](https://github.com/begin0808/Course_Scheduling_System/security/advisories/new)). Only the latest release receives security fixes.
