# KaptiaLab

KaptiaLab 是以 Windows 桌面為主要目標的本機 AI 助手專案。此倉庫同時包含產品官網與完整應用程式原始碼。

## 專案結構

- `/`：KaptiaLab 官方網站（GitHub Pages）。
- `/app/`：桌面應用程式、安裝器、CLI、Attach、Cloud Compute、VS Code 擴充、測試與技術文件。
- `/.github/workflows/`：官網部署與網站驗證工作流程。

## 開發狀態

原始碼已匯入公開倉庫；這不代表所有功能都已完成或經過正式環境驗證。請以 `app/docs/`、測試結果與 GitHub Actions 執行狀態為準。Cloud Compute Worker 需要自行部署到具備 Docker 的主機；本倉庫不會替使用者建立雲端主機或代付運算費用。

## 安裝與執行

請先閱讀 [應用程式說明](app/README.md) 及 [安裝器文件](app/docs/UPTP.md)。尚未有經本次遷移驗證的新版 Setup.exe 時，請勿將舊版安裝檔視為本分支的建置產物。

## 開源授權

本專案程式碼採 MIT License，詳見 [LICENSE](LICENSE)。第三方套件、模型權重及外部資料仍受其各自授權條款約束；本倉庫的 MIT 授權不會改變第三方資產的授權。