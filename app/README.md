# KaptiaLab Desktop Application

此目錄包含 KaptiaLab 桌面應用程式與相關開發資產。

## 主要模組

- `installer/`：Windows 安裝器與硬體環境偵測。
- `scripts/`：對話執行環境、記憶、工具、CLI、更新、Attach 與 Cloud Compute。
- `cloud_worker/`：可自行部署的遠端運算 Worker。
- `kaptia_packaging/`：安裝封裝協定。
- `ui/web/`：桌面應用程式 WebView 介面。
- `vscode-extension/`：VS Code 擴充功能。
- `tests/`、`scripts/test_*.py`：自動化測試。
- `docs/`：架構、功能與部署文件。

## 開發環境

主要程式使用 Python。請依功能安裝對應的 requirements 檔案，並參考各模組文件。Windows 安裝器建置工作流程與官網 Pages 工作流程分開管理。

## 模型與第三方資產

本倉庫提供應用程式程式碼，不包含模型權重。模型權重、第三方套件及外部服務均依其上游授權與服務條款使用。若設定外部 API，對話資料會依該服務商的政策傳輸與處理。

## 安全注意事項

- 不要提交 API Token、私鑰、`.env`、使用者對話資料、模型權重或本機快取。
- 使用 Cloud Compute 前，請先閱讀 `docs/CLOUD_COMPUTE.md`，並在受信任的主機上自行部署 Worker。
- Attach 與本機工具應採最小權限；操作桌面應用程式前應取得使用者明確授權。
- 本次公開遷移不包含舊核心倉庫的 Git 歷史。