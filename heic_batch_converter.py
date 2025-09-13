# heic_batch_converter.py
# -*- coding: utf-8 -*-
"""
シンプルなGUIアプリ：HEIC/HEIFをPNGまたはJPEGに一括変換
- Windows / macOS / Linux (Python 3.9+)
- 必要ライブラリ: Pillow, pillow-heif（任意でtkinterdnd2を使うとドラッグ&ドロップ対応）
- 機能:
    * ファイル追加 / フォルダ追加 / （任意）ドラッグ&ドロップ
    * 出力形式: PNG または JPEG
    * JPEG 品質スライダー
    * EXIF保持（JPEGのみ）
    * 出力先フォルダ選択（デフォルトは元フォルダ）
    * プログレスバー + ログ
"""

import os
import sys
import threading
from pathlib import Path
from typing import List, Optional

# --- 画像処理ライブラリの読み込み ---
# Pillow本体と、HEIF/HEICを開けるようにする拡張を読み込み
from PIL import Image, ImageOps
try:
    import pillow_heif
    # PillowにHEIF/HEICを開くオープナーを登録（これで Image.open() がHEICを認識できる）
    pillow_heif.register_heif_opener()
except Exception as e:
    # ここはGUIではなく標準出力に流す。未インストールでもアプリは起動するが変換は失敗する
    print("HEIFオープナーの登録に失敗しました。'pillow-heif' がインストールされているか確認してください。", e)

# --- GUI部品の読み込み ---
import tkinter as tk
from tkinter import filedialog, ttk, messagebox

# --- ドラッグ&ドロップ対応（任意） ---
DND_AVAILABLE = False
try:
    # pip install tkinterdnd2 で利用可能
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False

# 対応拡張子（大文字/小文字を両方含める）
SUPPORTED_EXTS = {".heic", ".heif", ".HEIC", ".HEIF"}


# =============================================================================
# ユーティリティ関数
# =============================================================================

def collect_heic_files(paths: List[Path]) -> List[Path]:
    """入力パス（ファイル/フォルダ混在）から、HEIC/HEIFファイルの一覧を収集する。
    - フォルダが渡された場合は再帰的に探索（rglob）
    - 順序を保持したまま重複を排除
    """
    files: List[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for ext in SUPPORTED_EXTS:
                files.extend(p.rglob(f"*{ext}"))
        elif p.is_file() and p.suffix in SUPPORTED_EXTS:
            files.append(p)
    # 重複除去（順序維持のため set + 手動フィルタ）
    seen = set()
    uniq: List[Path] = []
    for f in files:
        if f not in seen:
            uniq.append(f)
            seen.add(f)
    return uniq


def safe_output_path(src: Path, out_dir: Optional[Path], out_ext: str) -> Path:
    """出力先パスを安全に決定する。
    - 出力フォルダ未指定なら元ファイルのフォルダに保存
    - 既に同名ファイルが存在する場合は _1, _2 ... と連番を付与
    """
    base = src.stem
    dir_ = out_dir if out_dir else src.parent
    candidate = dir_ / f"{base}{out_ext}"
    idx = 1
    while candidate.exists():
        candidate = dir_ / f"{base}_{idx}{out_ext}"
        idx += 1
    return candidate


# =============================================================================
# 変換処理スレッド（バックグラウンド）
# =============================================================================

class ConverterThread(threading.Thread):
    """画像変換を行うワーカー・スレッド。
    - GUIフリーズを防ぐため、重いI/Oは別スレッドで実行
    - Tkウィジェットの操作は行わず、コールバック経由で通知のみ行う（※UI操作はメインスレッドで）
    """
    def __init__(
        self,
        files: List[Path],
        out_dir: Optional[Path],
        fmt: str,
        jpg_quality: int,
        keep_exif: bool,
        progress_cb,   # 進行状況を通知するコールバック（done, total）
        log_cb,        # ログ文字列を通知するコールバック（str）
        done_cb        # 完了時に呼び出すコールバック（引数なし）
    ):
        super().__init__(daemon=True)
        self.files = files
        self.out_dir = out_dir
        self.fmt = fmt                  # "PNG" または "JPEG"
        self.jpg_quality = jpg_quality
        self.keep_exif = keep_exif
        self.progress_cb = progress_cb
        self.log_cb = log_cb
        self.done_cb = done_cb

    def run(self):
        """各ファイルについて順番に変換を実行する。例外は1件ずつ握りつぶして続行。"""
        total = len(self.files)
        count = 0
        for src in self.files:
            try:
                # 出力拡張子を決定
                out_ext = ".png" if self.fmt == "PNG" else ".jpg"
                out_path = safe_output_path(src, self.out_dir, out_ext)

                # 画像を開く（pillow-heifが登録済みならHEICも開ける）
                with Image.open(src) as im:
                    # --- 複数フレーム（アニメーションHEIF等）対策：先頭フレームを選択 ---
                    try:
                        if getattr(im, "n_frames", 1) > 1:
                            im.seek(0)
                    except Exception:
                        # n_framesが無い or seek不可なら無視
                        pass

                    # --- EXIFの回転情報を反映：縦横が正しくなる ---
                    im = ImageOps.exif_transpose(im)

                    # --- 保存パラメータを準備 ---
                    save_kwargs = {}
                    exif_bytes = im.info.get("exif")          # EXIFバイナリ
                    icc = im.info.get("icc_profile")          # ICCプロファイル

                    if self.fmt == "JPEG":
                        # JPEGは品質やプログレッシブ等を設定
                        save_kwargs["quality"] = self.jpg_quality
                        save_kwargs["optimize"] = True
                        save_kwargs["progressive"] = True
                        # subsamplingは未指定が最も互換性高いが、指定したい場合は数値で（2=4:2:0）
                        # save_kwargs["subsampling"] = 2

                        # カラープロファイルがあれば渡す（色ズレ抑制）
                        if icc:
                            save_kwargs["icc_profile"] = icc
                        # EXIFを保持したい場合は付与
                        if self.keep_exif and exif_bytes:
                            save_kwargs["exif"] = exif_bytes

                        # JPEGはRGB前提。RGBA/パレット等はRGBへ変換
                        if im.mode not in ("RGB",):
                            im = im.convert("RGB")
                    else:
                        # PNGは可逆圧縮（optimize）
                        save_kwargs["optimize"] = True
                        # ICCはPNGでも埋め込めるが、用途次第。必要なら下記を有効化
                        # if icc:
                        #     save_kwargs["icc_profile"] = icc

                    # 出力フォルダを作成（なければ再帰的に作る）
                    out_path.parent.mkdir(parents=True, exist_ok=True)

                    # 画像を保存
                    im.save(out_path, self.fmt, **save_kwargs)

                # 正常終了ログ
                self.log_cb(f"✔ 変換完了: {src.name} → {out_path.name}")
            except Exception as e:
                # 1件ごとにエラーを記録して続行
                self.log_cb(f"✖ エラー: {src}  ({e})")
            finally:
                # 進捗カウントを更新
                count += 1
                self.progress_cb(count, total)

        # 全件処理後に完了コールバック
        self.done_cb()


# =============================================================================
# GUIアプリ本体
# =============================================================================

class App:
    """Tkinterベースの簡易GUI。
    - ファイル/フォルダ指定、オプション設定、進捗表示、ログ表示を担当
    - 実処理はConverterThreadへ委譲
    """
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("HEIC → PNG/JPEG 一括変換")
        self.files: List[Path] = []            # 変換対象のファイルリスト
        self.out_dir: Optional[Path] = None    # 出力先ディレクトリ（Noneなら元フォルダ）

        # --- ルートフレーム（余白つき） ---
        outer = ttk.Frame(root, padding=12)
        outer.pack(fill="both", expand=True)

        # --- ファイル一覧（ドラッグ&ドロップ可能） ---
        self.listbox = tk.Listbox(outer, height=10, selectmode="extended")
        self.listbox.grid(row=0, column=0, columnspan=4, sticky="nsew", pady=(0, 8))
        self._configure_drop(self.listbox)

        # --- ボタン群（追加/削除/クリア） ---
        btn_add_files = ttk.Button(outer, text="ファイルを追加", command=self.add_files)
        btn_add_folder = ttk.Button(outer, text="フォルダを追加", command=self.add_folder)
        btn_remove = ttk.Button(outer, text="選択を削除", command=self.remove_selected)
        btn_clear = ttk.Button(outer, text="リストをクリア", command=self.clear_list)
        btn_add_files.grid(row=1, column=0, sticky="ew", pady=2)
        btn_add_folder.grid(row=1, column=1, sticky="ew", pady=2)
        btn_remove.grid(row=1, column=2, sticky="ew", pady=2)
        btn_clear.grid(row=1, column=3, sticky="ew", pady=2)

        # --- オプション領域 ---
        opts = ttk.LabelFrame(outer, text="オプション", padding=10)
        opts.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 8))
        opts.grid_columnconfigure(5, weight=1)

        # 出力形式（PNG / JPEG）
        ttk.Label(opts, text="出力形式:").grid(row=0, column=0, sticky="w")
        self.fmt_var = tk.StringVar(value="PNG")
        fmt_png = ttk.Radiobutton(opts, text="PNG（劣化なし）", value="PNG", variable=self.fmt_var)
        fmt_jpg = ttk.Radiobutton(opts, text="JPEG", value="JPEG", variable=self.fmt_var)
        fmt_png.grid(row=0, column=1, sticky="w")
        fmt_jpg.grid(row=0, column=2, sticky="w")

        # JPEG品質（スライダー）
        ttk.Label(opts, text="JPEG品質:").grid(row=0, column=3, padx=(16, 4), sticky="e")
        self.quality = tk.IntVar(value=90)
        self.quality_scale = ttk.Scale(opts, from_=60, to=100, orient="horizontal", variable=self.quality)
        self.quality_scale.grid(row=0, column=4, sticky="ew")
        self.q_label = ttk.Label(opts, text="90")
        self.q_label.grid(row=0, column=5, padx=(6, 0), sticky="w")
        # スライダー値の表示をライブ更新
        self.quality.trace_add("write", lambda *args: self.q_label.config(text=str(int(self.quality.get()))))

        # EXIF保持（JPEGのみ有効）
        self.keep_exif = tk.BooleanVar(value=True)
        self.chk_exif = ttk.Checkbutton(opts, text="EXIFを保持（JPEGのみ）", variable=self.keep_exif)
        self.chk_exif.grid(row=1, column=1, columnspan=2, sticky="w", pady=(8, 0))

        # 出力先ディレクトリの選択
        self.out_dir_label = ttk.Label(opts, text="出力先: （元のフォルダ）")
        self.out_dir_label.grid(row=1, column=3, columnspan=2, sticky="w", pady=(8, 0))
        btn_out = ttk.Button(opts, text="出力先を選択…", command=self.choose_out_dir)
        btn_out.grid(row=1, column=5, sticky="e", pady=(8, 0))

        # --- 進捗バーと開始ボタン ---
        self.progress = ttk.Progressbar(outer, maximum=100)  # 最大値は開始時に総件数へ差し替え
        self.progress.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(0, 8))

        self.start_btn = ttk.Button(outer, text="変換開始", command=self.start)
        self.start_btn.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(0, 8))

        # --- ログ出力（読み取り専用Text） ---
        self.log = tk.Text(outer, height=10, state="disabled")
        self.log.grid(row=5, column=0, columnspan=4, sticky="nsew")

        # --- レイアウトの伸縮設定 ---
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_columnconfigure(1, weight=1)
        outer.grid_columnconfigure(2, weight=1)
        outer.grid_columnconfigure(3, weight=1)
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_rowconfigure(5, weight=1)

        # DnD未導入時の案内をログへ
        if not DND_AVAILABLE:
            self._append_log("※ ドラッグ＆ドロップを使うには 'pip install tkinterdnd2' を追加インストールしてください。\n")

    # ---- DnD有効化（tkinterdnd2がある場合のみ設定） ----
    def _configure_drop(self, widget):
        """ListboxにD&Dターゲットを登録し、ファイル/フォルダのドロップを受け付ける。"""
        if DND_AVAILABLE:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop(self, event):
        """OSから渡されるドロップ文字列（空白やクォート混じり）をパースしてパス配列に整形する。"""
        raw = event.data
        paths: List[str] = []
        buf = ""
        in_quotes = False
        for ch in raw:
            if ch == '"':
                in_quotes = not in_quotes
                if not in_quotes and buf:
                    paths.append(buf)
                    buf = ""
            elif ch == " " and not in_quotes:
                if buf:
                    paths.append(buf)
                    buf = ""
            else:
                buf += ch
        if buf:
            paths.append(buf)
        self.add_paths(paths)

    # ---- ファイル/フォルダ追加系 ----
    def add_paths(self, paths: List[str]):
        """渡されたパス（文字列）を収集関数へ渡し、Listbox/内部リストを更新する。"""
        files = collect_heic_files([Path(p) for p in paths])
        added = 0
        for f in files:
            if f not in self.files:
                self.files.append(f)
                self.listbox.insert("end", str(f))
                added += 1
        self._append_log(f"+ 追加: {added} ファイル\n")

    def add_files(self):
        """ファイル選択ダイアログからHEIC/HEIFファイルを追加する。"""
        paths = filedialog.askopenfilenames(
            title="HEIC/HEIF ファイルを選択",
            filetypes=[("HEIC/HEIF", "*.heic *.HEIC *.heif *.HEIF")]
        )
        if paths:
            self.add_paths(list(paths))

    def add_folder(self):
        """フォルダ選択ダイアログからフォルダを追加し、再帰的にHEIC/HEIFを収集する。"""
        d = filedialog.askdirectory(title="フォルダを選択")
        if d:
            self.add_paths([d])

    def clear_list(self):
        """リストをクリアする（内部配列とListboxの両方）。"""
        self.files.clear()
        self.listbox.delete(0, "end")
        self._append_log("リストをクリアしました。\n")

    def remove_selected(self):
        """Listboxで選択中の行を削除する。"""
        sel = list(self.listbox.curselection())
        sel.reverse()  # 後方から削除することでインデックスずれを防ぐ
        for idx in sel:
            try:
                self.files.pop(idx)
                self.listbox.delete(idx)
            except Exception:
                pass

    def choose_out_dir(self):
        """出力先フォルダを選択し、ラベル表示を更新する。"""
        d = filedialog.askdirectory(title="出力先フォルダを選択")
        if d:
            self.out_dir = Path(d)
            self.out_dir_label.config(text=f"出力先: {self.out_dir}")

    # ---- 変換開始 ----
    def start(self):
        """入力チェックを行い、変換ワーカースレッドを起動。進行/ログ/完了は after でUIスレッドへ反映する。"""
        if not self.files:
            messagebox.showwarning("警告", "ファイルがありません。先に追加してください。")
            return

        fmt = self.fmt_var.get()
        jpg_q = int(self.quality.get())
        keep_exif = bool(self.keep_exif.get())

        # UI初期化（ボタン無効化・プログレス初期化・開始ログ）
        self.start_btn.config(state="disabled")
        self.progress.config(value=0, maximum=len(self.files))
        self._append_log(f"=== 変換開始（{fmt}, JPEG品質={jpg_q}, EXIF保持={keep_exif}）===\n")

        # --- 以下、ワーカースレッドから呼ばれるコールバックをUIスレッドで実行するため after でラップ ---
        def on_progress(done, total):
            # 進捗バー更新はメインスレッドで実施
            self.root.after(0, lambda: self.progress.config(value=done))

        def on_log(msg: str):
            # ログ追記もメインスレッドにディスパッチ
            self.root.after(0, lambda: self._append_log(msg + "\n"))

        def on_done():
            # 完了時のUI更新（ボタン復帰・メッセージ表示）をメインスレッドで実行
            def _finish():
                self._append_log("=== 完了 ===\n")
                self.start_btn.config(state="normal")
                messagebox.showinfo("完了", "変換が完了しました。")
            self.root.after(0, _finish)

        # ワーカースレッドを起動
        t = ConverterThread(self.files, self.out_dir, fmt, jpg_q, keep_exif, on_progress, on_log, on_done)
        t.start()

    # ---- ログ追記（Textを読み書き可能にしてから、末尾へ追記→自動スクロール→再び不可に） ----
    def _append_log(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")


# =============================================================================
# エントリポイント
# =============================================================================

def main():
    """アプリ起動処理。
    - DnD対応Tkを優先的に使用
    - WindowsではHiDPI環境でのにじみ対策を実施
    - テーマ設定とウィンドウ最小サイズを指定
    """
    # DnD対応Tkの選択（利用可能なら使う）
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()

    # WindowsのHiDPIスケーリング対策（可能な環境のみ）
    try:
        if sys.platform.startswith("win"):
            from ctypes import windll
            # 1=SYSTEM_DPI_AWARE（マルチモニタ環境ではPer-Monitorにしたい場合もあるが、ここでは簡易対応）
            windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    # ttkテーマの適用（vistaが使える環境なら適用）
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")

    # アプリ本体を構築してメインループへ
    App(root)
    root.minsize(720, 520)
    root.mainloop()


if __name__ == "__main__":
    main()
