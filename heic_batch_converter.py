# heic_batch_converter.py
# -*- coding: utf-8 -*-
"""
シンプルなGUIアプリ：HEIC/HEIFをPNGまたはJPEGに一括変換
- Windows / macOS / Linux (Python 3.9+)
- 必要ライブラリ: Pillow, pillow-heif（任意でtkinterdnd2を使うとドラッグ&ドロップ対応）
- 機能:
    * ファイル追加 / フォルダ追加
    * （任意）tkinterdnd2があればドラッグ&ドロップ対応
    * 出力形式: PNG または JPEG
    * JPEG 品質スライダー
    * EXIF保持（JPEGのみ）
    * 出力先フォルダ選択（デフォルトは元フォルダ）
    * プログレスバー + ログ
"""
import os
import sys
import threading
import queue
from pathlib import Path
from typing import List, Optional

# Pillow と HEIF対応
from PIL import Image, ImageOps
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception as e:
    print("HEIFオープナーの登録に失敗しました。'pillow-heif' がインストールされているか確認してください。", e)

import tkinter as tk
from tkinter import filedialog, ttk, messagebox

# 任意のドラッグ&ドロップ対応
DND_AVAILABLE = False
try:
    # pip install tkinterdnd2
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False

SUPPORTED_EXTS = {".heic", ".heif", ".HEIC", ".HEIF"}

# 変換対象のファイルを配列に保持
def collect_heic_files(paths: List[Path]) -> List[Path]:
    files: List[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for ext in SUPPORTED_EXTS:
                files.extend(p.rglob(f"*{ext}"))
        elif p.is_file() and p.suffix in SUPPORTED_EXTS:
            files.append(p)
    # 重複を除去しつつ順序を保持
    seen = set()
    uniq = []
    for f in files:
        if f not in seen:
            uniq.append(f)
            seen.add(f)
    return uniq


def safe_output_path(src: Path, out_dir: Optional[Path], out_ext: str) -> Path:
    base = src.stem
    dir_ = out_dir if out_dir else src.parent
    candidate = dir_ / f"{base}{out_ext}"
    idx = 1
    while candidate.exists():
        candidate = dir_ / f"{base}_{idx}{out_ext}"
        idx += 1
    return candidate


class ConverterThread(threading.Thread):
    def __init__(self, files: List[Path], out_dir: Optional[Path], fmt: str, jpg_quality: int, keep_exif: bool, progress_cb, log_cb, done_cb):
        super().__init__(daemon=True)
        self.files = files
        self.out_dir = out_dir
        self.fmt = fmt  # "PNG" または "JPEG"
        self.jpg_quality = jpg_quality
        self.keep_exif = keep_exif
        self.progress_cb = progress_cb
        self.log_cb = log_cb
        self.done_cb = done_cb

    def run(self):
        total = len(self.files)
        count = 0
        for src in self.files:
            try:
                out_ext = ".png" if self.fmt == "PNG" else ".jpg"
                out_path = safe_output_path(src, self.out_dir, out_ext)

                with Image.open(src) as im:
                    # EXIFの回転情報を反映
                    im = ImageOps.exif_transpose(im)
                    save_kwargs = {}
                    exif_bytes = im.info.get("exif")
                    if self.fmt == "JPEG":
                        save_kwargs["quality"] = self.jpg_quality
                        save_kwargs["subsampling"] = "4:2:0"
                        save_kwargs["optimize"] = True
                        if self.keep_exif and exif_bytes:
                            save_kwargs["exif"] = exif_bytes
                    else:
                        # PNG: 可逆圧縮
                        save_kwargs["optimize"] = True

                    # モード変換（JPEGはRGBに限定される）
                    if self.fmt == "JPEG" and im.mode in ("RGBA", "LA", "P"):
                        im = im.convert("RGB")

                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    im.save(out_path, self.fmt, **save_kwargs)

                self.log_cb(f"✔ 変換完了: {src.name} → {out_path.name}")
            except Exception as e:
                self.log_cb(f"✖ エラー: {src}  ({e})")
            finally:
                count += 1
                self.progress_cb(count, total)
        self.done_cb()


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("HEIC → PNG/JPEG 一括変換")
        self.files: List[Path] = []
        self.out_dir: Optional[Path] = None

        outer = ttk.Frame(root, padding=12)
        outer.pack(fill="both", expand=True)

        # ドロップエリア / ファイルリスト
        self.listbox = tk.Listbox(outer, height=10, selectmode="extended")
        self.listbox.grid(row=0, column=0, columnspan=4, sticky="nsew", pady=(0,8))
        self._configure_drop(self.listbox)

        # ボタン群
        btn_add_files = ttk.Button(outer, text="ファイルを追加", command=self.add_files)
        btn_add_folder = ttk.Button(outer, text="フォルダを追加", command=self.add_folder)
        btn_clear = ttk.Button(outer, text="リストをクリア", command=self.clear_list)
        btn_remove = ttk.Button(outer, text="選択を削除", command=self.remove_selected)
        btn_add_files.grid(row=1, column=0, sticky="ew", pady=2)
        btn_add_folder.grid(row=1, column=1, sticky="ew", pady=2)
        btn_remove.grid(row=1, column=2, sticky="ew", pady=2)
        btn_clear.grid(row=1, column=3, sticky="ew", pady=2)

        # オプション
        opts = ttk.LabelFrame(outer, text="オプション", padding=10)
        opts.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8,8))
        opts.grid_columnconfigure(5, weight=1)

        ttk.Label(opts, text="出力形式:").grid(row=0, column=0, sticky="w")
        self.fmt_var = tk.StringVar(value="PNG")
        fmt_png = ttk.Radiobutton(opts, text="PNG（劣化なし）", value="PNG", variable=self.fmt_var)
        fmt_jpg = ttk.Radiobutton(opts, text="JPEG", value="JPEG", variable=self.fmt_var)
        fmt_png.grid(row=0, column=1, sticky="w")
        fmt_jpg.grid(row=0, column=2, sticky="w")

        ttk.Label(opts, text="JPEG品質:").grid(row=0, column=3, padx=(16,4), sticky="e")
        self.quality = tk.IntVar(value=90)
        self.quality_scale = ttk.Scale(opts, from_=60, to=100, orient="horizontal", variable=self.quality)
        self.quality_scale.grid(row=0, column=4, sticky="ew")
        self.q_label = ttk.Label(opts, text="90")
        self.q_label.grid(row=0, column=5, padx=(6,0), sticky="w")
        self.quality.trace_add("write", lambda *args: self.q_label.config(text=str(int(self.quality.get()))))

        self.keep_exif = tk.BooleanVar(value=True)
        self.chk_exif = ttk.Checkbutton(opts, text="EXIFを保持（JPEGのみ）", variable=self.keep_exif)
        self.chk_exif.grid(row=1, column=1, columnspan=2, sticky="w", pady=(8,0))

        self.out_dir_label = ttk.Label(opts, text="出力先: （元のフォルダ）")
        self.out_dir_label.grid(row=1, column=3, columnspan=2, sticky="w", pady=(8,0))
        btn_out = ttk.Button(opts, text="出力先を選択…", command=self.choose_out_dir)
        btn_out.grid(row=1, column=5, sticky="e", pady=(8,0))

        # プログレスバー + 開始ボタン
        self.progress = ttk.Progressbar(outer, maximum=100)
        self.progress.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(0,8))

        self.start_btn = ttk.Button(outer, text="変換開始", command=self.start)
        self.start_btn.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(0,8))

        # ログ
        self.log = tk.Text(outer, height=10, state="disabled")
        self.log.grid(row=5, column=0, columnspan=4, sticky="nsew")

        # レイアウト調整
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_columnconfigure(1, weight=1)
        outer.grid_columnconfigure(2, weight=1)
        outer.grid_columnconfigure(3, weight=1)
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_rowconfigure(5, weight=1)

        if not DND_AVAILABLE:
            self._append_log("※ ドラッグ＆ドロップを使うには 'pip install tkinterdnd2' を追加インストールしてください。\n")

    def _configure_drop(self, widget):
        if DND_AVAILABLE:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop(self, event):
        # Windowsではパスの文字列（場合によってはクォート付き）が渡される
        raw = event.data
        paths = []
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

    def add_paths(self, paths: List[str]):
        files = collect_heic_files([Path(p) for p in paths])
        added = 0
        for f in files:
            if f not in self.files:
                self.files.append(f)
                self.listbox.insert("end", str(f))
                added += 1
        self._append_log(f"+ 追加: {added} ファイル\n")

    def add_files(self):
        paths = filedialog.askopenfilenames(title="HEIC/HEIF ファイルを選択", filetypes=[("HEIC/HEIF", "*.heic *.HEIC *.heif *.HEIF")])
        if paths:
            self.add_paths(list(paths))

    def add_folder(self):
        d = filedialog.askdirectory(title="フォルダを選択")
        if d:
            self.add_paths([d])

    def clear_list(self):
        self.files.clear()
        self.listbox.delete(0, "end")
        self._append_log("リストをクリアしました。\n")

    def remove_selected(self):
        sel = list(self.listbox.curselection())
        sel.reverse()
        for idx in sel:
            try:
                self.files.pop(idx)
                self.listbox.delete(idx)
            except Exception:
                pass

    def choose_out_dir(self):
        d = filedialog.askdirectory(title="出力先フォルダを選択")
        if d:
            self.out_dir = Path(d)
            self.out_dir_label.config(text=f"出力先: {self.out_dir}")

    def start(self):
        if not self.files:
            messagebox.showwarning("警告", "ファイルがありません。先に追加してください。")
            return
        fmt = self.fmt_var.get()
        jpg_q = int(self.quality.get())
        keep_exif = bool(self.keep_exif.get())
        self.start_btn.config(state="disabled")
        self.progress.config(value=0, maximum=len(self.files))
        self._append_log(f"=== 変換開始（{fmt}, JPEG品質={jpg_q}, EXIF保持={keep_exif}）===\n")

        def on_progress(done, total):
            self.progress.config(value=done)

        def on_log(msg):
            self._append_log(msg + "\n")

        def on_done():
            self._append_log("=== 完了 ===\n")
            self.start_btn.config(state="normal")
            messagebox.showinfo("完了", "変換が完了しました。")

        t = ConverterThread(self.files, self.out_dir, fmt, jpg_q, keep_exif, on_progress, on_log, on_done)
        t.start()

    def _append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")


def main():
    # DnD対応のTkルートを使用可能なら利用
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    # Windows用 HiDPI スケーリング調整
    try:
        if sys.platform.startswith("win"):
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    App(root)
    root.minsize(720, 520)
    root.mainloop()

if __name__ == "__main__":
    main()
