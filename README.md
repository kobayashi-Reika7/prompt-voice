# prompt_voice

Windows向けのローカル音声入力CLIツールです。  
マイク入力を取り込み、発話区間を検知し、ローカル音声認識で文字起こしした結果を整形してクリップボードへコピーします。

superwhisperのような「話してすぐ使える」体験を参考にしつつ、ブランドやUIを模倣せず、ローカルで長時間使える実装を目指したMVPです。

## 1. プロジェクト概要

このツールは以下の流れをCLIで実現します。

1. マイク音声を連続取得
2. 発話区間をVADで検知
3. 発話終了ごとにローカル文字起こし
4. 用途別モードでテキスト整形
5. クリップボードへコピー

対象OSはWindows、実装言語はPythonです。

## 2. 主な特徴

- ローカル音声認識（`faster-whisper`）
- 発話区間検知（`silero-vad`）
- マイク連続入力（`sounddevice`）
- partialリアルタイム認識（Whisperベース）
- Push-to-talk（`Ctrl+Space` 長押し）
- CLIベースで軽量に運用可能
- 整形モード（`raw` / `clean` / `cursor` / `minutes`）
- 最終結果のクリップボードコピー（`pyperclip`）
- 自動貼り付け（`Ctrl+V` 送信）
- 履歴保存（`logs/history.json`）
- `Ctrl+C` で安全停止（録音停止時に末尾バッファをflush）

## 3. ディレクトリ構成

```text
prompt_voice/
├─ main.py          # CLI エントリーポイント
├─ gui.py           # デスクトップUI（tkinter）
├─ requirements.txt
├─ app/
│  ├─ config.py
│  ├─ models.py
│  ├─ audio_capture.py
│  ├─ vad.py
│  ├─ transcriber.py
│  ├─ formatter.py
│  ├─ clipboard_util.py
│  ├─ history.py
│  ├─ hotkey.py
│  └─ recording_session.py  # GUI用スレッド録音セッション
```

### 各ファイルの役割

- `main.py`: CLIエントリーポイント。各モジュールのオーケストレーション
- `app/config.py`: サンプリング設定、VAD閾値、Whisper設定、モード既定値
- `app/models.py`: `AudioChunk` / `UtteranceSegment` / `TranscriptResult` の共通型
- `app/audio_capture.py`: マイク入力をチャンク化しキューへ投入
- `app/vad.py`: Silero VAD + 状態機械で発話区間を切り出し
- `app/transcriber.py`: `faster-whisper` で発話区間を文字起こし
- `app/formatter.py`: 用途別テキスト整形（ルールベース）
- `app/clipboard_util.py`: クリップボードコピー/取得

## 4. セットアップ方法

### 4.1 Python仮想環境（例）

PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

### 4.2 依存パッケージのインストール

```powershell
pip install -r requirements.txt
```

> 注意: 現在の作業状態では `requirements.txt` が未作成の場合があります。未作成なら先に作成してください。

### 4.3 Whisperモデル初回ダウンロード

`faster-whisper` は初回実行時にモデルをダウンロードします。  
ネットワーク環境によって初回起動が遅くなる場合があります。

## 5. 実行方法

### デスクトップUI（推奨）

```powershell
python gui.py
```

- ダブルクリックで起動したい場合は `start_gui.cmd` を実行してください。

- **録音開始 / 録音停止**: トグルで録音の開始・停止
- **暫定 (partial)**: 発話中のリアルタイム認識表示
- **確定 (final)**: 発話区間確定後の整形テキスト（履歴は `logs/history.json`）
- モード・マイク・コピー/自動貼り付け/暫定表示は画面上で変更可能

### TUI（Textual / superwhisper風）

```powershell
python tui_main.py
```

- ダブルクリックで起動したい場合は `start_tui.cmd` を実行してください。
- キー操作: `R` start/stop / `M` mode / `C` copy / `Q` quit

### CLI（基本実行）

```powershell
python main.py --mode clean
```

### 主要オプション

- `--mode raw`
- `--mode clean`
- `--mode cursor`
- `--mode minutes`
- `--device <index or name>`
- `--list-devices`
- `--no-copy`
- `--show-partial`
- `--push-to-talk`
- `--auto-paste`
- `--history-path <path>`

### 例

```powershell
python main.py --list-devices
python main.py --mode clean
python main.py --mode cursor --device 1
python main.py --mode raw --no-copy --show-partial
python main.py --mode clean --push-to-talk --show-partial --auto-paste
```

## 6. 動作フロー

```text
Mic
  ↓
audio_capture
  ↓
vad
  ↓
transcriber
  ↓
formatter
  ↓
clipboard
```

## 7. Windowsでの注意点

- Windowsの「マイクアクセス許可」を有効化する
- `sounddevice` で入力デバイスが正しく選択されているか確認する（`--list-devices`）
- GPU利用時はCUDA/ドライバ/ライブラリ整備が必要
- `faster-whisper` の初回モデルDLは時間がかかる場合がある
- クリップボード利用不可環境ではコピー失敗するが、本体処理は継続可能

## 8. 今後の改善案

- AutoHotkey連携の追加強化
- 常駐ホットキー起動/停止の改善
- シンプルGUI追加
- ローカルLLMベース整形への差し替え
- 入力履歴の検索と再利用

## 9. ライセンス / 注意

- 本ツールは個人用途のMVPとして設計されています
- まずは動作安定性と実運用しやすさを優先しています
- 医療・法務など高い正確性が必要な用途では、必ず人間による確認を行ってください
- partial認識は進行中の発話バッファを再推論して表示します（確定テキストではありません）

