# HEIC Batch Converter / HEIC一括変換GUI

HEIC/HEIF を PNG または JPEG に一括変換するシンプルなデスクトップGUI（Tkinter）。
A simple Tkinter desktop GUI to batch-convert HEIC/HEIF into PNG or JPEG.


# 概要 / Overview

- フォールバック読込対応：Image.open() が HEIC を認識できない環境でも、pillow-heif.open_heif() を直接使って必ず開く設計。
- 非同期処理：変換はワーカースレッドで実行し、UIはフリーズしません。
- メタデータ：JPEG保存時に EXIF/ICC を可能な範囲で維持。PNGはデフォルトではEXIF非対応。
- 回転補正：ImageOps.exif_transpose() により、EXIFの向きを反映。


# 主な機能 / Features

- HEIC/HEIF → PNG / JPEG 一括変換
- JPEG 品質スライダー（60–100）
- EXIF保持（JPEGのみ、任意）
- ICCプロファイル（色プロファイル）の引き回し（可能な場合）
- 出力先フォルダを指定（未指定時は元フォルダ）
- 進捗バー・ログ表示
- （任意）ドラッグ＆ドロップ対応（tkinterdnd2）


# 動作環境 / Requirements

- Python: 3.9 以上（3.12 動作確認）
- OS: Windows / macOS / Linux
- 必須ライブラリ / Required:
  - Pillow (PIL)
  - pillow-heif
- 任意 / Optional:
  - **Tkinterdnd2** （ドラッグ＆ドロップ対応）

> Windows + Anaconda の場合は conda-forge 経由の pillow-heif が安定です。
> On Windows with Anaconda, prefer pillow-heif from conda-forge.


# インストール / Installation

## pip（公式Pythonなど） / Using pip

```bash
pip install -U pillow pillow-heif
# optional:
pip install tkinterdnd2
```

## conda（Anaconda/Miniconda） / Using conda

```bash
conda activate base   # ← your env
conda install -c conda-forge pillow-heif pillow
# optional:
pip install tkinterdnd2
```

### インストール確認 / Verify installation

```bash
python -c "import PIL, pillow_heif; print('Pillow', PIL.__version__, '| pillow-heif', pillow_heif.__version__)"
```


# 実行方法 / How to Run

## 1) 直接実行 / Direct

```bash
python heic_batch_converter_debug.py
```

Windows + Anaconda 環境で確実に動かすには、Python実行ファイルを明示：
For Windows + Anaconda, call the interpreter explicitly:

```pwsh
C:\Users\<YOU>\anaconda3\python.exe C:\path\to\heic_batch_converter_debug.py
```

## 2) VS Code での実行 / From VS Code

- 右上の「Run Python File」（Python拡張）で実行（Code Runnerは使わないのが安全）。
- ステータスバーのインタプリタが Anacondaの python.exe になっていることを確認。
- どうしても Code Runner を使うなら settings.json で固定：

```json
{
  "python.defaultInterpreterPath": "C:\\Users\\<YOU>\\anaconda3\\python.exe",
  "code-runner.runInTerminal": true,
  "code-runner.executorMap": {
    "python": "C:\\Users\\<YOU>\\anaconda3\\python.exe -u"
  }
}
```

# 使い方 / Usage

1. アプリを起動（上記「実行方法」参照）。
2. 「ファイルを追加」または「フォルダを追加」で HEIC/HEIF を読み込む。
  - （任意）DnD対応環境なら、ファイル/フォルダをリストにドラッグ。
3. 出力形式（PNG / JPEG）を選択。
  - JPEG時は 品質スライダー、EXIF保持を調整。
4. 出力先を必要に応じて指定（未指定なら元フォルダ）。
5. 「変換開始」で実行。ログと進捗が表示されます。


# 仕組み / Under the Hood

## フォールバック読込 / Fallback loading
  `open_image_any(path)` が、

1. `Image.open(path) `を試し、

2. 失敗時に `pillow_heif.open_heif(path)` → `Image.frombytes(...) `で 必ず開く。
  これにより、PillowのHEIFプラグイン登録が無効な環境でも安定動作します。

## メタデータ / Metadata
  - JPEG 保存時に EXIF を再埋め込み（チェックONかつEXIFがある場合）。
  - ICCプロファイルが取れたら JPEG 保存時に付与。PNGへ入れたい場合はコードの該当箇所を有効化可能。
## 回転補正 / Orientation
  `ImageOps.exif_transpose() `でEXIFの向きを画素に適用。表示の天地が正しくなります。
## スレッド / Threading
  変換は `ConverterThread`（`threading.Thread`）で実行。
  UI更新は `root.after(...)` でメインスレッドにディスパッチします。


# トラブルシューティング / Troubleshooting

## 1) `ModuleNotFoundError: No module named 'pillow_heif'`

- 実行している Python が インストール先と違う可能性が高いです。
  - `python -c "import sys; print(sys.executable)"` で 実行中のPythonパスを確認。
  - Anacondaなら `...anaconda3\python.exe` を使って起動。
  - VS CodeではインタプリタをAnacondaに固定、または上の settings.json を設定。

## 2) `cannot identify image file '... .HEIC'`

- Pillow側のHEIF登録が無効でも、このアプリはフォールバックで開くように作ってあります。
- それでも失敗する場合は、問題のファイル1枚で実行し、GUIログに表示されるフルスタックを確認してください。

## 3) `UserWarning: Unknown feature 'heif'`

- 一部環境で `features.check('heif')` が Unknown になりますが、問題ありません（診断用の表示だけです）。

## 4) 文字化けやパス問題

- まずは `C:\Temp` など ASCII パスでテスト。ネットワークドライブ/NASは一時的にローカルへコピー。

## 5) 非常に大きい画像での警告
- `Image.MAX_IMAGE_PIXELS = None` を設定済み。警告で止まりにくい設計です（必要に応じて元に戻せます）。

# よくある質問 / FAQ

Q. PNG保存時にEXIFは残りますか？
A. 既定では残しません（互換性のため）。必要ならコードの該当箇所に EXIF/ICC の埋め込み処理を追加可能です。

Q. サブサンプリング（4:4:4 / 4:2:0）を指定できますか？
A. 可能です。`save_kwargs["subsampling"] = 2`（= 4:2:0）など、コメント行を有効化してください。

Q. マルチフレーム（Live Photo的）HEIFは？
A. 先頭フレームのみを使用しています（`im.seek(0)`）。

Q. WebP/AVIFなど他形式に出力できますか？
A. 現状は PNG/JPEG のみ。拡張は容易です（Pillowのビルド/依存に左右されます）。


# 開発メモ / Developer Notes

- 変換順序：開く →（先頭フレーム）→ 回転補正 →（JPEG時）RGB → 保存
- 保存時の衝突は safe_output_path() で連番回避。
- 例外は traceback.format_exc() をそのままGUIログに出すため、現場での切り分けが容易。


# ライセンス / License

MIT（想定）。必要に応じて置き換えてください。
MIT (suggested). Replace as appropriate for your project.


# 謝辞 / Acknowledgements

Pillow
 – The friendly PIL fork

pillow-heif
 – HEIF/HEIC decoder for Pillow

tkinterdnd2 – Drag & Drop for Tkinter (optional)


# 連絡 / Support

改善案や問題報告は、該当ログ（GUIの✖エラー行＋スタックトレース）とともにお知らせください。
For issues or suggestions, please include the GUI log line with the full traceback so we can help quickly.

Happy converting! / 快適変換ライフを！
