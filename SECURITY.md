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

- 容器不以 root 執行(api、worker 為 `app`,web 為 `caddy`;啟動時調整 volume 權限後隨即降權)。
- 程式碼不內建任何密碼或金鑰:資料庫密碼由安裝程式隨機產生;沒設管理員密碼時第一次啟動產生臨時密碼;
  沒設 `SECRET_KEY` 時自動產生隨機金鑰。所有帳號首次登入強制改密碼。
- 資料庫與 Redis 不對外開放埠號,只在 Docker 內部網路使用。
- 登入連續失敗 5 次鎖定 15 分鐘(含同時大量送出的情況);session cookie 為 HttpOnly,走 HTTPS 時加上 Secure。
- 寄信加密時驗證郵件伺服器憑證(STARTTLS 或 SMTPS)。
- CI 對前端(`npm audit`)與後端(`pip-audit`)第三方套件做弱點檢查,有中風險以上的已知弱點就不發布映像。
- v1.5.0 依數位發展部公共程式平臺的源碼檢測(Fortify)與第三方元件掃描(Mend)報告完成修補。

---

**English:** Please do not report security issues in public issues. Use GitHub's private vulnerability reporting instead: **Security** tab → **Report a vulnerability** ([direct link](https://github.com/begin0808/Course_Scheduling_System/security/advisories/new)). Only the latest release receives security fixes.
