# heic_batch_converter_debug.py
# -*- coding: utf-8 -*-
"""
HEIC/HEIF を PNG / JPEG に一括変換する Tkinter GUI（診断ログ強化版）
- 例外のフルスタックをGUIログへ出力
- 起動時に環境情報（Pillow / pillow-heif / OS / HEIF対応状況）を表示
"""

import sys
import platform
import threading
import traceback
from pathlib import Path
from typing import List, Optional

# --- 画像処理 / HEIF対応 ---
from PIL import Image, ImageOps, UnidentifiedImageError, features  # Pillow本体
import pillow_heif  # HEIC/HEIFデコーダ（フォールバックにも使用）
pillow_heif.register_heif_opener()  # Pillow側のオープナー登録（効かない環境もあるが害はない）
Image.MAX_IMAGE_PIXELS = None       # 超高解像度でも警告で止まらないように

# pillow-heif の情報を環境ダンプ用に取得
pillow_heif_loaded = True
heif_register_ok = True
try:
    ver = getattr(pillow_heif, "__version__", "unknown")
    compilers = getattr(pillow_heif, "compiled_with", lambda: None)()
    heif_summary_text = f"pillow-heif version: {ver}; compiled_with: {compilers}"
except Exception:
    heif_summary_text = None

# --- GUI部品 ---
import tkinter as tk
from tkinter import filedialog, ttk, messagebox

# --- DnD（任意） ---
DND_AVAILABLE = False
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False

SUPPORTED_EXTS = {".heic", ".heif", ".HEIC", ".HEIF"}


# =============================================================================
# ユーティリティ
# =============================================================================

def collect_heic_files(paths: List[Path]) -> List[Path]:
    """入力パス（ファイル/フォルダ混在）から HEIC/HEIF を収集（順序維持・重複排除）"""
    files: List[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for ext in SUPPORTED_EXTS:
                files.extend(p.rglob(f"*{ext}"))
        elif p.is_file() and p.suffix in SUPPORTED_EXTS:
            files.append(p)
    seen = set()
    uniq: List[Path] = []
    for f in files:
        if f not in seen:
            uniq.append(f)
            seen.add(f)
    return uniq


def safe_output_path(src: Path, out_dir: Optional[Path], out_ext: str) -> Path:
    """出力先パスを決定（同名があれば _1, _2… を付与）"""
    base = src.stem
    dir_ = out_dir if out_dir else src.parent
    candidate = dir_ / f"{base}{out_ext}"
    idx = 1
    while candidate.exists():
        candidate = dir_ / f"{base}_{idx}{out_ext}"
        idx += 1
    return candidate


def open_image_any(path: Path):
    """HEIC/HEIF を“必ず” Pillow Image として開く。
    1) まず Image.open を試す（成功時は EXIF/ICC も取得）
    2) 失敗したら pillow_heif.open_heif → Image.frombytes で PIL 画像化
    戻り値: (pil_image, exif_bytes or None, icc_bytes or None)
    """
    # 通常ルート（環境によっては HEIC で失敗する）
    try:
        im = Image.open(path)
        exif_bytes = im.info.get("exif")
        icc = im.info.get("icc_profile")
        return im, exif_bytes, icc
    except UnidentifiedImageError:
        pass  # フォールバックへ

    # フォールバック：pillow-heif で直にHEIFを開く
    hf = pillow_heif.open_heif(path)

    # EXIFの取り出し（あれば）
    exif_bytes = None
    try:
        for md in getattr(hf, "metadata", []) or []:
            # 例: {'type': 'Exif', 'data': b'...'}
            if md.get("type", "").lower() == "exif" and md.get("data"):
                exif_bytes = md["data"]
                break
    except Exception:
        pass

    # ICCプロファイル（あれば）
    icc = None
    try:
        cp = getattr(hf, "color_profile", None)  # 例: {'type':'icc','icc_profile': b'...'}
        if isinstance(cp, dict) and cp.get("icc_profile"):
            icc = cp["icc_profile"]
    except Exception:
        pass

    # Pillow Image を生で構築
    im = Image.frombytes(hf.mode, hf.size, hf.data, "raw")
    return im, exif_bytes, icc


# =============================================================================
# 変換ワーカースレッド
# =============================================================================

class ConverterThread(threading.Thread):
    """変換をバックグラウンドで実行（UI操作はコールバック経由でメインスレッドへ）"""
    def __init__(self, files: List[Path], out_dir: Optional[Path], fmt: str,
                 jpg_quality: int, keep_exif: bool, progress_cb, log_cb, done_cb):
        super().__init__(daemon=True)
        self.files = files
        self.out_dir = out_dir
        self.fmt = fmt
        self.jpg_quality = jpg_quality
        self.keep_exif = keep_exif
        self.progress_cb = progress_cb
        self.log_cb = log_cb
        self.done_cb = done_cb

    def run(self):
        total = len(self.files)
        count = 0
        for src in self.files:
            abs_src = str(Path(src).resolve())
            try:
                self.log_cb(f"… 開始: {abs_src}")
                out_ext = ".png" if self.fmt == "PNG" else ".jpg"
                out_path = safe_output_path(src, self.out_dir, out_ext)

                # --- 画像を開く（Image.open → 失敗時 open_heif フォールバック） ---
                im, exif_bytes, icc = open_image_any(src)

                # アニメーションHEIF対策：先頭フレームを選択
                try:
                    if getattr(im, "n_frames", 1) > 1:
                        im.seek(0)
                except Exception as e:
                    self.log_cb(f"！警告: フレームseekに失敗 ({e})")

                # EXIFの回転情報を反映（縦横を正しく）
                try:
                    im = ImageOps.exif_transpose(im)
                except Exception as e:
                    self.log_cb(f"！警告: 回転補正に失敗 ({e})")

                # 保存パラメータを用意
                save_kwargs = {}
                if self.fmt == "JPEG":
                    save_kwargs["quality"] = self.jpg_quality
                    save_kwargs["optimize"] = True
                    save_kwargs["progressive"] = True
                    # 指定したい場合のみ（2=4:2:0）：save_kwargs["subsampling"] = 2
                    if icc:
                        save_kwargs["icc_profile"] = icc
                    if self.keep_exif and exif_bytes:
                        save_kwargs["exif"] = exif_bytes
                    if im.mode != "RGB":  # JPEGはRGB前提
                        im = im.convert("RGB")
                else:
                    # PNGは可逆圧縮
                    save_kwargs["optimize"] = True
                    # 必要なら ICC を入れる
                    # if icc:
                    #     save_kwargs["icc_profile"] = icc

                # 出力ディレクトリを作成して保存
                out_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    im.save(out_path, self.fmt, **save_kwargs)
                except Exception as e:
                    raise RuntimeError(f"[Save] で失敗: {e}（dest={out_path}）")

                self.log_cb(f"✔ 変換完了: {src.name} → {out_path.name}")

            except Exception:
                # フルスタックをGUIログへ
                tb = traceback.format_exc()
                self.log_cb(f"✖ エラー: {abs_src}\n{tb}")
            finally:
                count += 1
                self.progress_cb(count, total)

        self.done_cb()


# =============================================================================
# GUI本体
# =============================================================================

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("HEIC → PNG/JPEG 一括変換（診断ログ強化）")
        self.files: List[Path] = []
        self.out_dir: Optional[Path] = None

        outer = ttk.Frame(root, padding=12)
        outer.pack(fill="both", expand=True)

        # ファイルリスト
        self.listbox = tk.Listbox(outer, height=10, selectmode="extended")
        self.listbox.grid(row=0, column=0, columnspan=4, sticky="nsew", pady=(0, 8))
        self._configure_drop(self.listbox)

        # ボタン群
        ttk.Button(outer, text="ファイルを追加", command=self.add_files)\
            .grid(row=1, column=0, sticky="ew", pady=2)
        ttk.Button(outer, text="フォルダを追加", command=self.add_folder)\
            .grid(row=1, column=1, sticky="ew", pady=2)
        ttk.Button(outer, text="選択を削除", command=self.remove_selected)\
            .grid(row=1, column=2, sticky="ew", pady=2)
        ttk.Button(outer, text="リストをクリア", command=self.clear_list)\
            .grid(row=1, column=3, sticky="ew", pady=2)

        # オプション
        opts = ttk.LabelFrame(outer, text="オプション", padding=10)
        opts.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 8))
        opts.grid_columnconfigure(5, weight=1)

        ttk.Label(opts, text="出力形式:").grid(row=0, column=0, sticky="w")
        self.fmt_var = tk.StringVar(value="PNG")
        ttk.Radiobutton(opts, text="PNG（劣化なし）", value="PNG", variable=self.fmt_var)\
            .grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(opts, text="JPEG", value="JPEG", variable=self.fmt_var)\
            .grid(row=0, column=2, sticky="w")

        ttk.Label(opts, text="JPEG品質:").grid(row=0, column=3, padx=(16, 4), sticky="e")
        self.quality = tk.IntVar(value=90)
        self.quality_scale = ttk.Scale(opts, from_=60, to=100, orient="horizontal", variable=self.quality)
        self.quality_scale.grid(row=0, column=4, sticky="ew")
        self.q_label = ttk.Label(opts, text="90")
        self.q_label.grid(row=0, column=5, padx=(6, 0), sticky="w")
        self.quality.trace_add("write", lambda *args: self.q_label.config(text=str(int(self.quality.get()))))

        self.keep_exif = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="EXIFを保持（JPEGのみ）", variable=self.keep_exif)\
            .grid(row=1, column=1, columnspan=2, sticky="w", pady=(8, 0))

        self.out_dir_label = ttk.Label(opts, text="出力先: （元のフォルダ）")
        self.out_dir_label.grid(row=1, column=3, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(opts, text="出力先を選択…", command=self.choose_out_dir)\
            .grid(row=1, column=5, sticky="e", pady=(8, 0))

        # 進捗 & 開始
        self.progress = ttk.Progressbar(outer, maximum=100)
        self.progress.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(0, 8))
        self.start_btn = ttk.Button(outer, text="変換開始", command=self.start)
        self.start_btn.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(0, 8))

        # ログ
        self.log = tk.Text(outer, height=14, state="disabled")
        self.log.grid(row=5, column=0, columnspan=4, sticky="nsew")

        # レイアウト伸縮
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_columnconfigure(1, weight=1)
        outer.grid_columnconfigure(2, weight=1)
        outer.grid_columnconfigure(3, weight=1)
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_rowconfigure(5, weight=1)

        # 起動時の環境情報ダンプ
        self._dump_environment()

        if not DND_AVAILABLE:
            self._append_log("※ D&Dを使うには 'pip install tkinterdnd2' を追加インストールしてください。\n")

    def _dump_environment(self):
        """Pillow / pillow-heif / OS / HEIF対応状況など、診断に有用な情報をログ表示"""
        try:
            import PIL
            pil_ver = getattr(PIL, "__version__", "unknown")
        except Exception:
            pil_ver = "(Pillow 不明)"

        # Pillow features は環境によって 'heif' が Unknown になるので安全に判定
        try:
            heif_supported = bool(features.check("heif") or features.check("heif_decoder"))
        except Exception:
            heif_supported = False

        os_info = f"{platform.system()} {platform.release()} ({platform.version()})"
        arch_info = platform.machine()
        py_info = sys.version.replace("\n", " ")

        lines = [
            "=== 環境情報 ===",
            f"Pillow: {pil_ver}",
            f"pillow-heif 読み込み: {pillow_heif_loaded}, register_ok: {heif_register_ok}",
            f"HEIF対応（Pillow features）: {heif_supported}",
            f"OS: {os_info}",
            f"Arch: {arch_info}",
            f"Python: {py_info}",
        ]
        if heif_summary_text:
            lines.append(heif_summary_text)
        lines.append("================\n")
        for l in lines:
            self._append_log(l + ("\n" if not l.endswith("\n") else ""))

    def _configure_drop(self, widget):
        if DND_AVAILABLE:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop(self, event):
        raw = event.data
        paths: List[str] = []
        buf, in_quotes = "", False
        for ch in raw:
            if ch == '"':
                in_quotes = not in_quotes
                if not in_quotes and buf:
                    paths.append(buf); buf = ""
            elif ch == " " and not in_quotes:
                if buf:
                    paths.append(buf); buf = ""
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
        paths = filedialog.askopenfilenames(
            title="HEIC/HEIF ファイルを選択",
            filetypes=[("HEIC/HEIF", "*.heic *.HEIC *.heif *.HEIF")]
        )
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

        # ワーカーからの通知を UI スレッドにディスパッチ
        def on_progress(done, total):
            self.root.after(0, lambda: self.progress.config(value=done))

        def on_log(msg: str):
            self.root.after(0, lambda: self._append_log(msg + ("" if msg.endswith("\n") else "\n")))

        def on_done():
            def _finish():
                self._append_log("=== 完了 ===\n")
                self.start_btn.config(state="normal")
                messagebox.showinfo("完了", "変換が完了しました。")
            self.root.after(0, _finish)

        t = ConverterThread(self.files, self.out_dir, fmt, jpg_q, keep_exif, on_progress, on_log, on_done)
        t.start()

    def _append_log(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")


def main():
    # DnD対応Tkが使えれば優先
    root = TkinterDnD.Tk() if DND_AVAILABLE else tk.Tk()

    # Windows HiDPI 簡易対策
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
    root.minsize(760, 560)
    root.mainloop()


if __name__ == "__main__":
    main()
