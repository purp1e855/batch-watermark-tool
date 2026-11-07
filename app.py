from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import time
import traceback

import cv2
import numpy as np
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk
from PIL import Image, ImageTk

import core

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:
    DND_FILES = None
    TkinterDnD = None

APP_NAME = "批量水印工具"
IMAGE_TYPES = [("图片", "*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff"), ("所有文件", "*.*")]


def enable_dpi() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


class WatermarkApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(APP_NAME)
        try:
            root.tk.call("tk", "scaling", 1.0)
        except Exception:
            pass
        root.geometry("1200x660")
        root.minsize(900, 600)
        if sys.platform == "win32":
            try:
                import ctypes
                try:
                    s = ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100.0
                except Exception:
                    s = ctypes.windll.user32.GetDpiForSystem() / 96.0
                if not s or s <= 0:
                    s = 1.0
                sw = int(root.winfo_screenwidth() / s)
                sh = int(root.winfo_screenheight() / s)
                w = min(1200, sw - 30)
                h = min(660, sh - 60)
                root.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2)}")
            except Exception:
                pass
        try:
            ttk.Style().theme_use("vista")
        except Exception:
            pass

        self.folder = ""
        self.files: list[str] = []
        self.sample_path: str | None = None
        self.sample_img: Image.Image | None = None
        self.sample_bgr: np.ndarray | None = None
        self.mask: np.ndarray | None = None
        self.result_img: Image.Image | None = None
        self.show_result = False
        self.tk_img = None
        self.disp_scale = 1.0
        self.disp_ox = 0
        self.disp_oy = 0
        self.pan_x = 0
        self.pan_y = 0
        self.pan_anchor: tuple[int, int] | None = None
        self.pan_origin = (0, 0)
        self.drag_start: tuple[int, int] | None = None
        self.temp_rect = None
        self.last_pt: tuple[int, int] | None = None
        self.busy = False
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.q: queue.Queue = queue.Queue()
        self.last_out = ""
        self.out_base = ""
        self.zoom = 1.0

        self.folder_var = tk.StringVar()
        self.count_var = tk.StringVar(value="未选择文件夹")
        self.sample_var = tk.StringVar(value="未加载样图")
        self.status_var = tk.StringVar(value="就绪 · 可把文件夹拖进窗口")
        self.recursive_var = tk.BooleanVar(value=False)
        self.tool_var = tk.StringVar(value="rect")
        self.brush_var = tk.IntVar(value=28)
        self.template_var = tk.BooleanVar(value=False)
        self.method_var = tk.StringVar(value="标准 (Telea)")
        self.grow_var = tk.IntVar(value=2)
        self.text_var = tk.StringVar(value="我的水印")
        self.font_var = tk.IntVar(value=0)
        self.color_var = tk.StringVar(value="#FFFFFF")
        self.opacity_var = tk.DoubleVar(value=0.78)
        self.margin_var = tk.IntVar(value=24)
        self.logo_var = tk.StringVar(value="")
        self.logo_width_var = tk.DoubleVar(value=15.0)

        self._build()
        self.root.after(100, self._poll)
        if sys.platform == "win32":
            self.root.after(150, self._enable_tkdnd)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------------------------------------------------------- UI
    def _build(self) -> None:
        self.root.rowconfigure(1, weight=1)
        self.root.columnconfigure(0, weight=1)

        top = ttk.Frame(self.root, padding=(10, 8))
        top.grid(row=0, column=0, sticky="ew")
        ttk.Label(top, text="图片文件夹：").pack(side="left")
        ttk.Entry(top, textvariable=self.folder_var, width=42).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(top, text="选择文件夹", command=self.choose_folder).pack(side="left", padx=2)
        ttk.Button(top, text="重新扫描", command=self.rescan).pack(side="left", padx=2)
        ttk.Checkbutton(top, text="包含子文件夹", variable=self.recursive_var,
                        command=self.rescan).pack(side="left", padx=8)
        ttk.Label(top, textvariable=self.count_var).pack(side="left", padx=6)

        body = ttk.Frame(self.root, padding=(10, 0))
        body.grid(row=1, column=0, sticky="nsew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        left = ttk.Frame(body, width=390)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        left.grid_propagate(False)
        self.nb = ttk.Notebook(left)
        self.nb.pack(fill="both", expand=True)
        self.remove_tab = ttk.Frame(self.nb, padding=8)
        self.add_tab = ttk.Frame(self.nb, padding=8)
        self.nb.add(self.remove_tab, text="  去水印  ")
        self.nb.add(self.add_tab, text="  加水印  ")
        self._build_remove_tab()
        self._build_add_tab()

        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        bar = ttk.Frame(right)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ttk.Button(bar, text="适应窗口", command=self._fit_window).pack(side="left")
        ttk.Button(bar, text="放大 +", command=self.zoom_in).pack(side="left", padx=(4, 0))
        ttk.Button(bar, text="缩小 −", command=self.zoom_out).pack(side="left", padx=(2, 0))
        self.toggle_btn = ttk.Button(bar, text="查看处理效果", command=self.toggle_result)
        self.toggle_btn.pack(side="left", padx=6)
        ttk.Label(bar, text="左键画选区 · 移动工具/右键拖图 · 滚轮缩放").pack(side="left", padx=10)

        self.canvas = tk.Canvas(right, bg="#f4f4f4", highlightthickness=1, highlightbackground="#b8b8b8")
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda e: self.render())
        self.canvas.bind("<Button-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_mouse_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.canvas.bind("<MouseWheel>", self.on_wheel)
        self.canvas.bind("<ButtonPress-3>", self.on_pan_start)
        self.canvas.bind("<B3-Motion>", self.on_pan_move)
        self.canvas.bind("<ButtonRelease-3>", self.on_pan_end)

        bottom = ttk.Frame(self.root, padding=(10, 4))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(bottom, text="输出目录", command=self.choose_output_base).grid(row=0, column=1, padx=2)
        ttk.Button(bottom, text="默认目录", command=self.reset_output_base).grid(row=0, column=2, padx=2)
        ttk.Button(bottom, text="打开输出", command=self.open_output).grid(row=0, column=3, padx=2)
        ttk.Button(bottom, text="取消", command=self.cancel).grid(row=0, column=4, padx=2)
        ttk.Label(bottom, textvariable=self.status_var).grid(row=1, column=0, columnspan=5, sticky="w", pady=(4, 0))

        logframe = ttk.LabelFrame(self.root, text="处理日志", padding=4)
        logframe.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 8))
        self.log_text = tk.Text(logframe, height=4, wrap="none")
        self.log_text.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(logframe, orient="vertical", command=self.log_text.yview)
        sb.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=sb.set, state="disabled")

    def _build_remove_tab(self) -> None:
        f = self.remove_tab
        ttk.Label(f, text="1. 加载一张样图，框选水印范围", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        ttk.Button(f, text="加载样图…", command=self.choose_sample).pack(fill="x", pady=(6, 2))
        ttk.Label(f, textvariable=self.sample_var, foreground="#555").pack(anchor="w")

        ttk.Separator(f).pack(fill="x", pady=6)
        ttk.Label(f, text="2. 选择画笔工具").pack(anchor="w")
        tool = ttk.Frame(f)
        tool.pack(fill="x", pady=4)
        ttk.Radiobutton(tool, text="矩形", value="rect", variable=self.tool_var,
                        command=self._on_tool_change).pack(side="left", padx=(0, 8))
        ttk.Radiobutton(tool, text="画笔", value="brush", variable=self.tool_var,
                        command=self._on_tool_change).pack(side="left", padx=(0, 8))
        ttk.Radiobutton(tool, text="橡皮", value="eraser", variable=self.tool_var,
                        command=self._on_tool_change).pack(side="left", padx=(0, 8))
        ttk.Radiobutton(tool, text="移动", value="pan", variable=self.tool_var,
                        command=self._on_tool_change).pack(side="left")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="画笔粗细").pack(side="left")
        ttk.Scale(row, from_=4, to=100, variable=self.brush_var, orient="horizontal").pack(side="left", fill="x", expand=True, padx=6)
        ttk.Label(row, textvariable=self.brush_var, width=4).pack(side="left")
        ttk.Button(f, text="清空选区", command=self.clear_mask).pack(fill="x", pady=(4, 0))

        ttk.Separator(f).pack(fill="x", pady=6)
        ttk.Label(f, text="3. 修复设置").pack(anchor="w")
        ttk.Checkbutton(f, text="使用模板匹配（水印位置每张不同）", variable=self.template_var).pack(anchor="w", pady=2)
        row = ttk.Frame(f)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="算法").pack(side="left")
        ttk.Combobox(row, textvariable=self.method_var, state="readonly", width=18,
                     values=["标准 (Telea)", "纹理 (ShiftMap，实验)"]).pack(side="left", padx=6)
        row = ttk.Frame(f)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="边缘扩展(px)").pack(side="left")
        ttk.Spinbox(row, from_=0, to=8, textvariable=self.grow_var, width=5).pack(side="left", padx=6)
        ttk.Label(row, text="默认 2，可盖住水印毛边", foreground="#777").pack(side="left")

        ttk.Separator(f).pack(fill="x", pady=6)
        ttk.Button(f, text="预览去水印效果", command=self.preview_remove).pack(fill="x", pady=2)
        self.btn_remove = ttk.Button(f, text="开始批量去水印", command=self.start_remove)
        self.btn_remove.pack(fill="x", pady=(8, 2), ipady=4)

    def _build_add_tab(self) -> None:
        f = self.add_tab
        ttk.Label(f, text="1. 水印文字", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        ttk.Entry(f, textvariable=self.text_var).pack(fill="x", pady=4)
        row = ttk.Frame(f)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="字号").pack(side="left")
        ttk.Spinbox(row, from_=0, to=600, textvariable=self.font_var, width=6).pack(side="left", padx=4)
        ttk.Label(row, text="0=自动").pack(side="left", padx=(0, 12))
        ttk.Label(row, text="颜色").pack(side="left")
        self.color_btn = tk.Button(row, text="  ", bg=self.color_var.get(), width=4, command=self.pick_color)
        self.color_btn.pack(side="left", padx=4)
        row = ttk.Frame(f)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="不透明度").pack(side="left")
        ttk.Scale(row, from_=0.05, to=1.0, variable=self.opacity_var, orient="horizontal").pack(side="left", fill="x", expand=True, padx=6)
        ttk.Label(row, textvariable=self.opacity_var, width=5).pack(side="left")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="边距").pack(side="left")
        ttk.Spinbox(row, from_=0, to=400, textvariable=self.margin_var, width=6).pack(side="left", padx=4)
        ttk.Label(row, text="像素").pack(side="left")

        ttk.Separator(f).pack(fill="x", pady=6)
        ttk.Label(f, text="2. 或使用 Logo 图片", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        ttk.Entry(f, textvariable=self.logo_var).pack(fill="x", pady=4)
        row = ttk.Frame(f)
        row.pack(fill="x")
        ttk.Button(row, text="选择 Logo", command=self.choose_logo).pack(side="left", padx=(0, 4))
        ttk.Button(row, text="清除", command=lambda: self.logo_var.set("")).pack(side="left")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="Logo 宽度 %").pack(side="left")
        ttk.Spinbox(row, from_=3, to=60, textvariable=self.logo_width_var, width=6).pack(side="left", padx=4)
        ttk.Label(f, text="Logo 存在时优先使用 Logo，位置固定在右下角。", foreground="#777").pack(anchor="w")

        ttk.Separator(f).pack(fill="x", pady=6)
        ttk.Button(f, text="预览加水印效果", command=self.preview_add).pack(fill="x", pady=2)
        self.btn_add = ttk.Button(f, text="开始批量加水印", command=self.start_add)
        self.btn_add.pack(fill="x", pady=(8, 2), ipady=4)

    # ---------------------------------------------------------------- folder
    def choose_folder(self) -> None:
        d = filedialog.askdirectory(title="选择图片文件夹")
        if d:
            self.folder = d
            self.folder_var.set(d)
            self.rescan()

    def _enable_tkdnd(self) -> None:
        """用 tkinterdnd2 接收拖放；比子类化窗口过程稳定。"""
        if DND_FILES is None or not hasattr(self.root, "drop_target_register"):
            self.log("当前环境不支持拖放，请用“选择文件夹”按钮。")
            return
        try:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_tkdnd_drop)
        except Exception as exc:
            self.log(f"拖放初始化失败：{exc}")

    def _on_tkdnd_drop(self, event) -> None:
        try:
            paths = list(self.root.tk.splitlist(event.data))
        except Exception:
            paths = [str(event.data)]
        self._on_drop(paths)

    def _on_drop(self, paths: list[str]) -> None:
        dirs = [p for p in paths if os.path.isdir(p)]
        imgs = [p for p in paths if os.path.isfile(p)
                and os.path.splitext(p)[1].lower() in core.IMAGE_EXTS]
        if dirs:
            target = dirs[0]
        elif imgs:
            target = os.path.dirname(imgs[0])
        else:
            self.log("拖入的内容不是文件夹或图片。")
            return
        self.folder = os.path.normpath(target)
        self.folder_var.set(self.folder)
        self.rescan()
        if imgs and not dirs:
            self.load_sample(imgs[0], quiet=True)
        self.log(f"拖入文件夹：{self.folder}")

    def _current_img(self):
        if self.show_result and self.result_img is not None:
            return self.result_img
        return self.sample_img

    def _on_tool_change(self) -> None:
        self.canvas.config(cursor="fleur" if self.tool_var.get() == "pan" else "")

    def _fit_window(self) -> None:
        self.zoom = 1.0
        self.pan_x = 0
        self.pan_y = 0
        if self.tool_var.get() == "pan":
            self.tool_var.set("rect")
            self._on_tool_change()
        self.render()

    def _zoom_by(self, factor: float, anchor: tuple[int, int] | None = None) -> None:
        img = self._current_img()
        if img is None:
            return
        cw = max(self.canvas.winfo_width(), 200)
        ch = max(self.canvas.winfo_height(), 200)
        ax, ay = anchor or (cw // 2, ch // 2)
        old = self.disp_scale or 1.0
        ix = (ax - self.disp_ox) / old
        iy = (ay - self.disp_oy) / old
        new_zoom = max(0.2, min(6.0, self.zoom * factor))
        if abs(new_zoom - self.zoom) < 1e-6:
            return
        self.zoom = new_zoom
        ns = min(cw / img.width, ch / img.height, 1.0) * self.zoom
        dw, dh = img.width * ns, img.height * ns
        self.pan_x = ax - ix * ns - (cw - dw) / 2
        self.pan_y = ay - iy * ns - (ch - dh) / 2
        self.render()

    def zoom_in(self) -> None:
        self._zoom_by(1.25)

    def zoom_out(self) -> None:
        self._zoom_by(0.8)

    def on_wheel(self, event) -> str:
        if self.sample_img is None:
            return "break"
        self._zoom_by(1.15 if event.delta > 0 else 1 / 1.15, (event.x, event.y))
        return "break"

    def on_pan_start(self, event) -> None:
        if self.sample_img is None:
            return
        self.pan_anchor = (event.x, event.y)
        self.pan_origin = (self.pan_x, self.pan_y)
        self.pan_step = (0, 0)
        self.canvas.config(cursor="fleur")

    def on_pan_move(self, event) -> None:
        if not self.pan_anchor:
            return
        # 关键：anchor 必须保持按下时的位置，dx/dy 是累计位移。
        # 之前每次移动都重置 anchor，导致 pan 只保留最后一小步，松开后几乎回到原位。
        dx = event.x - self.pan_anchor[0]
        dy = event.y - self.pan_anchor[1]
        step_x = dx - self.pan_step[0]
        step_y = dy - self.pan_step[1]
        self.pan_step = (dx, dy)
        self.canvas.move("view", step_x, step_y)
        self.disp_ox += step_x
        self.disp_oy += step_y
        self.pan_x = self.pan_origin[0] + dx
        self.pan_y = self.pan_origin[1] + dy

    def on_pan_end(self, event) -> None:
        if not self.pan_anchor:
            return
        self.pan_anchor = None
        self.canvas.config(cursor="fleur" if self.tool_var.get() == "pan" else "")
        self.render()

    def choose_output_base(self) -> None:
        initial = self.out_base or self.folder or os.path.expanduser("~")
        d = filedialog.askdirectory(title="选择输出根目录（下面会自动创建 去水印/加水印）",
                                    initialdir=initial)
        if d:
            base = os.path.normpath(d)
            if os.path.basename(base) in ("去水印", "加水印"):
                base = os.path.dirname(base)
                self.log("检测到选择的是输出子文件夹，已自动改用其上级目录。")
            self.out_base = base
            self.log(f"输出根目录：{self.out_base}（会在其下创建 去水印/加水印）")

    def reset_output_base(self) -> None:
        self.out_base = ""
        self.log("输出根目录已恢复为图片文件夹。")

    def rescan(self) -> None:
        self.folder = self.folder_var.get().strip()
        self.files = []
        if self.folder and os.path.isdir(self.folder):
            if self.recursive_var.get():
                for root, dirs, names in os.walk(self.folder):
                    dirs[:] = [d for d in dirs if d not in ("去水印", "加水印")]
                    for n in names:
                        if os.path.splitext(n)[1].lower() in core.IMAGE_EXTS:
                            self.files.append(os.path.join(root, n))
            else:
                for n in os.listdir(self.folder):
                    p = os.path.join(self.folder, n)
                    if os.path.isfile(p) and os.path.splitext(n)[1].lower() in core.IMAGE_EXTS:
                        self.files.append(p)
        self.files.sort(key=lambda p: p.lower())
        self.count_var.set(f"{len(self.files)} 张" if self.files else "没有图片")
        self.sample_path = None
        self.sample_img = None
        self.sample_bgr = None
        self.mask = None
        self.result_img = None
        self.show_result = False
        self.zoom = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.sample_var.set("未加载样图")
        self.render()
        if self.files and self.sample_path is None:
            self.load_sample(self.files[0], quiet=True)

    def choose_sample(self) -> None:
        p = filedialog.askopenfilename(title="选择样图", initialdir=self.folder or None, filetypes=IMAGE_TYPES)
        if p:
            self.load_sample(p)

    def load_sample(self, path: str, quiet: bool = False) -> None:
        try:
            img = core.pil_open(path).convert("RGB")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"无法打开图片：\n{path}\n\n{exc}")
            return
        self.sample_path = path
        self.sample_img = img
        self.sample_bgr = core.pil_to_bgr(img)
        self.mask = np.zeros((img.height, img.width), np.uint8)
        self.result_img = None
        self.show_result = False
        self.zoom = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.sample_var.set(f"{os.path.basename(path)}  ({img.width}×{img.height})")
        if not quiet:
            self.log(f"加载样图：{path}")
        self.render()

    def choose_logo(self) -> None:
        p = filedialog.askopenfilename(title="选择 Logo", filetypes=IMAGE_TYPES)
        if p:
            self.logo_var.set(p)
            self.preview_add()

    def pick_color(self) -> None:
        color = colorchooser.askcolor(color=self.color_var.get(), title="选择水印颜色")[1]
        if color:
            self.color_var.set(color.upper())
            self.color_btn.configure(bg=color)

    # ---------------------------------------------------------------- canvas
    def render(self) -> None:
        self.canvas.delete("all")
        img = self._current_img()
        if img is None:
            self.canvas.create_text(max(self.canvas.winfo_width() // 2, 200),
                                    max(self.canvas.winfo_height() // 2, 150),
                                    text="选择文件夹后会自动加载第一张图片作为样图",
                                    fill="#777", font=("Microsoft YaHei UI", 12), tags="view")
            return
        cw = max(self.canvas.winfo_width(), 200)
        ch = max(self.canvas.winfo_height(), 200)
        scale = min(cw / img.width, ch / img.height, 1.0) * self.zoom
        self.disp_scale = scale
        dw, dh = max(1, round(img.width * scale)), max(1, round(img.height * scale))
        base_x, base_y = (cw - dw) // 2, (ch - dh) // 2
        ox, oy = base_x + self.pan_x, base_y + self.pan_y
        # 只要放大过（zoom>1）就允许平移；缩小到适应窗口时自动回中。
        # 拖动时最多把图片移到只剩 80px 可见，避免完全找不回来。
        allow_pan = self.zoom > 1.0001
        if allow_pan:
            ox = max(80 - dw, min(cw - 80, ox))
            oy = max(80 - dh, min(ch - 80, oy))
        else:
            ox, oy = base_x, base_y
        self.pan_x, self.pan_y = ox - base_x, oy - base_y
        self.disp_ox, self.disp_oy = ox, oy

        vx0, vy0 = max(0, ox), max(0, oy)
        vx1, vy1 = min(cw, ox + dw), min(ch, oy + dh)
        if vx1 <= vx0 or vy1 <= vy0:
            self.canvas.create_text(cw // 2, ch // 2, text="图片已移出视图，点“适应窗口”恢复",
                                    fill="#777", font=("Microsoft YaHei UI", 12), tags="view")
            return

        sx0 = max(0, int((vx0 - ox) / scale))
        sy0 = max(0, int((vy0 - oy) / scale))
        sx1 = min(img.width, int((vx1 - ox) / scale) + 2)
        sy1 = min(img.height, int((vy1 - oy) / scale) + 2)
        crop = img.crop((sx0, sy0, sx1, sy1))
        cw2 = max(1, round((sx1 - sx0) * scale))
        ch2 = max(1, round((sy1 - sy0) * scale))
        disp = crop.resize((cw2, ch2), Image.BILINEAR)

        if not self.show_result and self.nb.index("current") == 0 and self.mask is not None:
            m = Image.fromarray(self.mask).crop((sx0, sy0, sx1, sy1)).resize((cw2, ch2), Image.NEAREST)
            red = Image.new("RGBA", (cw2, ch2), (255, 0, 0, 0))
            red.putalpha(m.point(lambda a: int(a * 0.42)))
            disp = Image.alpha_composite(disp.convert("RGBA"), red).convert("RGB")

        self.tk_img = ImageTk.PhotoImage(disp)
        self.canvas.create_image(ox + sx0 * scale, oy + sy0 * scale,
                                 anchor="nw", image=self.tk_img, tags="view")

    def _to_image(self, x: int, y: int) -> tuple[int, int] | None:
        if self.sample_img is None or self.disp_scale <= 0:
            return None
        ix = int((x - self.disp_ox) / self.disp_scale)
        iy = int((y - self.disp_oy) / self.disp_scale)
        return max(0, min(self.sample_img.width - 1, ix)), max(0, min(self.sample_img.height - 1, iy))

    def on_mouse_down(self, e) -> None:
        if self.busy or self.sample_img is None or self.nb.index("current") != 0:
            return
        if self.tool_var.get() == "pan":
            self.on_pan_start(e)
            return
        p = self._to_image(e.x, e.y)
        if not p:
            return
        self.show_result = False
        if self.tool_var.get() == "rect":
            self.drag_start = p
            self.temp_rect = None
        else:
            self.last_pt = p
            self._paint(p, p)

    def on_mouse_move(self, e) -> None:
        if self.busy or self.sample_img is None or self.nb.index("current") != 0:
            return
        if self.tool_var.get() == "pan":
            self.on_pan_move(e)
            return
        p = self._to_image(e.x, e.y)
        if not p:
            return
        if self.tool_var.get() == "rect" and self.drag_start:
            x0, y0 = self.drag_start
            if self.temp_rect:
                self.canvas.delete("temp")
            cx0 = self.disp_ox + min(x0, p[0]) * self.disp_scale
            cy0 = self.disp_oy + min(y0, p[1]) * self.disp_scale
            cx1 = self.disp_ox + max(x0, p[0]) * self.disp_scale
            cy1 = self.disp_oy + max(y0, p[1]) * self.disp_scale
            self.temp_rect = self.canvas.create_rectangle(cx0, cy0, cx1, cy1, outline="#ff2222", width=2)
        elif self.tool_var.get() in ("brush", "eraser") and self.last_pt:
            self._paint(self.last_pt, p)
            self.last_pt = p

    def on_mouse_up(self, e) -> None:
        if self.tool_var.get() == "pan":
            self.on_pan_end(e)
            return
        if self.tool_var.get() == "rect" and self.drag_start and self.mask is not None:
            p = self._to_image(e.x, e.y)
            if p:
                x0, y0 = self.drag_start
                x1, y1 = p
                if abs(x1 - x0) >= 2 and abs(y1 - y0) >= 2:
                    cv2.rectangle(self.mask, (min(x0, x1), min(y0, y1)),
                                  (max(x0, x1), max(y0, y1)), 255, -1)
                    self.log("已添加矩形选区")
            self.drag_start = None
            self.temp_rect = None
            self.canvas.delete("temp")
            self.show_result = False
            self.render()
        elif self.tool_var.get() in ("brush", "eraser"):
            self.render()
        self.last_pt = None

    def _paint(self, a: tuple[int, int], b: tuple[int, int]) -> None:
        if self.mask is None:
            return
        value = 0 if self.tool_var.get() == "eraser" else 255
        r = max(1, int(self.brush_var.get()))
        if a == b:
            cv2.circle(self.mask, a, r, value, -1)
        else:
            cv2.line(self.mask, a, b, value, r * 2, cv2.LINE_AA)
        self.show_result = False
        # 画笔移动时只在画布上叠加红色笔迹，不重绘整张图；松开鼠标后再合成 mask。
        if self.tool_var.get() == "brush":
            x0 = self.disp_ox + a[0] * self.disp_scale
            y0 = self.disp_oy + a[1] * self.disp_scale
            x1 = self.disp_ox + b[0] * self.disp_scale
            y1 = self.disp_oy + b[1] * self.disp_scale
            w = max(1, int(r * 2 * self.disp_scale))
            self.canvas.create_line(x0, y0, x1, y1, fill="#ff3333",
                                    width=w, capstyle="round", tags="brush")
            if a == b:
                self.canvas.create_oval(x0 - w / 2, y0 - w / 2, x0 + w / 2, y0 + w / 2,
                                        fill="#ff3333", outline="", tags="brush")

    def clear_mask(self) -> None:
        if self.mask is not None:
            self.mask[:] = 0
        self.show_result = False
        self.result_img = None
        self.render()
        self.log("已清空选区")

    def toggle_result(self) -> None:
        if self.result_img is None:
            messagebox.showinfo(APP_NAME, "请先点击“预览”生成效果图。")
            return
        self.show_result = not self.show_result
        self.render()

    # ---------------------------------------------------------------- preview
    def _method(self) -> str:
        return "shiftmap" if "ShiftMap" in self.method_var.get() else "telea"

    def preview_remove(self) -> None:
        if not self._check_remove():
            return
        try:
            m = self.mask.copy()
            out = core.inpaint(self.sample_bgr, m, self._method(), 6, int(self.grow_var.get()))
            self.result_img = core.bgr_to_pil(out)
            self.show_result = True
            self.render()
            self.log("已生成去水印预览（只处理样图，不写文件）")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"预览失败：\n{exc}")

    def preview_add(self) -> None:
        if self.sample_img is None:
            messagebox.showinfo(APP_NAME, "请先选择图片文件夹或加载样图。")
            return
        try:
            self.result_img = self._add_to(self.sample_img)
            self.show_result = True
            self.render()
            self.log("已生成加水印预览（只处理样图，不写文件）")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"预览失败：\n{exc}")

    def _add_to(self, img: Image.Image) -> Image.Image:
        logo = self.logo_var.get().strip()
        if logo:
            return core.add_logo_watermark(img, logo, width_ratio=self.logo_width_var.get() / 100.0,
                                           opacity=float(self.opacity_var.get()),
                                           margin=int(self.margin_var.get()))
        return core.add_text_watermark(img, self.text_var.get().strip(), font_size=int(self.font_var.get()),
                                       color=self.color_var.get(), opacity=float(self.opacity_var.get()),
                                       margin=int(self.margin_var.get()))

    def _check_remove(self) -> bool:
        if self.sample_img is None or self.mask is None:
            messagebox.showinfo(APP_NAME, "请先加载样图并框选水印范围。")
            return False
        if self.mask.max() == 0:
            messagebox.showinfo(APP_NAME, "选区是空的，请先用矩形或画笔框出水印。")
            return False
        return True

    # ---------------------------------------------------------------- batch
    def _out_dir(self, kind: str) -> str:
        root = os.path.normpath(self.out_base or self.folder)
        if os.path.basename(root) in ("去水印", "加水印"):
            root = os.path.dirname(root)
        return os.path.join(root, kind)

    def _suggest_output(self) -> str:
        candidates = []
        if os.path.isdir("E:\\"):
            candidates.append(r"E:\水印输出")
        candidates.append(os.path.join(os.path.expanduser("~"), "Pictures", "水印输出"))
        for c in candidates:
            try:
                os.makedirs(c, exist_ok=True)
                probe = os.path.join(c, f".write_test_{os.getpid()}")
                with open(probe, "wb") as f:
                    f.write(b"ok")
                os.remove(probe)
                return c
            except OSError:
                continue
        return ""

    def _prepare_out(self, kind: str, allow_fallback: bool = True) -> str | None:
        out = self._out_dir(kind)
        try:
            os.makedirs(out, exist_ok=True)
            probe = os.path.join(out, f".write_test_{os.getpid()}")
            with open(probe, "wb") as f:
                f.write(b"ok")
            os.remove(probe)
            return out
        except OSError as exc:
            msg = (f"无法写入输出目录：\n{out}\n\n{exc}\n\n"
                   "Windows 不允许往这个位置写文件，通常是桌面被“受控文件夹访问”保护。\n"
                   "可以点下方“输出目录”手动换位置，或让软件改用建议目录。")
            suggest = self._suggest_output() if allow_fallback else ""
            if suggest and messagebox.askyesno(
                    APP_NAME, msg + f"\n\n是否改用：\n{suggest}\n并重试？"):
                self.out_base = suggest
                return self._prepare_out(kind, allow_fallback=False)
            if not suggest:
                messagebox.showerror(APP_NAME, msg)
            return None

    def start_remove(self) -> None:
        if self.busy:
            return
        if not self._check_remove():
            return
        if not self.files:
            messagebox.showinfo(APP_NAME, "当前文件夹里没有图片。")
            return
        out = self._prepare_out("去水印")
        if not out:
            return
        self.cancel_event.clear()
        self.busy = True
        self._set_busy(True)
        self.progress.configure(maximum=len(self.files), value=0)
        self.status_var.set("开始批量去水印…")
        kwargs = dict(files=list(self.files), mask=self.mask.copy(), sample_bgr=self.sample_bgr.copy(),
                      method=self._method(), grow=int(self.grow_var.get()),
                      template=bool(self.template_var.get()), out=out,
                      base=self.folder)
        self.worker = threading.Thread(target=self._remove_worker, kwargs=kwargs, daemon=True)
        self.worker.start()

    def start_add(self) -> None:
        if self.busy:
            return
        if not self.files:
            messagebox.showinfo(APP_NAME, "当前文件夹里没有图片。")
            return
        if not self.logo_var.get().strip() and not self.text_var.get().strip():
            messagebox.showinfo(APP_NAME, "请填写水印文字，或选择 Logo。")
            return
        out = self._prepare_out("加水印")
        if not out:
            return
        self.cancel_event.clear()
        self.busy = True
        self._set_busy(True)
        self.progress.configure(maximum=len(self.files), value=0)
        self.status_var.set("开始批量加水印…")
        kwargs = dict(files=list(self.files), out=out, base=self.folder,
                      text=self.text_var.get().strip(), color=self.color_var.get(),
                      font_size=int(self.font_var.get()), opacity=float(self.opacity_var.get()),
                      margin=int(self.margin_var.get()), logo=self.logo_var.get().strip(),
                      logo_width=self.logo_width_var.get() / 100.0)
        self.worker = threading.Thread(target=self._add_worker, kwargs=kwargs, daemon=True)
        self.worker.start()

    def _target_path(self, src: str, out_root: str, base: str) -> str:
        rel = os.path.relpath(src, base)
        dst = os.path.join(out_root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        return core.unique_path(dst)

    def _remove_worker(self, files, mask, sample_bgr, method, grow, template, out, base) -> None:
        ok = fail = 0
        bbox = core.mask_bbox(mask)
        tpl = tmask = None
        if template and bbox:
            x0, y0, x1, y1 = bbox
            tpl = sample_bgr[y0:y1, x0:x1].copy()
            tmask = mask[y0:y1, x0:x1].copy()
            if tpl.size == 0 or tmask.max() == 0:
                tpl = tmask = None
        try:
            for i, path in enumerate(files, 1):
                if self.cancel_event.is_set():
                    self.q.put(("log", "用户取消，已停止。"))
                    break
                try:
                    img = core.pil_open(path)
                    bgr = core.pil_to_bgr(img)
                    h, w = bgr.shape[:2]
                    if tpl is not None:
                        match = core.match_mask_template(bgr, tpl, tmask, (1.0,), 0.45)
                        if match:
                            score, loc, scale = match
                            m = core.place_mask(mask, (h, w), bbox, loc, scale)
                        else:
                            m = self._scale_mask(mask, w, h)
                    else:
                        m = self._scale_mask(mask, w, h)
                    outp = core.inpaint(bgr, m, method, 6, grow)
                    dst = self._target_path(path, out, base)
                    core.save_image(core.bgr_to_pil(outp), dst, 95,
                                    exif=img.info.get("exif"), icc=img.info.get("icc_profile"))
                    ok += 1
                    self.q.put(("log", f"完成：{os.path.basename(path)}"))
                except Exception as exc:
                    fail += 1
                    self.q.put(("log", f"失败：{os.path.basename(path)} — {exc}"))
                self.q.put(("progress", i, len(files), os.path.basename(path)))
        except Exception:
            self.q.put(("log", "批量任务异常：\n" + traceback.format_exc()))
        self.q.put(("done", out, ok, fail))

    def _add_worker(self, files, out, base, text, color, font_size, opacity, margin, logo, logo_width) -> None:
        ok = fail = 0
        try:
            for i, path in enumerate(files, 1):
                if self.cancel_event.is_set():
                    self.q.put(("log", "用户取消，已停止。"))
                    break
                try:
                    img = core.pil_open(path).convert("RGB")
                    if logo:
                        res = core.add_logo_watermark(img, logo, logo_width, opacity, margin)
                    else:
                        res = core.add_text_watermark(img, text, font_size, color, opacity, margin)
                    dst = self._target_path(path, out, base)
                    core.save_image(res, dst, 95, exif=img.info.get("exif"), icc=img.info.get("icc_profile"))
                    ok += 1
                    self.q.put(("log", f"完成：{os.path.basename(path)}"))
                except Exception as exc:
                    fail += 1
                    self.q.put(("log", f"失败：{os.path.basename(path)} — {exc}"))
                self.q.put(("progress", i, len(files), os.path.basename(path)))
        except Exception:
            self.q.put(("log", "批量任务异常：\n" + traceback.format_exc()))
        self.q.put(("done", out, ok, fail))

    def _scale_mask(self, mask: np.ndarray, w: int, h: int) -> np.ndarray:
        sh, sw = mask.shape[:2]
        if (sw, sh) == (w, h):
            return mask.copy()
        scale = w / sw
        if sh * scale > h:
            scale = h / sh
        nw, nh = max(1, int(round(sw * scale))), max(1, int(round(sh * scale)))
        m = cv2.resize(mask, (nw, nh), interpolation=cv2.INTER_NEAREST)
        out = np.zeros((h, w), np.uint8)
        ox, oy = w - nw, h - nh
        out[oy:oy + nh, ox:ox + nw] = m
        return out

    # ---------------------------------------------------------------- queue
    def _poll(self) -> None:
        try:
            while True:
                msg = self.q.get_nowait()
                if msg[0] == "log":
                    self.log(msg[1])
                elif msg[0] == "progress":
                    _, i, total, name = msg
                    self.progress.configure(value=i)
                    self.status_var.set(f"{i}/{total}  {name}")
                elif msg[0] == "done":
                    _, out, ok, fail = msg
                    self.busy = False
                    self.worker = None
                    self._set_busy(False)
                    self.last_out = out
                    self.status_var.set(f"完成：成功 {ok} 张，失败 {fail} 张")
                    self.log(f"任务结束：成功 {ok}，失败 {fail}，输出 {out}")
                    if ok or fail:
                        messagebox.showinfo(APP_NAME, f"处理完成。\n成功 {ok} 张，失败 {fail} 张。\n\n输出目录：\n{out}")
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.btn_remove.configure(state=state)
        self.btn_add.configure(state=state)

    def cancel(self) -> None:
        if self.busy:
            self.cancel_event.set()
            self.status_var.set("正在取消…")
            self.log("已请求取消，等待当前图片处理完。")

    def open_output(self) -> None:
        if self.last_out and os.path.isdir(self.last_out):
            os.startfile(self.last_out)
            return
        kind = "去水印" if self.nb.index("current") == 0 else "加水印"
        p = self._out_dir(kind) if (self.folder or self.out_base) else ""
        if p and os.path.isdir(p):
            os.startfile(p)
        else:
            messagebox.showinfo(APP_NAME, "还没有输出目录，先执行一次任务。")

    # ---------------------------------------------------------------- misc
    def log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", time.strftime("[%H:%M:%S] ") + text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_close(self) -> None:
        if self.busy:
            if not messagebox.askyesno(APP_NAME, "任务正在运行，确定退出吗？"):
                return
            self.cancel_event.set()
        self.root.destroy()


def main() -> None:
    enable_dpi()
    root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
    WatermarkApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()





