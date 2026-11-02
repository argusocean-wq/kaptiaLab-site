"""Small, dependency-free locale preferences for Kaptia desktop apps."""
from __future__ import annotations

import json
import os
from pathlib import Path

SUPPORTED = ("zh-TW", "zh-CN", "en", "ja", "ko")
LABELS = {
    "zh-TW": "繁體中文",
    "zh-CN": "简体中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
}


def preference_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Kaptia"
    return root / "user-preferences.json"


def get_language() -> str:
    candidate = os.environ.get("KAPTIA_LANG", "").strip()
    if candidate in SUPPORTED:
        return candidate
    try:
        data = json.loads(preference_path().read_text(encoding="utf-8"))
        candidate = data.get("language", "")
        if candidate in SUPPORTED:
            return candidate
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return "zh-TW"


def set_language(language: str) -> None:
    if language not in SUPPORTED:
        raise ValueError(f"Unsupported Kaptia language: {language}")
    path = preference_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            current = value
    except (OSError, json.JSONDecodeError):
        pass
    current["language"] = language
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


TRANSLATIONS = {
    "language": {"zh-TW":"介面語言", "zh-CN":"界面语言", "en":"Interface language", "ja":"表示言語", "ko":"인터페이스 언어"},
    "overview": {"zh-TW":"總覽", "zh-CN":"总览", "en":"Overview", "ja":"概要", "ko":"개요"},
    "corpus": {"zh-TW":"語料實驗室", "zh-CN":"语料实验室", "en":"Corpus Lab", "ja":"コーパスラボ", "ko":"코퍼스 연구실"},
    "training": {"zh-TW":"訓練實驗室", "zh-CN":"训练实验室", "en":"Training Lab", "ja":"トレーニングラボ", "ko":"학습 연구실"},
    "compute": {"zh-TW":"運算環境", "zh-CN":"计算环境", "en":"Compute", "ja":"計算環境", "ko":"컴퓨팅"},
    "evaluation": {"zh-TW":"評測", "zh-CN":"评测", "en":"Evaluation", "ja":"評価", "ko":"평가"},
    "experiments": {"zh-TW":"實驗紀錄", "zh-CN":"实验记录", "en":"Experiments", "ja":"実験履歴", "ko":"실험 기록"},
    "idle": {"zh-TW":"待命", "zh-CN":"待命", "en":"Ready", "ja":"待機中", "ko":"대기"},
    "refresh": {"zh-TW":"重新整理狀態", "zh-CN":"刷新状态", "en":"Refresh status", "ja":"状態を更新", "ko":"상태 새로고침"},
    "open_chat": {"zh-TW":"開啟本機模型對話", "zh-CN":"打开本地模型对话", "en":"Open local chat", "ja":"ローカルチャットを開く", "ko":"로컬 채팅 열기"},
    "corpus_heading": {"zh-TW":"語料品質與切分", "zh-CN":"语料质量与切分", "en":"Corpus quality and splitting", "ja":"コーパス品質と分割", "ko":"코퍼스 품질 및 분할"},
    "input_path": {"zh-TW":"輸入檔案或資料夾", "zh-CN":"输入文件或文件夹", "en":"Input file or folder", "ja":"入力ファイルまたはフォルダー", "ko":"입력 파일 또는 폴더"},
    "choose_file": {"zh-TW":"選擇檔案", "zh-CN":"选择文件", "en":"Choose file", "ja":"ファイルを選択", "ko":"파일 선택"},
    "choose_folder": {"zh-TW":"選擇資料夾", "zh-CN":"选择文件夹", "en":"Choose folder", "ja":"フォルダーを選択", "ko":"폴더 선택"},
    "prepare_corpus": {"zh-TW":"檢查並準備語料", "zh-CN":"检查并准备语料", "en":"Validate and prepare corpus", "ja":"コーパスを検証・準備", "ko":"코퍼스 검사 및 준비"},
    "training_heading": {"zh-TW":"可續訓的 scratch 實驗", "zh-CN":"可续训的 scratch 实验", "en":"Resumable scratch training", "ja":"再開可能なスクラッチ学習", "ko":"재개 가능한 스크래치 학습"},
    "additional_steps": {"zh-TW":"追加步數", "zh-CN":"追加步数", "en":"Additional steps", "ja":"追加ステップ", "ko":"추가 단계"},
    "eval_interval": {"zh-TW":"評測間隔", "zh-CN":"评测间隔", "en":"Evaluation interval", "ja":"評価間隔", "ko":"평가 간격"},
    "device": {"zh-TW":"裝置", "zh-CN":"设备", "en":"Device", "ja":"デバイス", "ko":"장치"},
    "start_training": {"zh-TW":"開始 / 繼續訓練", "zh-CN":"开始 / 继续训练", "en":"Start / resume training", "ja":"学習を開始 / 再開", "ko":"학습 시작 / 재개"},
    "compute_heading": {"zh-TW":"本機資源檢查", "zh-CN":"本地资源检查", "en":"Local resource diagnostics", "ja":"ローカルリソース診断", "ko":"로컬 리소스 진단"},
    "rescan": {"zh-TW":"重新檢查硬體", "zh-CN":"重新检查硬件", "en":"Rescan hardware", "ja":"ハードウェアを再確認", "ko":"하드웨어 다시 검사"},
    "evaluation_heading": {"zh-TW":"評測結果與生成抽查", "zh-CN":"评测结果与生成抽查", "en":"Evaluation and generation spot-check", "ja":"評価と生成スポットチェック", "ko":"평가 및 생성 표본 검사"},
    "read_metrics": {"zh-TW":"讀取訓練指標", "zh-CN":"读取训练指标", "en":"Read training metrics", "ja":"学習指標を読み込む", "ko":"학습 지표 읽기"},
    "generation_check": {"zh-TW":"執行生成抽查", "zh-CN":"执行生成抽查", "en":"Run generation check", "ja":"生成チェックを実行", "ko":"생성 검사 실행"},
    "experiment_heading": {"zh-TW":"實驗沿革", "zh-CN":"实验记录", "en":"Experiment history", "ja":"実験履歴", "ko":"실험 기록"},
    "reload_records": {"zh-TW":"重新讀取紀錄", "zh-CN":"重新读取记录", "en":"Reload records", "ja":"記録を再読み込み", "ko":"기록 다시 불러오기"},
}


def tr(key: str, language: str | None = None) -> str:
    language = language or get_language()
    values = TRANSLATIONS.get(key, {})
    return values.get(language, values.get("zh-TW", key))
