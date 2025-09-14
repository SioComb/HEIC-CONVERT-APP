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

- HEIC/HEIF → PNG / JPEG **一括変換** / **Batch** conversion  
- JPEG **品質スライダー**（60–100） / JPEG **quality** slider (60–100)  
- **EXIF** 保持（JPEGのみ、任意） / Keep **EXIF** (JPEG only, optional)  
- **ICC** プロファイルを可能な範囲で引き回し / Carry **ICC** profile when available  
- **出力先フォルダ**指定（未指定時は元フォルダ） / Select **output folder** (defaults to source)  
- **進捗バー・詳細ログ** / **Progress bar & detailed log**  
- （任意）**ドラッグ＆ドロップ**対応（[`tkinterdnd2`](https://pypi.org/project/tkinterdnd2/)） / Optional **drag & drop** via [`tkinterdnd2`](https://pypi.org/project/tkinterdnd2/)

---

## 動作環境 / Requirements

- **Python**: 3.9+（3.12 で動作確認） / 3.9+ (tested on 3.12)  
- **OS**: Windows / macOS / Linux  
- **Required**:  
  - [`Pillow`](https://pypi.org/project/pillow/))  
  - [pillow-heif](https://pypi.org/project/pillow-heif/)  
- **Optional**:  
  - [`tkinterdnd2`](https://pypi.org/project/tkinterdnd2/)（ドラッグ＆ドロップ） / drag & drop support

> **Windows + Anaconda** では、`conda-forge` から `pillow-heif` を入れるのが安定です。  
> On **Windows + Anaconda**, prefer installing `pillow-heif` from `conda-forge`.

---

## インストール / Installation

### pip（公式 Python など） / Using pip
```bash
pip install -U pillow pillow-heif
# optional
pip install tkinterdnd2
```

### conda（Anaconda/Miniconda） / Using conda
```bash
conda activate base   # ← your env
conda install -c conda-forge pillow-heif pillow
# optional
pip install tkinterdnd2
```

### インストール確認 / Verify installation
```bash
python -c "import PIL, pillow_heif; print('Pillow', PIL.__version__, '| pillow-heif', pillow_heif.__version__)"
```

---

## 実行方法 / How to Run

### 1) 直接実行 / Direct
```bash
python heic_batch_converter_debug.py
# or
python heic_batch_converter.py
```

**Windows + Anaconda で確実に動かすには**、Python 実行ファイルを明示：  
For **Windows + Anaconda**, call the interpreter explicitly:
```powershell
C:\Users\<YOU>\anaconda3\python.exe C:\path\to\heic_batch_converter_debug.py
```

### 2) VS Code での実行 / From VS Code
- 右上の **“Run Python File”**（Python 拡張）で実行（**Code Runner は非推奨**）。  
- ステータスバーのインタプリタが **Anaconda の `python.exe`** になっていることを確認。  
- どうしても Code Runner を使う場合、`settings.json` で固定：
```json
{
  "python.defaultInterpreterPath": "C:\\\\Users\\\\<YOU>\\\\anaconda3\\\\python.exe",
  "code-runner.runInTerminal": true,
  "code-runner.executorMap": {
    "python": "C:\\\\Users\\\\<YOU>\\\\anaconda3\\\\python.exe -u"
  }
}
```

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

## トラブルシューティング / Troubleshooting

### `ModuleNotFoundError: No module named 'pillow_heif'`
- インストールした Python と **別の Python** で実行している可能性。  
  - `python -c "import sys; print(sys.executable)"` で実行中のパスを確認。  
  - Anaconda の `...\anaconda3\python.exe` を明示、または VS Code でピン留め。

### `cannot identify image file '... .HEIC'`
- フォールバックで開ける設計です。1 枚で試し、GUI ログの **フルスタック** を確認してください。

### `UserWarning: Unknown feature 'heif'`
- 一部環境で `features.check('heif')` が Unknown になりますが、**問題ありません**（診断用）。

### パス/文字化け / Path & encoding
- まずは `C:\Temp` など ASCII パスで検証。NAS/ネットワークは一旦ローカルに。

### 超高解像度の警告 / Huge images
- `Image.MAX_IMAGE_PIXELS = None` を設定済み。必要なら制限を戻してください。

---

## よくある質問 / FAQ

- **PNG 保存時に EXIF は残る？ / Does PNG keep EXIF?**  
  既定では残りません。必要なら PNG への EXIF/ICC 埋め込みを実装してください。

- **サブサンプリング（4:4:4 / 4:2:0）を指定できる？ / Chroma subsampling?**  
  可能です。例：`save_kwargs["subsampling"] = 2`（= 4:2:0）。

- **マルチフレーム HEIF は？ / Multi‑frame HEIF?**  
  先頭フレームのみ使用（`im.seek(0)`）。

- **WebP/AVIF など他形式に出力？ / Other output formats?**  
  現状は PNG/JPEG。Pillow のビルドに応じて拡張可能です。

---

## ライセンス / License

MIT

