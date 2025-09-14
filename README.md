# HEIC Convert App / HEIC一括変換GUI

HEIC/HEIF を **PNG** または **JPEG** に一括変換するシンプルなデスクトップ GUI（Tkinter）。  
A simple Tkinter desktop GUI to batch-convert **HEIC/HEIF** into **PNG** or **JPEG**.

---

## 概要 / Overview

- **フォールバック読込 / Fallback loading**: `Image.open()` が HEIC を認識できない環境でも、`pillow-heif.open_heif()` を直接使って **必ず開く** 設計。  
- **非同期処理 / Non‑blocking UI**: 変換はワーカースレッドで実行し、UI はフリーズしません。  
- **メタデータ / Metadata**: JPEG 保存時に **EXIF/ICC** を可能な範囲で維持（PNG の EXIF は既定で無効）。  
- **回転補正 / Orientation fix**: `ImageOps.exif_transpose()` により、EXIF の向きを反映。

---

## 主な機能 / Features

- HEIC/HEIF → PNG / JPEG **一括変換** 
- JPEG **品質スライダー**（60–100）
- **EXIF** 保持（JPEGのみ、任意） 
- **ICC** プロファイルを可能な範囲で引き回し 
- **出力先フォルダ**指定（未指定時は元フォルダ）
- **進捗バー・詳細ログ** 
- （任意）**ドラッグ＆ドロップ**対応（[`tkinterdnd2`](https://pypi.org/project/tkinterdnd2/)）
---

## 動作環境 / Requirements

- **Python**: 3.9+（3.12 で動作確認） / 3.9+ (tested on 3.12)  
- **OS**: Windows11 （macOS / Linux　は未検証）  
- **Required**:  
  - [`Pillow`](https://pypi.org/project/pillow/))  
  - [pillow-heif](https://pypi.org/project/pillow-heif/)  
- **Optional**:  
  - [`tkinterdnd2`](https://pypi.org/project/tkinterdnd2/)（ドラッグ＆ドロップ） / drag & drop support

> **Windows + Anaconda** では、`conda-forge` から `pillow-heif` を入れるのが安定です。  
> On **Windows + Anaconda**, prefer installing `pillow-heif` from `conda-forge`.

---

## 使い方 / Usage

1. アプリを起動（上記「実行方法」参照）。 / Launch the app.  
2. 「**ファイルを追加**」「**フォルダを追加**」で HEIC/HEIF を読み込み（DnD 可）。 / Add files or folder (DnD supported).  
3. **出力形式**（PNG / JPEG）を選択。 / Choose **output format** (PNG/JPEG).  
   - JPEG 時は **品質スライダー**、**EXIF保持**を調整。 / For JPEG, set **quality** and **keep EXIF**.  
4. **出力先**を必要に応じて指定（未指定なら元フォルダ）。 / Set **output folder** (optional; defaults to source).  
5. 「**変換開始**」で実行。ログと進捗が表示されます。 / Click **Convert** to start and watch logs/progress.

---

## 仕組み / Under the Hood

### フォールバック読込 / Fallback loading
`open_image_any(path)` が以下を試行：
1. `Image.open(path)`（成功時は `im.info['exif']` / `icc_profile` 取得）  
2. 失敗時は `pillow_heif.open_heif(path)` → `Image.frombytes(...)` で **必ず開く**  

> Pillow の HEIF プラグイン登録が無効でも安定動作します。  
> This guarantees opening HEIC even when Pillow's HEIF plugin isn't registered.

### メタデータ / Metadata
- **JPEG**: オプション ON かつ EXIF がある場合 `exif=` で再埋め込み。ICC があれば `icc_profile=` を付与。  
- **PNG**: 既定では EXIF を埋め込みません（必要ならコードで拡張可能）。

### 回転補正 / Orientation
`ImageOps.exif_transpose()` で EXIF の向きを画素に適用。画像の天地が正しくなります。

### スレッド / Threading
重い処理は `ConverterThread`（`threading.Thread`）で実行。  
UI 更新は `root.after(...)` でメインスレッドにディスパッチ。

---

## ライセンス / License

MIT

