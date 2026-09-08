# -*- coding: utf-8 -*-
"""디지털배움터 출결증빙 생성기 — 로컬 전용 데스크톱 앱 (인터넷·한글 불필요)

설정창은 두 부분이다.
  · 공통  : 강사/보조강사, 교육장소, 교육일자(월·일), 제출자, 서명  → 모든 교시에 똑같이 들어감
  · 교시별: 교육과정명, 교육실시ID, 시작/종료 시간, 증빙사진 3장    → 교시마다 따로
"""

import base64
import calendar
import datetime
import io
import json
import os
import traceback

try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font as tkfont

from PIL import Image, ImageTk

try:
    from PIL import ImageGrab
except Exception:
    ImageGrab = None

import hwpx_builder as HB

try:
    from icon_data import ICON_PNG
except Exception:
    ICON_PNG = None

APP_NAME = "증빙 니가해"
# 설정 폴더는 예전 이름을 그대로 쓴다 (이미 저장해둔 값·서명을 잃지 않도록)
CFG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                       "출결증빙생성기")
CFG_FILE = os.path.join(CFG_DIR, "config.json")
SIG_FILE = os.path.join(CFG_DIR, "signature.png")
SIG_SRC = os.path.join(CFG_DIR, "signature_src.png")

# ---- 양식 좌표 (원본 렌더링에서 실측, 단위 mm) --------------------------
PAGE_W, PAGE_H = 297.0, 210.0
TBL_L, TBL_R = 20.3, 272.9
TBL_W = TBL_R - TBL_L
COL_F = [0.0, 0.07373, 0.34380, 0.47545, 0.60907, 0.71912, 1.0]
Y_TITLE = 35.55
Y_SUB = 48.15
Y_A1, Y_A2 = 50.8, 61.8
Y_B1, Y_B2 = 67.6, 73.4
Y_B3, Y_B4 = 151.1, 162.7
Y_Q, Y_SUBM = 153.2, 159.1
Y_SIG = 154.2
SIG_H_MM = 7.95
Y_N1, Y_N2 = 168.4, 172.7
THIN, THICK = 0.12, 0.40

Q_SEGS = [
    ("1. 출석 인원수 모두 나왔나요? (", 0), ("네", 1),
    (",아니오)  / 2. 강사, 보조강사가 사진에 나왔나요? (", 0), ("네", 1),
    (",아니오)　/ 3. 디지털배움터 교육인지 알 수 있나요? (", 0), ("네", 1),
    (",아니오)", 0),
]
NOTE1 = "　※ 2일 이상 교육인 경우, 교육일자별로 각각 작성하여 증빙 제출  (예 : 2일 교육인 경우 해당 양식 2장 제출 필요)"
NOTE2 = "　※ 교육인원이 많아 사진 한 장에 모두 담기 어려운 경우는 출석 인원이 모두 안 찍혀도 무방하나 수기 출석부나 시스템 출석 기록 등 추가 증빙 필요"
PHOTO_CAPS = [("전", "(교육 시작 후 20분 이내)"), ("중", "(교육 중간)"),
              ("후", "(교육 종료 전 20분 이내)")]
SLOT_NAMES = ["전", "중", "후"]

IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff")

# 자주 쓰는 조합. course 는 HB.COURSES 순번(0=에듀버스1, 1=에듀버스2, 2=에듀버스3)
PRESETS = [
    ("제대병원", {
        "place": "제주특별자치도 제주시 아란13길 15 (아라일동) 제대병원 1층 로비",
        "periods": [
            {"course": 0, "sh": "9", "sm": "30", "eh": "10", "em": "30"},
            {"course": 1, "sh": "10", "sm": "30", "eh": "11", "em": "30"},
            {"course": 2, "sh": "11", "sm": "30", "eh": "13", "em": "00"},
        ],
    }),
]

COMMON_KEYS = ["lead", "lead_name", "asst", "asst_name", "place", "submitter"]
PERIOD_KEYS = ["course", "eduid", "sh", "sm", "eh", "em"]

# 원본 문서 글꼴은 "휴먼명조". 없으면 비슷한 명조 계열로 대체한다.
DOC_FONT_CHAIN = ["휴먼명조", "HY신명조", "HCI Poppy", "한컴바탕", "함초롬바탕",
                  "바탕", "Batang", "궁서", "맑은 고딕"]
DOC_FONT = "바탕"
UI_FONT = "맑은 고딕"
FILL_HEAD = "#F2F2F2"
C_ACC = "#1f6feb"
C_ACC_W = "#e8f0fe"
C_MUTED = "#6b7788"
C_LINE = "#d7dde6"


# =======================================================================
#  이미지 처리
# =======================================================================
def fit_photo(im):
    """사진칸 비율보다 가로로 넓으면 가운데 기준으로 좌우를 잘라낸다."""
    im = im.convert("RGB")
    w, h = im.size
    if w / h > HB.CELL_ASPECT:
        nw = int(round(h * HB.CELL_ASPECT))
        x = (w - nw) // 2
        im = im.crop((x, 0, x + nw, h))
        w, h = im.size
    if h > 1500:
        im = im.resize((max(1, int(round(w * 1500.0 / h))), 1500), Image.LANCZOS)
    return im


def make_signature(im, remove_bg=True):
    """흰 배경을 투명하게 만들고 여백을 잘라낸다."""
    im = im.convert("RGBA")
    w, h = im.size
    if w > 1000:
        im = im.resize((1000, max(1, int(round(h * 1000.0 / w)))), Image.LANCZOS)
    if not remove_bg:
        return im
    lum = im.convert("L")
    alpha = lum.point(lambda v: 0 if v > 205 else (255 if v < 130 else int(255 * (205 - v) / 75)))
    old = im.getchannel("A")
    alpha = Image.composite(alpha, Image.new("L", im.size, 0),
                            old.point(lambda v: 255 if v > 8 else 0))
    out = im.convert("RGB")
    out.putalpha(alpha)
    box = alpha.point(lambda v: 255 if v > 12 else 0).getbbox()
    if box:
        p = 3
        box = (max(0, box[0] - p), max(0, box[1] - p),
               min(out.size[0], box[2] + p), min(out.size[1], box[3] + p))
        out = out.crop(box)
    return out


def load_image(path):
    im = Image.open(path)
    im.load()
    return im


# =======================================================================
#  달력 위젯 (월·일만 고름 — 모든 교시 공통)
# =======================================================================
class Calendar(tk.Frame):
    def __init__(self, master, on_pick):
        tk.Frame.__init__(self, master, bg="white", highlightbackground=C_LINE,
                          highlightthickness=1)
        self.on_pick = on_pick
        today = datetime.date.today()
        self.year, self.month = today.year, today.month
        self.sel = (today.year, today.month, today.day)

        nav = tk.Frame(self, bg="white")
        nav.pack(fill="x", padx=6, pady=(5, 2))
        tk.Button(nav, text="‹", width=2, relief="flat", bg="white",
                  command=lambda: self.shift(-1)).pack(side="left")
        self.lbl = tk.Label(nav, text="", bg="white", font=(UI_FONT, 10, "bold"))
        self.lbl.pack(side="left", expand=True)
        tk.Button(nav, text="›", width=2, relief="flat", bg="white",
                  command=lambda: self.shift(1)).pack(side="right")

        self.grid_f = tk.Frame(self, bg="white")
        self.grid_f.pack(padx=6, pady=(0, 6))
        for i, d in enumerate("일월화수목금토"):
            fg = "#d33" if i == 0 else ("#2a5fbf" if i == 6 else C_MUTED)
            tk.Label(self.grid_f, text=d, width=3, bg="white", fg=fg,
                     font=(UI_FONT, 8)).grid(row=0, column=i)
        self.cells = []
        self.draw()

    def shift(self, n):
        m = self.month + n
        self.year += (m - 1) // 12
        self.month = (m - 1) % 12 + 1
        self.draw()

    def set(self, y, m, d):
        self.sel = (y, m, d)
        self.year, self.month = y, m
        self.draw()

    def draw(self):
        self.lbl.config(text="%d년 %d월" % (self.year, self.month))
        for w in self.cells:
            w.destroy()
        self.cells = []
        first = (datetime.date(self.year, self.month, 1).weekday() + 1) % 7
        ndays = calendar.monthrange(self.year, self.month)[1]
        r, c = 1, first
        for d in range(1, ndays + 1):
            selected = self.sel == (self.year, self.month, d)
            fg = "#d33" if c == 0 else ("#2a5fbf" if c == 6 else "#1c2530")
            b = tk.Button(self.grid_f, text=str(d), width=3, relief="flat", bd=0,
                          font=(UI_FONT, 8),
                          bg=C_ACC if selected else "white",
                          fg="white" if selected else fg,
                          activebackground="#eef3fb",
                          command=lambda dd=d: self.pick(dd))
            b.grid(row=r, column=c, sticky="nsew", padx=1, pady=1)
            self.cells.append(b)
            c += 1
            if c == 7:
                c = 0
                r += 1

    def pick(self, d):
        self.sel = (self.year, self.month, d)
        self.draw()
        self.on_pick(*self.sel)


# =======================================================================
#  사진 자르기 창
# =======================================================================
class CropDialog(tk.Toplevel):
    """가운데 고정된 틀 안으로 사진을 옮기고 확대해서 자른다.

    틀의 가로:세로는 사진칸 비율(1.08:1)을 넘지 않는다. 세로 사진은
    좁은 비율을 골라 그대로 쓰면 된다.
    """

    VW, VH = 760, 470
    RATIOS = [("칸에 꽉", HB.CELL_ASPECT), ("1 : 1", 1.0),
              ("3 : 4", 0.75), ("원본 비율", None)]

    def __init__(self, app, image, saved, on_ok):
        tk.Toplevel.__init__(self, app, bg="white")
        self.title("사진 자르기")
        self.resizable(False, False)
        self.transient(app)
        self.im = image
        self.on_ok = on_ok
        self.result = None

        W, H = image.size
        self.ratio_key = tk.IntVar(value=0 if W / H >= HB.CELL_ASPECT else 3)
        if saved and saved.get("ratio") is not None:
            self.ratio_key.set(saved["ratio"])

        self.cv = tk.Canvas(self, width=self.VW, height=self.VH, bg="#20242b",
                            highlightthickness=0, cursor="fleur")
        self.cv.pack(padx=14, pady=(14, 8))

        bar = tk.Frame(self, bg="white")
        bar.pack(fill="x", padx=14)
        tk.Label(bar, text="비율", bg="white", fg=C_MUTED,
                 font=(UI_FONT, 8)).pack(side="left", padx=(0, 6))
        for n, (txt, _) in enumerate(self.RATIOS):
            tk.Radiobutton(bar, text=txt, variable=self.ratio_key, value=n, bg="white",
                           font=(UI_FONT, 8), activebackground="white",
                           command=self.on_ratio).pack(side="left", padx=(0, 6))
        tk.Label(bar, text="확대", bg="white", fg=C_MUTED,
                 font=(UI_FONT, 8)).pack(side="left", padx=(14, 4))
        self.zvar = tk.DoubleVar(value=0.0)
        ttk.Scale(bar, from_=0.0, to=1.0, variable=self.zvar, length=150,
                  command=lambda v: self.on_slider()).pack(side="left")
        tk.Button(bar, text="처음으로", font=(UI_FONT, 8), relief="solid", bd=1,
                  bg="white", command=self.reset).pack(side="left", padx=(10, 0))

        tip = tk.Label(self, bg="white", fg="#aab2bd", font=(UI_FONT, 8), anchor="w",
                       text="사진을 끌어 위치를 맞추고, 휠을 굴리거나 확대 막대로 크기를 조절하세요. "
                            "밝은 틀 안쪽만 양식에 들어갑니다.")
        tip.pack(fill="x", padx=14, pady=(6, 0))

        btn = tk.Frame(self, bg="white")
        btn.pack(fill="x", padx=14, pady=(10, 14))
        tk.Button(btn, text="적용", bg=C_ACC, fg="white", bd=0, font=(UI_FONT, 10, "bold"),
                  padx=22, pady=6, activebackground="#1a5fd0", activeforeground="white",
                  command=self.ok).pack(side="right")
        tk.Button(btn, text="취소", bg="white", fg=C_MUTED, bd=1, relief="solid",
                  font=(UI_FONT, 9), padx=16, pady=5,
                  command=self.destroy).pack(side="right", padx=(0, 8))

        self.cv.bind("<Button-1>", self.press)
        self.cv.bind("<B1-Motion>", self.drag)
        self.cv.bind("<MouseWheel>", self.wheel)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self.ok())

        self.set_box()
        if saved and saved.get("zoom"):
            self.zoom = max(self.zmin, min(self.zmin * 6, saved["zoom"]))
            self.cx, self.cy = saved["cx"], saved["cy"]
            self.clamp()
        self.sync_slider()
        self.render()
        self.update_idletasks()
        x = app.winfo_rootx() + (app.winfo_width() - self.winfo_width()) // 2
        y = app.winfo_rooty() + (app.winfo_height() - self.winfo_height()) // 3
        self.geometry("+%d+%d" % (max(0, x), max(0, y)))
        self.grab_set()

    # ---- 틀 / 배율 ----
    def cur_ratio(self):
        ar = self.RATIOS[self.ratio_key.get()][1]
        if ar is None:
            ar = self.im.size[0] / float(self.im.size[1])
        return min(ar, HB.CELL_ASPECT)

    def set_box(self, keep=False):
        ar = self.cur_ratio()
        bh = min(self.VH - 40, (self.VW - 40) / ar)
        self.box_w, self.box_h = bh * ar, bh
        self.bx = (self.VW - self.box_w) / 2.0
        self.by = (self.VH - self.box_h) / 2.0
        W, H = self.im.size
        self.zmin = max(self.box_w / W, self.box_h / H)
        if not keep:
            self.zoom = self.zmin
            self.cx, self.cy = W / 2.0, H / 2.0
        else:
            self.zoom = max(self.zmin, self.zoom)
        self.clamp()

    def clamp(self):
        W, H = self.im.size
        bw, bh = self.box_w / self.zoom, self.box_h / self.zoom
        self.cx = max(bw / 2.0, min(W - bw / 2.0, self.cx))
        self.cy = max(bh / 2.0, min(H - bh / 2.0, self.cy))

    def sync_slider(self):
        span = self.zmin * 5.0
        self.zvar.set(0.0 if span <= 0 else (self.zoom - self.zmin) / span)

    def on_ratio(self):
        self.set_box()
        self.sync_slider()
        self.render()

    def on_slider(self):
        z = self.zmin + self.zvar.get() * self.zmin * 5.0
        if abs(z - self.zoom) > 1e-6:
            self.zoom = z
            self.clamp()
            self.render()

    def wheel(self, e):
        self.zoom = max(self.zmin, min(self.zmin * 6.0,
                                       self.zoom * (1.12 if e.delta > 0 else 1 / 1.12)))
        self.clamp()
        self.sync_slider()
        self.render()

    def reset(self):
        self.set_box()
        self.sync_slider()
        self.render()

    # ---- 마우스로 옮기기 ----
    def press(self, e):
        self.grab = (e.x, e.y, self.cx, self.cy)

    def drag(self, e):
        gx, gy, cx0, cy0 = self.grab
        self.cx = cx0 - (e.x - gx) / self.zoom
        self.cy = cy0 - (e.y - gy) / self.zoom
        self.clamp()
        self.render()

    # ---- 그리기 ----
    def render(self):
        z, W, H = self.zoom, self.im.size[0], self.im.size[1]
        x0 = self.cx - self.VW / (2.0 * z)
        y0 = self.cy - self.VH / (2.0 * z)
        sx0, sy0 = max(0, int(x0)), max(0, int(y0))
        sx1 = min(W, int(x0 + self.VW / z) + 1)
        sy1 = min(H, int(y0 + self.VH / z) + 1)
        base = Image.new("RGB", (self.VW, self.VH), (32, 36, 43))
        if sx1 > sx0 and sy1 > sy0:
            part = self.im.crop((sx0, sy0, sx1, sy1))
            nw = max(1, int(round((sx1 - sx0) * z)))
            nh = max(1, int(round((sy1 - sy0) * z)))
            part = part.resize((nw, nh), Image.LANCZOS)
            base.paste(part, (int(round((sx0 - x0) * z)), int(round((sy0 - y0) * z))))
        self.view = ImageTk.PhotoImage(base)
        c = self.cv
        c.delete("all")
        c.create_image(0, 0, image=self.view, anchor="nw")
        bx, by, bw, bh = self.bx, self.by, self.box_w, self.box_h
        for a in ((0, 0, self.VW, by), (0, by + bh, self.VW, self.VH),
                  (0, by, bx, by + bh), (bx + bw, by, self.VW, by + bh)):
            c.create_rectangle(*a, fill="#000000", stipple="gray50", outline="")
        c.create_rectangle(bx, by, bx + bw, by + bh, outline="#ffffff", width=2)
        for f in (1 / 3.0, 2 / 3.0):
            c.create_line(bx + bw * f, by, bx + bw * f, by + bh, fill="#ffffff",
                          width=1, stipple="gray50")
            c.create_line(bx, by + bh * f, bx + bw, by + bh * f, fill="#ffffff",
                          width=1, stipple="gray50")
        r = self.result_rect()
        c.create_text(bx + 6, by + 5, anchor="nw", fill="#ffffff", font=(UI_FONT, 8),
                      text="%d × %d" % (r[2] - r[0], r[3] - r[1]))

    def result_rect(self):
        bw, bh = self.box_w / self.zoom, self.box_h / self.zoom
        W, H = self.im.size
        x0 = max(0, min(W - bw, self.cx - bw / 2.0))
        y0 = max(0, min(H - bh, self.cy - bh / 2.0))
        return (int(round(x0)), int(round(y0)),
                int(round(min(W, x0 + bw))), int(round(min(H, y0 + bh))))

    def ok(self):
        r = self.result_rect()
        im = self.im.crop(r).convert("RGB")
        w, h = im.size
        if h > 1500:
            im = im.resize((max(1, int(round(w * 1500.0 / h))), 1500), Image.LANCZOS)
        state = {"ratio": self.ratio_key.get(), "zoom": self.zoom,
                 "cx": self.cx, "cy": self.cy}
        self.destroy()
        self.on_ok(im, state)


# =======================================================================
#  접이식 묶음 위젯
# =======================================================================
class Section(tk.Frame):
    """머리글을 누르면 내용이 접히고 펴지는 상자."""

    def __init__(self, master, title, key, app, big=False, opened=True):
        tk.Frame.__init__(self, master, bg="white")
        self.app = app
        self.key = key
        self.opened = opened
        hbg = "#eef3fb" if big else "#f4f6f8"
        self.head = tk.Frame(self, bg=hbg, cursor="hand2")
        self.head.pack(fill="x")
        self.arrow = tk.Label(self.head, text="▾", bg=hbg, fg=C_ACC,
                              font=(UI_FONT, 9), padx=8, pady=6, cursor="hand2")
        self.arrow.pack(side="left")
        self.ttl = tk.Label(self.head, text=title, bg=hbg,
                            fg=C_ACC if big else "#1c2530",
                            font=(UI_FONT, 10 if big else 9, "bold"),
                            cursor="hand2")
        self.ttl.pack(side="left")
        self.note = tk.Label(self.head, text="", bg=hbg, fg=C_MUTED,
                             font=(UI_FONT, 8), cursor="hand2")
        self.note.pack(side="left", padx=6)
        for w in (self.head, self.arrow, self.ttl, self.note):
            w.bind("<Button-1>", lambda e: self.toggle())
        self.body = tk.Frame(self, bg="white")
        if opened:
            self.body.pack(fill="x", padx=(10 if big else 14), pady=(6, 8))
        else:
            self.arrow.config(text="▸")

    def toggle(self):
        self.opened = not self.opened
        if self.opened:
            self.body.pack(fill="x", padx=12, pady=(6, 8))
            self.arrow.config(text="▾")
        else:
            self.body.pack_forget()
            self.arrow.config(text="▸")
        self.app.open_state[self.key] = self.opened

    def set_open(self, on):
        if on != self.opened:
            self.toggle()

    def clear(self):
        for w in self.body.winfo_children():
            w.destroy()


# =======================================================================
#  본체
# =======================================================================
class App(tk.Tk):
    def __init__(self):
        tk.Tk.__init__(self)
        self.title(APP_NAME)
        self.geometry("1380x880")
        self.minsize(1140, 720)
        self.configure(bg="#eef1f5")
        self.set_app_icon()

        self.signature = None
        self._sig_raw = None
        self._loading = False
        self._imgcache = {}
        self._fonts = {}
        self._thumbs = {}
        self.slot_lbl = {}
        self.num_btn = []
        self.sections = {}
        self.open_state = {}
        self.last_dir = os.path.expanduser("~")
        self.cur = 0                       # 미리보기로 보고 있는 교시
        self.photo_mode = 3                # 교시당 사진 수 (3장 또는 2장)
        self.sig_scale = 1.0               # 서명 크기 배율
        self.sig_dx = 0                    # 서명 좌우 이동(HWPUNIT)
        self.sig_dy = 0                    # 서명 위아래 이동(HWPUNIT)
        self._sig_mode = None

        today = datetime.date.today()
        self.date = [today.year, today.month, today.day]

        self.v = {
            "lead": tk.BooleanVar(value=False), "lead_name": tk.StringVar(),
            "asst": tk.BooleanVar(value=True), "asst_name": tk.StringVar(),
            "place": tk.StringVar(), "submitter": tk.StringVar(),
            "sigbg": tk.BooleanVar(value=True),
        }
        self.periods = [self.new_period()]

        self.resolve_font()
        self.build_ui()
        self.load_config()
        for var in self.v.values():
            var.trace_add("write", lambda *a: self.on_change())
        self.bind_all("<Control-v>", self.on_paste)
        self.bind_all("<Control-V>", self.on_paste)
        self.after(120, self.redraw)
        self.after(300, self.enable_file_drop)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def set_app_icon(self):
        if not ICON_PNG:
            return
        try:
            im = Image.open(io.BytesIO(base64.b64decode(ICON_PNG)))
            self._icon_img = ImageTk.PhotoImage(im)
            self.iconphoto(True, self._icon_img)
        except Exception:
            pass

    def resolve_font(self):
        global DOC_FONT
        fams = set(tkfont.families(self))
        for name in DOC_FONT_CHAIN:
            if name in fams:
                DOC_FONT = name
                break

    # ---------------- 교시 ----------------
    def new_period(self, base=None, index=None):
        # 교시 순서대로 에듀버스1 -> 2 -> 3 (4교시부터는 마지막 과정)
        idx = len(getattr(self, "periods", [])) if index is None else index
        course = HB.COURSES[min(idx, len(HB.COURSES) - 1)]
        dur = HB.course_minutes(course)
        start = HB.DEFAULT_START
        if base is not None:                 # 앞 교시가 끝난 시각부터 이어서
            try:
                start = int(base["v"]["eh"].get()) * 60 + int(base["v"]["em"].get())
            except (TypeError, ValueError):
                pass
        if start + dur > 24 * 60:
            start = HB.DEFAULT_START
        end = start + dur
        d = {"course": course,
             "eduid": base["v"]["eduid"].get() if base is not None else "",
             "sh": str(start // 60), "sm": "%02d" % (start % 60),
             "eh": str(end // 60), "em": "%02d" % (end % 60)}
        p = {"v": {k: tk.StringVar(value=d[k]) for k in PERIOD_KEYS},
             "photos": [None, None, None], "names": ["", "", ""],
             "origs": [None, None, None], "crops": [None, None, None],
             "auto": False}
        for var in p["v"].values():
            var.trace_add("write", lambda *a: self.on_change())
        return p

    def add_period(self, silent=False):
        self.periods.append(self.new_period(self.periods[-1]))
        self.cur = len(self.periods) - 1
        if not silent:
            self.rebuild_periods()
            self.redraw()

    def del_period(self, i=None):
        if len(self.periods) <= 1:
            return
        i = self.cur if i is None else i
        if not messagebox.askyesno(APP_NAME, "%d교시를 지울까요?\n"
                                             "이 교시의 사진도 함께 지워집니다." % (i + 1)):
            return
        del self.periods[i]
        self.cur = min(self.cur, len(self.periods) - 1)
        self.rebuild_periods()
        self.redraw()

    def set_cur(self, i):
        if i == self.cur or not (0 <= i < len(self.periods)):
            return
        self.cur = i
        self.mark_current()
        self.redraw()

    @property
    def photos(self):
        return self.periods[self.cur]["photos"]

    def period_state(self, i):
        p = self.periods[i]
        st = {k: self.v[k].get() for k in COMMON_KEYS}
        st["month"], st["day"] = self.date[1], self.date[2]
        st["course"] = p["v"]["course"].get()
        st["eduid"] = p["v"]["eduid"].get()
        for k in ("sh", "sm", "eh", "em"):
            try:
                st[k] = int(p["v"][k].get())
            except (TypeError, ValueError):
                st[k] = 0
        return st

    def state(self):
        return self.period_state(self.cur)

    # ---------------- 화면 구성 ----------------
    def build_ui(self):
        left = tk.Frame(self, bg="white", width=422)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        hd = tk.Frame(left, bg="white")
        hd.pack(fill="x", padx=16, pady=(12, 8))
        tk.Label(hd, text=APP_NAME, bg="white", font=(UI_FONT, 12, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(hd, text="디지털배움터 출결증빙 · 한글(HWP)·인터넷 없이 .hwpx 를 만듭니다", bg="white",
                 fg=C_MUTED, font=(UI_FONT, 8), anchor="w").pack(fill="x")
        ttk.Separator(left).pack(fill="x")

        wrap = tk.Frame(left, bg="white")
        wrap.pack(fill="both", expand=True)
        cv = tk.Canvas(wrap, bg="white", highlightthickness=0, width=404)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        cv.pack(side="left", fill="both", expand=True)
        form = tk.Frame(cv, bg="white")
        cv.create_window((0, 0), window=form, anchor="nw", width=388)
        form.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind_all("<MouseWheel>", lambda e: cv.yview_scroll(int(-e.delta / 120), "units"))
        self.form = form
        self.formcv = cv

        self.build_presets(form)
        self.build_common(form)
        self.build_periods(form)
        tk.Frame(form, bg="white", height=18).pack()

        ft = tk.Frame(left, bg="#fafbfc")
        ft.pack(fill="x")
        ttk.Separator(ft).pack(fill="x")
        self.fname_lbl = tk.Label(ft, text="", bg="#fafbfc", fg=C_MUTED,
                                  font=(UI_FONT, 8), wraplength=384)
        self.fname_lbl.pack(pady=(8, 6))
        self.save_all_btn = tk.Button(ft, text="전체 교시 한번에 저장", bg=C_ACC,
                                      fg="white", bd=0, font=(UI_FONT, 11, "bold"),
                                      pady=8, activebackground="#1a5fd0",
                                      activeforeground="white", command=self.save_all)
        self.save_all_btn.pack(fill="x", padx=16, pady=(0, 6))
        tk.Button(ft, text="보고 있는 교시 저장", bg="white", fg=C_ACC, bd=1,
                  relief="solid", font=(UI_FONT, 9), pady=5,
                  command=self.save).pack(fill="x", padx=16, pady=(0, 12))

        right = tk.Frame(self, bg="#eef1f5")
        right.pack(side="left", fill="both", expand=True)
        self.tabbar = tk.Frame(right, bg="#dfe3e9", height=36)
        self.tabbar.pack(fill="x")
        self.tabbar.pack_propagate(False)
        self.cv = tk.Canvas(right, bg="#eef1f5", highlightthickness=0)
        self.cv.pack(fill="both", expand=True)
        self.cv.bind("<Configure>", lambda e: self.redraw())
        self.cv.bind("<Motion>", self.canvas_motion)
        self.cv.bind("<Button-1>", self.canvas_press)
        self.cv.bind("<B1-Motion>", self.canvas_drag)
        self.cv.bind("<ButtonRelease-1>", self.canvas_release)
        self.cv.bind("<Double-Button-1>", self.canvas_double)
        self.cv.bind("<MouseWheel>", self.canvas_wheel)

        self.rebuild_periods()

    def sec(self, parent, key, title, big=False, opened=True):
        s = Section(parent, title, key, self, big=big,
                    opened=self.open_state.get(key, opened))
        s.pack(fill="x", padx=(0 if big else 14), pady=(8 if big else 4, 0))
        self.sections[key] = s
        self.open_state.setdefault(key, s.opened)
        return s

    def hint(self, parent, text):
        tk.Label(parent, text=text, bg="white", fg=C_MUTED, font=(UI_FONT, 8),
                 wraplength=330, justify="left", anchor="w").pack(fill="x", pady=(4, 0))

    def row_label(self, parent, i):
        """묶음 안에서 '1교시' 같은 줄 이름표."""
        lb = tk.Label(parent, text="%d교시" % (i + 1), bg="white", width=6,
                      anchor="w", font=(UI_FONT, 9), cursor="hand2")
        lb.bind("<Button-1>", lambda e, i=i: self.set_cur(i))
        return lb

    # ---------- 프리셋 ----------
    def build_presets(self, f):
        row = tk.Frame(f, bg="white")
        row.pack(fill="x", padx=16, pady=(10, 2))
        tk.Label(row, text="프리셋", bg="white", fg=C_MUTED,
                 font=(UI_FONT, 8)).pack(side="left", padx=(0, 8))
        for name, spec in PRESETS:
            tk.Button(row, text=name, bg=C_ACC_W, fg=C_ACC, bd=1, relief="solid",
                      font=(UI_FONT, 9, "bold"), padx=12, pady=3,
                      activebackground="#dbe7fb",
                      command=lambda sp=spec, nm=name: self.apply_preset(nm, sp)).pack(
                side="left", padx=(0, 6))
        tk.Label(f, text="누르면 교육장소와 교시별 과정명·시간이 한 번에 채워집니다.",
                 bg="white", fg="#aab2bd", font=(UI_FONT, 8), anchor="w").pack(
            fill="x", padx=16)

    def apply_preset(self, name, spec):
        want = len(spec["periods"])
        if len(self.periods) > want:
            msg = "%s 프리셋을 적용하면 교시가 %d개로 맞춰집니다." % (name, want)
            msg += chr(10) + "%d교시부터는 입력값과 사진이 함께 지워집니다. 계속할까요?" % (want + 1)
            if not messagebox.askyesno(APP_NAME, msg):
                return
        self.v["place"].set(spec["place"])
        while len(self.periods) > want:
            self.periods.pop()
        while len(self.periods) < want:
            self.add_period(silent=True)
        for i, ps in enumerate(spec["periods"]):
            v = self.periods[i]["v"]
            v["course"].set(HB.COURSES[ps["course"]])
            for k in ("sh", "sm", "eh", "em"):
                v[k].set(ps[k])
        self.cur = min(self.cur, len(self.periods) - 1)
        self.rebuild_periods()
        self.redraw()

    # ---------- 공통 ----------
    def build_common(self, f):
        top = self.sec(f, "common", "공통 항목  ·  모든 교시에 똑같이 들어감", big=True)
        c = top.body

        s = self.sec(c, "c_teacher", "강사 / 보조강사")
        for key, name, label in (("lead", "lead_name", "강사"),
                                 ("asst", "asst_name", "보조강사")):
            row = tk.Frame(s.body, bg="white")
            row.pack(fill="x", pady=2)
            tk.Checkbutton(row, text=label, variable=self.v[key], bg="white",
                           font=(UI_FONT, 9), activebackground="white",
                           width=7, anchor="w").pack(side="left")
            tk.Entry(row, textvariable=self.v[name], font=(UI_FONT, 10),
                     relief="solid", bd=1).pack(side="left", fill="x",
                                                expand=True, ipady=3)
        self.hint(s.body, "체크한 항목만 양식에 기재됩니다.  예)  보조강사: 홍길동")

        s = self.sec(c, "c_place", "교육장소")
        tk.Entry(s.body, textvariable=self.v["place"], font=(UI_FONT, 10),
                 relief="solid", bd=1).pack(fill="x", ipady=3)
        self.hint(s.body, "예) 제주특별자치도 제주시 아란13길 15 (아라일동) 제대병원 1층 로비")

        s = self.sec(c, "c_date", "교육일자 (월 · 일)")
        self.cal = Calendar(s.body, self.on_date)
        self.cal.pack(fill="x")
        self.hint(s.body, "시작 / 종료 시각은 교시별로 따로 정합니다.")

        s = self.sec(c, "c_submitter", "제출자")
        tk.Entry(s.body, textvariable=self.v["submitter"], font=(UI_FONT, 10),
                 relief="solid", bd=1).pack(fill="x", ipady=3)
        self.hint(s.body, "비워두면 위에서 체크한 강사/보조강사 이름이 사용됩니다.")

        s = self.sec(c, "c_sign", "서명 이미지")
        self.sig_lbl = tk.Label(s.body, bg="#f4f6f8", height=4, cursor="hand2",
                                text="클릭해서 서명 이미지 불러오기 (한 번 등록하면 저장됨)",
                                fg=C_MUTED, font=(UI_FONT, 8), relief="solid", bd=1)
        self.sig_lbl.pack(fill="x")
        self.sig_lbl.bind("<Button-1>", lambda e: self.pick_sig())
        r = tk.Frame(s.body, bg="white")
        r.pack(fill="x", pady=(4, 0))
        tk.Checkbutton(r, text="흰 배경 자동 제거", variable=self.v["sigbg"], bg="white",
                       font=(UI_FONT, 9), activebackground="white",
                       command=self.reload_sig).pack(side="left")
        tk.Button(r, text="삭제", font=(UI_FONT, 8), relief="solid", bd=1, bg="white",
                  command=self.clear_sig).pack(side="right")
        self.hint(s.body, "제출자 이름 옆 (서명) 자리에 배경 없이 겹쳐 찍힙니다.")

    # ---------- 교시별 ----------
    def build_periods(self, f):
        top = self.sec(f, "period", "교시별 항목  ·  같은 항목끼리 모아 교시마다 입력", big=True)
        c = top.body

        self.sec_course = self.sec(c, "p_course", "교육과정명")
        self.sec_eduid = self.sec(c, "p_eduid", "교육실시ID")
        self.sec_time = self.sec(c, "p_time", "시작 / 종료 시간")
        self.sec_photo = self.sec(c, "p_photo", "증빙사진")

    def rebuild_periods(self):
        n = len(self.periods)
        hours = [str(i) for i in range(24)]
        mins = ["00", "30"]

        # --- 교육과정명 ---
        self.sec_course.clear()
        for i, p in enumerate(self.periods):
            row = tk.Frame(self.sec_course.body, bg="white")
            row.pack(fill="x", pady=2)
            self.row_label(row, i).pack(side="left")
            cb = ttk.Combobox(row, textvariable=p["v"]["course"], values=HB.COURSES,
                              state="readonly", font=(UI_FONT, 8))
            cb.pack(side="left", fill="x", expand=True, ipady=1)
            cb.bind("<FocusIn>", lambda e, i=i: self.set_cur(i))

        # --- 교육실시ID ---
        self.sec_eduid.clear()
        for i, p in enumerate(self.periods):
            row = tk.Frame(self.sec_eduid.body, bg="white")
            row.pack(fill="x", pady=2)
            self.row_label(row, i).pack(side="left")
            en = tk.Entry(row, textvariable=p["v"]["eduid"], font=(UI_FONT, 10),
                          relief="solid", bd=1)
            en.pack(side="left", fill="x", expand=True, ipady=3)
            en.bind("<FocusIn>", lambda e, i=i: self.set_cur(i))

        # --- 시작 / 종료 시간 ---
        self.sec_time.clear()
        for i, p in enumerate(self.periods):
            row = tk.Frame(self.sec_time.body, bg="white")
            row.pack(fill="x", pady=2)
            self.row_label(row, i).pack(side="left")
            for hv, mv, tail in (("sh", "sm", " ~ "), ("eh", "em", "")):
                c1 = ttk.Combobox(row, textvariable=p["v"][hv], values=hours,
                                  state="readonly", width=3, font=(UI_FONT, 9))
                c1.pack(side="left")
                tk.Label(row, text="시", bg="white", font=(UI_FONT, 9)).pack(side="left")
                c2 = ttk.Combobox(row, textvariable=p["v"][mv], values=mins,
                                  state="readonly", width=3, font=(UI_FONT, 9))
                c2.pack(side="left", padx=(2, 0))
                tk.Label(row, text="분" + tail, bg="white",
                         font=(UI_FONT, 9)).pack(side="left")
                for w in (c1, c2):
                    w.bind("<FocusIn>", lambda e, i=i: self.set_cur(i))

        # --- 증빙사진 ---
        self.sec_photo.clear()
        body = self.sec_photo.body
        br = tk.Frame(body, bg="white")
        br.pack(fill="x")
        tk.Button(br, text="사진 한번에 불러오기", font=(UI_FONT, 8), relief="solid",
                  bd=1, bg="white", command=self.pick_photos).pack(
            side="left", fill="x", expand=True)
        tk.Button(br, text="붙여넣기", font=(UI_FONT, 8), relief="solid", bd=1,
                  bg="white", command=self.paste_photo).pack(side="left", padx=(4, 0))
        tk.Button(br, text="모두 비우기", font=(UI_FONT, 8), relief="solid", bd=1,
                  bg="white", command=self.clear_all_photos).pack(side="left", padx=(4, 0))

        mr = tk.Frame(body, bg="white")
        mr.pack(fill="x", pady=(5, 2))
        tk.Label(mr, text="배치", bg="white", fg=C_MUTED,
                 font=(UI_FONT, 8)).pack(side="left", padx=(0, 6))
        self.modevar = tk.IntVar(value=self.photo_mode)
        for val, txt in ((3, "3장씩  (전·중·후)"), (2, "2장씩  (전·중)")):
            tk.Radiobutton(mr, text=txt, variable=self.modevar, value=val, bg="white",
                           font=(UI_FONT, 8), activebackground="white",
                           command=self.on_mode).pack(side="left", padx=(0, 8))

        self.photo_rows = []
        self.row_slots = []
        lst = tk.Frame(body, bg="white")
        lst.pack(fill="x", pady=(6, 0))
        for idx, (i, k) in enumerate(self.slot_seq()):
            r = tk.Frame(lst, bg="white", height=32, highlightthickness=1,
                         highlightbackground="#e6e9ee")
            r.pack(fill="x", pady=(0, 3))
            r.pack_propagate(False)
            tag = tk.Label(r, text="%d교시 %s" % (i + 1, SLOT_NAMES[k]), bg=C_ACC_W,
                           fg=C_ACC, font=(UI_FONT, 8, "bold"), width=10)
            tag.pack(side="left", fill="y")
            im = self.periods[i]["photos"][k]
            nm = tk.Label(r, text=self.periods[i]["names"][k] or "비어 있음", bg="white",
                          fg="#1c2530" if im is not None else "#aab2bd",
                          font=(UI_FONT, 8), anchor="w", padx=8)
            nm.pack(side="left", fill="both", expand=True)
            r._name_lbl = nm
            xb = tk.Label(r, text="✕", bg="white", fg="#98a1ae", font=(UI_FONT, 8),
                          padx=7, cursor="hand2")
            xb.pack(side="right")
            xb.bind("<Button-1>", lambda e, i=i, k=k: self.drop_photo(i, k))
            hd = tk.Label(r, text="≡", bg="white", fg="#b6bdc7", font=(UI_FONT, 11),
                          padx=8, cursor="fleur")
            hd.pack(side="right")
            for w in (r, tag, nm, hd):
                w.bind("<Button-1>", lambda e, n=idx: self.drag_start(n))
                w.bind("<B1-Motion>", self.drag_move)
                w.bind("<ButtonRelease-1>", self.drag_end)
            self.photo_rows.append(r)
            self.row_slots.append((i, k))
        self.hint(body, "탐색기에서 사진을 창 위로 끌어다 놓으면 빈 자리부터 차례대로 들어갑니다. "
                        "한 번에 고른 사진은 위에서부터 1교시 전·중·후 → 2교시 … 순서로 채워집니다.")
        self.hint(body, "목록의 줄을 끌어다 놓으면 순서를 바꿀 수 있고, 교시 경계를 넘어서도 옮겨집니다.")

        self.rebuild_tabs()
        self.update_thumbs()
        self.title("%s  —  총 %d교시" % (APP_NAME, n))
        for key, s in self.sections.items():   # 접힘 상태 유지
            s.set_open(self.open_state.get(key, True))
        self.sections["period"].note.config(text="총 %d교시" % n)

    def rebuild_tabs(self):
        """미리보기 위쪽의 브라우저식 교시 탭."""
        for w in self.tabbar.winfo_children():
            w.destroy()
        self.tab_w = []
        n = len(self.periods)
        for i in range(n):
            t = tk.Frame(self.tabbar, bg="#eceff3", cursor="hand2")
            t.pack(side="left", fill="y", padx=(0, 1), pady=(5, 0))
            lb = tk.Label(t, text="%d교시" % (i + 1), bg="#eceff3", fg="#6b7788",
                          font=(UI_FONT, 9), padx=13, cursor="hand2")
            lb.pack(side="left")
            xb = tk.Label(t, text="✕", bg="#eceff3", fg="#98a1ae",
                          font=(UI_FONT, 7), padx=7, cursor="hand2")
            if n > 1:
                xb.pack(side="left")
                xb.bind("<Button-1>",
                        lambda e, i=i: self.after_idle(lambda: self.del_period(i)))
            for w in (t, lb):
                w.bind("<Button-1>", lambda e, i=i: self.set_cur(i))
            self.tab_w.append((t, lb, xb))
        add = tk.Label(self.tabbar, text="＋", bg="#dfe3e9", fg="#5b6472",
                       font=(UI_FONT, 11), padx=11, cursor="hand2")
        add.pack(side="left", pady=(5, 0))
        add.bind("<Button-1>", lambda e: self.after_idle(self.add_period))
        tk.Label(self.tabbar, text="A4 가로 1쪽  ·  2쪽 교육프로그램 표는 원본 그대로 유지",
                 bg="#dfe3e9", fg="#8a93a0", font=(UI_FONT, 8)).pack(side="right", padx=12)
        self.mark_current()

    def mark_current(self):
        for i, (t, lb, xb) in enumerate(getattr(self, "tab_w", [])):
            on = (i == self.cur)
            bg = "white" if on else "#eceff3"
            for w in (t, lb, xb):
                w.config(bg=bg)
            lb.config(fg="#1c2530" if on else "#6b7788",
                      font=(UI_FONT, 9, "bold" if on else "normal"))

    # ---------------- 사진 ----------------
    def slot_seq(self, mode=None):
        """사진이 채워지는 순서. 2장씩 모드에서는 '중'을 건너뛴다."""
        order = (0, 1, 2) if (mode or self.photo_mode) == 3 else (0, 1)
        return [(i, k) for i in range(len(self.periods)) for k in order]

    def full_seq(self):
        return [(i, k) for i in range(len(self.periods)) for k in (0, 1, 2)]

    def on_mode(self):
        self.photo_mode = self.modevar.get()
        self.reflow()
        self.rebuild_periods()
        self.redraw()

    def reflow(self):
        """넣어둔 사진을 현재 모드 순서대로 앞에서부터 다시 채운다."""
        items = [self.grab_slot(i, k) for i, k in self.full_seq()
                 if self.periods[i]["photos"][k] is not None]
        need = max(1, -(-len(items) // self.photo_mode))
        while len(self.periods) < need:
            self.add_period(silent=True)
            self.periods[-1]["auto"] = True
        for pr in self.periods:
            self.clear_slots(pr)
        for (i, k), it in zip(self.slot_seq(), items):
            self.put_slot(i, k, it)
        # 모드를 바꾸느라 자동으로 붙었던 빈 교시는 다시 걷어낸다
        while len(self.periods) > need and self.periods[-1].get("auto")                 and not any(self.periods[-1]["photos"]):
            self.periods.pop()
        self.cur = min(self.cur, len(self.periods) - 1)

    # ----- 드래그로 순서 바꾸기 -----
    def row_at(self, y_root):
        for n, r in enumerate(self.photo_rows):
            if y_root < r.winfo_rooty() + r.winfo_height():
                return n
        return len(self.photo_rows) - 1

    def drag_start(self, n):
        self._drag_from = n
        self._drag_to = n
        self._drag_moved = False

    def drag_move(self, e):
        if getattr(self, "_drag_from", None) is None:
            return
        self._drag_moved = True
        t = self.row_at(e.y_root)
        if t != self._drag_to:
            self._drag_to = t
            for n, r in enumerate(self.photo_rows):
                on = (n == t)
                r.config(highlightbackground=C_ACC if on else "#e6e9ee",
                         highlightthickness=2 if on else 1)

    def drag_end(self, e):
        n = getattr(self, "_drag_from", None)
        self._drag_from = None
        if n is None or n >= len(self.row_slots):
            return
        t = self._drag_to
        if not self._drag_moved or t == n:
            self.set_cur(self.row_slots[n][0])
            self.refresh_photo_rows()
            return
        seq = self.slot_seq()
        items = [self.grab_slot(i, k) for i, k in seq]
        items.insert(t, items.pop(n))
        for (i, k), it in zip(seq, items):
            self.put_slot(i, k, it)
        self.refresh_photo_rows()
        self.redraw()

    def refresh_photo_rows(self):
        for n, (i, k) in enumerate(self.row_slots):
            r = self.photo_rows[n]
            im = self.periods[i]["photos"][k]
            r._name_lbl.config(text=self.periods[i]["names"][k] or "비어 있음",
                               fg="#1c2530" if im is not None else "#aab2bd")
            r.config(highlightbackground="#e6e9ee", highlightthickness=1)

    # ----- 탐색기에서 파일 끌어다 놓기 (Windows WM_DROPFILES) -----
    def enable_file_drop(self):
        try:
            import ctypes
            from ctypes import wintypes
            user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
            hwnd = user32.GetParent(self.winfo_id()) or self.winfo_id()
            shell32.DragAcceptFiles(ctypes.c_void_p(hwnd), True)

            LRESULT = ctypes.c_ssize_t
            WNDPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_void_p, ctypes.c_uint,
                                         ctypes.c_size_t, ctypes.c_ssize_t)
            setter = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
            setter.restype = LRESULT
            setter.argtypes = [ctypes.c_void_p, ctypes.c_int, WNDPROC]
            user32.CallWindowProcW.restype = LRESULT
            user32.CallWindowProcW.argtypes = [LRESULT, ctypes.c_void_p, ctypes.c_uint,
                                               ctypes.c_size_t, ctypes.c_ssize_t]

            def proc(h, msg, wp, lp):
                if msg == 0x0233:                      # WM_DROPFILES
                    try:
                        drop = ctypes.c_void_p(wp)
                        cnt = shell32.DragQueryFileW(drop, 0xFFFFFFFF, None, 0)
                        files = []
                        for i in range(cnt):
                            ln = shell32.DragQueryFileW(drop, i, None, 0)
                            buf = ctypes.create_unicode_buffer(ln + 1)
                            shell32.DragQueryFileW(drop, i, buf, ln + 1)
                            files.append(buf.value)
                        shell32.DragFinish(drop)
                        self.after(1, lambda f=files: self.drop_files(f))
                    except Exception:
                        pass
                    return 0
                return user32.CallWindowProcW(self._old_proc, h, msg, wp, lp)

            self._new_proc = WNDPROC(proc)             # 참조 유지 필수
            self._old_proc = setter(ctypes.c_void_p(hwnd), -4, self._new_proc)
            self._drop_ok = True
        except Exception:
            self._drop_ok = False

    def drop_files(self, paths):
        """끌어다 놓은 이미지를 빈 자리부터 차례대로 채운다."""
        imgs = [p for p in paths
                if os.path.isfile(p) and os.path.splitext(p)[1].lower() in IMG_EXT]
        if not imgs:
            return
        imgs.sort()
        empt = [t for t in self.slot_seq() if self.periods[t[0]]["photos"][t[1]] is None]
        if len(imgs) > len(empt):
            extra = -(-(len(imgs) - len(empt)) // self.photo_mode)
            if messagebox.askyesno(
                    APP_NAME, "사진 %d장을 넣으려면 빈 자리가 모자랍니다." % len(imgs)
                              + chr(10) + "교시를 %d개 늘릴까요?" % extra):
                for _ in range(extra):
                    self.add_period(silent=True)
                empt = [t for t in self.slot_seq()
                        if self.periods[t[0]]["photos"][t[1]] is None]
        bad = 0
        for n, path in enumerate(imgs):
            if n >= len(empt):
                break
            i, k = empt[n]
            try:
                self.set_slot(i, k, load_image(path), os.path.basename(path))
            except Exception:
                bad += 1
        left = len(imgs) - len(empt)
        self.rebuild_periods()
        self.redraw()
        if bad:
            messagebox.showwarning(APP_NAME, "%d개 파일은 열 수 없어 건너뛰었습니다." % bad)
        elif left > 0:
            messagebox.showinfo(APP_NAME, "빈 자리가 모자라 사진 %d장은 넣지 못했습니다." % left)

    def pick_photos(self):
        paths = filedialog.askopenfilenames(
            title="증빙사진 선택 (고른 순서대로 1교시부터 채웁니다)",
            initialdir=self.last_dir,
            filetypes=[("이미지 파일", "*.jpg *.jpeg *.png *.bmp *.gif *.webp"),
                       ("모든 파일", "*.*")])
        if not paths:
            return
        self.last_dir = os.path.dirname(paths[0])

        per = self.photo_mode
        seq = self.slot_seq()
        if len(paths) > len(seq):
            extra = -(-(len(paths) - len(seq)) // per)
            if messagebox.askyesno(
                    APP_NAME, "사진 %d장을 넣으려면 교시가 %d개 더 필요합니다.\n"
                              "교시를 늘릴까요?" % (len(paths), extra)):
                for _ in range(extra):
                    self.add_period(silent=True)
                seq = self.slot_seq()

        has = any(p is not None for pr in self.periods for p in pr["photos"])
        start = 0
        if has:
            if messagebox.askyesno(APP_NAME, "이미 넣어둔 사진이 있습니다.\n"
                                             "모두 지우고 새로 채울까요?\n\n"
                                             "[아니오] 를 고르면 빈 자리부터 이어서 채웁니다."):
                for pr in self.periods:
                    self.clear_slots(pr)
            else:
                while start < len(seq):
                    i, k = seq[start]
                    if self.periods[i]["photos"][k] is None:
                        break
                    start += 1

        bad = 0
        for n, path in enumerate(paths):
            j = start + n
            if j >= len(seq):
                break
            i, k = seq[j]
            try:
                self.set_slot(i, k, load_image(path), os.path.basename(path))
            except Exception:
                bad += 1
        if bad:
            messagebox.showwarning(APP_NAME, "%d개 파일은 열 수 없어 건너뛰었습니다." % bad)
        if start + len(paths) > len(seq):
            messagebox.showinfo(APP_NAME, "자리가 모자라 뒤쪽 사진 일부는 넣지 못했습니다.")
        self.rebuild_periods()
        self.redraw()

    def paste_photo(self):
        im = self.clipboard_image()
        if im is None:
            messagebox.showinfo(APP_NAME, "클립보드에 이미지가 없습니다.")
            return
        for i, k in self.slot_seq():
            if self.periods[i]["photos"][k] is None:
                self.set_slot(i, k, im, "붙여넣은 이미지")
                self.set_cur(i)
                self.refresh_photos()
                return
        messagebox.showinfo(APP_NAME, "빈 사진 자리가 없습니다.")

    def clear_all_photos(self):
        if not messagebox.askyesno(APP_NAME, "모든 교시의 사진을 지울까요?"):
            return
        for pr in self.periods:
            self.clear_slots(pr)
        self.refresh_photos()

    def set_slot(self, i, k, orig, name):
        p = self.periods[i]
        p["origs"][k] = orig
        p["photos"][k] = fit_photo(orig)
        p["names"][k] = name
        p["crops"][k] = None

    def clear_slots(self, p):
        p["photos"][:] = [None, None, None]
        p["names"][:] = ["", "", ""]
        p["origs"][:] = [None, None, None]
        p["crops"][:] = [None, None, None]

    def drop_photo(self, i, k):
        p = self.periods[i]
        p["photos"][k] = p["origs"][k] = p["crops"][k] = None
        p["names"][k] = ""
        self.refresh_photos()

    def move_photo(self, i, k, d):
        """사진을 앞/뒤 자리로 옮긴다. 교시 경계를 넘어서도 이동한다."""
        seq = self.full_seq()
        idx = seq.index((i, k)) + d
        if not (0 <= idx < len(seq)):
            return
        a, b = (i, k), seq[idx]
        pa, pb = self.periods[a[0]]["photos"], self.periods[b[0]]["photos"]
        pa[a[1]], pb[b[1]] = pb[b[1]], pa[a[1]]
        self.refresh_photos()

    def grab_slot(self, i, k):
        p = self.periods[i]
        return (p["photos"][k], p["names"][k], p["origs"][k], p["crops"][k])

    def put_slot(self, i, k, it):
        p = self.periods[i]
        p["photos"][k], p["names"][k], p["origs"][k], p["crops"][k] = it

    def refresh_photos(self):
        self.refresh_photo_rows()
        self.redraw()

    def clipboard_image(self):
        if ImageGrab is None:
            return None
        try:
            d = ImageGrab.grabclipboard()
        except Exception:
            return None
        if isinstance(d, list):
            for p in d:
                try:
                    return load_image(p)
                except Exception:
                    pass
            return None
        if d is not None and hasattr(d, "size"):
            return d
        return None

    def on_paste(self, event=None):
        if event is not None and isinstance(event.widget, (tk.Entry, ttk.Entry)):
            return
        im = self.clipboard_image()
        if im is None:
            return
        for i, k in self.slot_seq():
            if self.periods[i]["photos"][k] is None:
                self.set_slot(i, k, im, "붙여넣은 이미지")
                self.set_cur(i)
                self.refresh_photos()
                return

    # ---------------- 서명 ----------------
    def pick_sig(self):
        p = filedialog.askopenfilename(
            title="서명 이미지 선택", initialdir=self.last_dir,
            filetypes=[("이미지 파일", "*.png *.jpg *.jpeg *.bmp *.gif"),
                       ("모든 파일", "*.*")])
        if not p:
            return
        self.last_dir = os.path.dirname(p)
        try:
            self._sig_raw = load_image(p)
            self.signature = make_signature(self._sig_raw, self.v["sigbg"].get())
            self.save_sig()
        except Exception as e:
            messagebox.showerror(APP_NAME, "서명 이미지를 열 수 없습니다.\n%s" % e)
            return
        self.update_thumbs()
        self.redraw()

    def reload_sig(self):
        if self._sig_raw is not None:
            self.signature = make_signature(self._sig_raw, self.v["sigbg"].get())
            self.save_sig()
            self.update_thumbs()
            self.redraw()

    def clear_sig(self):
        self.signature = None
        self._sig_raw = None
        for f in (SIG_FILE, SIG_SRC):
            try:
                os.remove(f)
            except Exception:
                pass
        self.update_thumbs()
        self.redraw()

    def save_sig(self):
        try:
            os.makedirs(CFG_DIR, exist_ok=True)
            if self.signature is not None:
                self.signature.save(SIG_FILE, "PNG")
            if self._sig_raw is not None:
                self._sig_raw.convert("RGBA").save(SIG_SRC, "PNG")
        except Exception:
            pass

    # ---------------- 설정 저장/복원 ----------------
    def on_change(self):
        if self._loading:
            return
        self.redraw()

    def on_date(self, y, m, d):
        self.date = [y, m, d]
        self.redraw()

    def load_config(self):
        try:
            with open(CFG_FILE, encoding="utf-8") as fp:
                j = json.load(fp)
        except Exception:
            j = {}
        if "periods" not in j and j.get("tabs"):   # 예전 설정 형식 이어받기
            old = j["tabs"]
            for k in COMMON_KEYS:
                j.setdefault(k, old[0].get(k))
            j.setdefault("date", old[0].get("date"))
            j["periods"] = [{k: t.get(k) for k in PERIOD_KEYS if k in t} for t in old]
        self._loading = True
        for k in COMMON_KEYS:
            if k in j:
                try:
                    self.v[k].set(j[k])
                except Exception:
                    pass
        self.v["sigbg"].set(bool(j.get("sigbg", True)))
        if isinstance(j.get("date"), list) and len(j["date"]) == 3:
            self.date = list(j["date"])
        self.cal.set(*self.date)
        if j.get("photo_mode") in (2, 3):
            self.photo_mode = j["photo_mode"]
        try:
            self.sig_scale = max(0.4, min(2.5, float(j.get("sig_scale", 1.0))))
            self.sig_dx = int(j.get("sig_dx", 0))
            self.sig_dy = int(j.get("sig_dy", 0))
            self.clamp_sig()
        except (TypeError, ValueError):
            pass
        if isinstance(j.get("open"), dict):
            self.open_state.update({k: bool(v) for k, v in j["open"].items()})

        saved = j.get("periods") or []
        if saved:
            self.periods = []
            for item in saved:
                p = self.new_period()
                for k in PERIOD_KEYS:
                    if item.get(k) is not None:
                        p["v"][k].set(item[k])
                if p["v"]["course"].get() not in HB.COURSES:
                    p["v"]["course"].set(HB.COURSES[0])
                self.periods.append(p)
        self.cur = 0
        self._loading = False
        self.rebuild_periods()

        self.last_dir = j.get("last_dir") or self.last_dir
        try:
            if os.path.exists(SIG_SRC):
                self._sig_raw = load_image(SIG_SRC)
                self.signature = make_signature(self._sig_raw, self.v["sigbg"].get())
            elif os.path.exists(SIG_FILE):
                self.signature = load_image(SIG_FILE)
        except Exception:
            pass
        self.update_thumbs()

    def schedule_save(self):
        """값이 바뀌면 잠시 뒤 자동으로 설정을 저장한다(강제 종료 대비)."""
        job = getattr(self, "_save_job", None)
        if job:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._save_job = self.after(1500, self.save_config)

    def on_close(self):
        self.save_config()
        self.destroy()

    def save_config(self):
        self._save_job = None
        try:
            os.makedirs(CFG_DIR, exist_ok=True)
            j = {k: self.v[k].get() for k in COMMON_KEYS}
            j["sigbg"] = self.v["sigbg"].get()
            j["date"] = list(self.date)
            j["last_dir"] = self.last_dir
            j["photo_mode"] = self.photo_mode
            j["sig_scale"] = self.sig_scale
            j["sig_dx"] = self.sig_dx
            j["sig_dy"] = self.sig_dy
            j["open"] = dict(self.open_state)
            j["periods"] = [{k: p["v"][k].get() for k in PERIOD_KEYS}
                            for p in self.periods]
            with open(CFG_FILE, "w", encoding="utf-8") as fp:
                json.dump(j, fp, ensure_ascii=False, indent=1)
        except Exception:
            pass

    # ---------------- 저장 ----------------
    def save(self):
        i = self.cur
        st = self.period_state(i)
        want = (0, 1, 2) if self.photo_mode == 3 else (0, 1)
        miss = [SLOT_NAMES[k] for k in want if self.periods[i]["photos"][k] is None]
        if miss:
            if not messagebox.askyesno(
                    APP_NAME, "%d교시의 %s 사진이 비어 있습니다.\n그대로 저장할까요?"
                              % (i + 1, ", ".join(miss))):
                return
        p = filedialog.asksaveasfilename(
            title="%d교시 hwpx 저장" % (i + 1), initialdir=self.last_dir,
            initialfile=HB.file_name(st), defaultextension=".hwpx",
            filetypes=[("한글 문서", "*.hwpx"), ("모든 파일", "*.*")])
        if not p:
            return
        try:
            data = HB.build_hwpx(st, self.periods[i]["photos"], self.signature,
                                 self.sig_scale, self.sig_dx, self.sig_dy)
            with open(p, "wb") as fp:
                fp.write(data)
        except Exception:
            messagebox.showerror(APP_NAME, "저장 중 오류가 발생했습니다.\n\n%s"
                                 % traceback.format_exc(limit=3))
            return
        self.last_dir = os.path.dirname(p)
        self.save_config()
        messagebox.showinfo(APP_NAME, "저장했습니다.\n\n%s" % p)

    def save_all(self):
        folder = filedialog.askdirectory(title="전체 교시를 저장할 폴더 선택",
                                         initialdir=self.last_dir)
        if not folder:
            return
        done, used = [], set()
        for i in range(len(self.periods)):
            st = self.period_state(i)
            name = HB.file_name(st)
            if name in used:
                name = name[:-5] + "_%d교시.hwpx" % (i + 1)
            used.add(name)
            try:
                data = HB.build_hwpx(st, self.periods[i]["photos"], self.signature,
                                 self.sig_scale, self.sig_dx, self.sig_dy)
                with open(os.path.join(folder, name), "wb") as fp:
                    fp.write(data)
                done.append("%d교시  →  %s" % (i + 1, name))
            except Exception:
                done.append("%d교시  →  실패" % (i + 1))
        self.last_dir = folder
        self.save_config()
        msg = "%d개 파일을 저장했습니다." % len(self.periods)
        msg += chr(10) + chr(10) + folder + chr(10) + chr(10) + chr(10).join(done)
        messagebox.showinfo(APP_NAME, msg)

    # ---------------- 미리보기에서 바로 편집 ----------------
    def click_cell(self, k):
        i = self.cur
        if self.periods[i]["origs"][k] is None:
            self.pick_photos()
            return

        def done(img, state):
            self.periods[i]["photos"][k] = img
            self.periods[i]["crops"][k] = state
            self.redraw()

        CropDialog(self, self.periods[i]["origs"][k],
                   self.periods[i]["crops"][k], done)

    HU_MM = 283.46          # 1mm 당 HWPUNIT

    def sig_hit(self, e):
        """서명 위인지 / 크기조절 손잡이 위인지."""
        b = getattr(self, "_sig_box", None)
        if not b or self.signature is None:
            return None
        x1, y1, x2, y2 = b
        if abs(e.x - x1) <= 7 and abs(e.y - y2) <= 7:
            return "size"
        if x1 - 2 <= e.x <= x2 + 2 and y1 - 2 <= e.y <= y2 + 2:
            return "move"
        return None

    def canvas_motion(self, e):
        hit = self.sig_hit(e)
        cur = {"size": "sizing", "move": "fleur"}.get(hit, "")
        if not hit:
            for x1, y1, x2, y2 in getattr(self, "_cell_boxes", []):
                if x1 <= e.x <= x2 and y1 <= e.y <= y2:
                    cur = "hand2"
                    break
        hot = hit is not None
        if hot != getattr(self, "_sig_hot", False):
            self._sig_hot = hot
            self.cv.itemconfigure("sigui", state="normal" if hot else "hidden")
        if cur != getattr(self, "_cursor_now", None):
            self._cursor_now = cur
            self.cv.config(cursor=cur)

    def canvas_press(self, e):
        self._sig_mode = self.sig_hit(e)
        if self._sig_mode:
            x1, y1, x2, y2 = self._sig_box
            self._sig_grab = (e.x, e.y, self.sig_dx, self.sig_dy, self.sig_scale,
                              x2, y1, x2 - x1, y2 - y1)
            return
        for k, (x1, y1, x2, y2) in enumerate(getattr(self, "_cell_boxes", [])):
            if x1 <= e.x <= x2 and y1 <= e.y <= y2:
                self.click_cell(k)
                return

    def canvas_drag(self, e):
        if not self._sig_mode:
            return
        gx, gy, dx0, dy0, sc0, ax, ay, w0, h0 = self._sig_grab
        if self._sig_mode == "move":
            k = self.HU_MM / self.s
            self.sig_dx = int(round(dx0 + (e.x - gx) * k))
            self.sig_dy = int(round(dy0 + (e.y - gy) * k))
        else:
            nw, nh = max(6.0, ax - e.x), max(6.0, e.y - ay)
            sc = sc0 * max(nw / max(w0, 1.0), nh / max(h0, 1.0))
            self.sig_scale = round(max(0.25, min(3.0, sc)), 3)
        self.clamp_sig()
        self.redraw()

    def canvas_release(self, e):
        self._sig_mode = None

    def canvas_double(self, e):
        if self.sig_hit(e):
            self.sig_scale, self.sig_dx, self.sig_dy = 1.0, 0, 0
            self.redraw()

    def canvas_wheel(self, e):
        if not self.sig_hit(e):
            return
        self.sig_scale = round(max(0.25, min(3.0, self.sig_scale *
                                             (1.08 if e.delta > 0 else 1 / 1.08))), 3)
        self.redraw()

    def clamp_sig(self):
        self.sig_dx = max(-58000, min(3000, self.sig_dx))
        self.sig_dy = max(-14000, min(6000, self.sig_dy))

    # ---------------- 미리보기 그리기 ----------------
    def font(self, pt, bold=False, italic=False):
        px = max(6, int(round(pt * 0.3528 * self.s)))
        key = (px, bold, italic)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(
                family=DOC_FONT, size=-px,
                weight="bold" if bold else "normal",
                slant="italic" if italic else "roman")
        return self._fonts[key]

    def X(self, mm):
        return self.ox + mm * self.s

    def Y(self, mm):
        return self.oy + mm * self.s

    def lw(self, mm):
        return max(1, int(round(mm * self.s)))

    def font_fit(self, text, pt, bold, maxpx, italic=False):
        """한 줄에 들어갈 때까지 글자 크기를 조금씩 줄인다."""
        if isinstance(text, (list, tuple)):
            meas = lambda f: sum(f.measure(t) for t in text)
        else:
            meas = lambda f: f.measure(text)
        f = self.font(pt, bold, italic)
        while pt > 5.0 and meas(f) > maxpx:
            pt -= 0.25
            f = self.font(pt, bold, italic)
        return f

    def wrap(self, text, f, maxpx):
        lines, cur = [], ""
        for ch in text:
            if cur and f.measure(cur + ch) > maxpx:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        lines.append(cur)
        return lines

    def redraw(self):
        try:
            self._redraw()
        except Exception:
            traceback.print_exc()
        if not self._loading:
            self.schedule_save()

    def _redraw(self):
        c = self.cv
        W, H = c.winfo_width(), c.winfo_height()
        if W < 100 or H < 100:
            return
        c.delete("all")
        self._imgcache = {}
        self.s = min((W - 34) / PAGE_W, (H - 34) / PAGE_H)
        s = self.s
        self.ox = (W - PAGE_W * s) / 2.0
        self.oy = (H - PAGE_H * s) / 2.0
        X, Y = self.X, self.Y
        st = self.state()

        self.fname_lbl.config(text="%d교시  →  %s" % (self.cur + 1, HB.file_name(st)))

        c.create_rectangle(X(0) + 3, Y(0) + 3, X(PAGE_W) + 3, Y(PAGE_H) + 3,
                           fill="#dfe3e9", outline="")
        c.create_rectangle(X(0), Y(0), X(PAGE_W), Y(PAGE_H), fill="white",
                           outline="#c8ccd2")

        cx = X((TBL_L + TBL_R) / 2.0)

        self._cell_boxes = [(X(TBL_L + TBL_W * k / 3.0), Y(Y_B2),
                             X(TBL_L + TBL_W * (k + 1) / 3.0), Y(Y_B3))
                            for k in range(3)]

        c.create_text(cx, Y(Y_TITLE), text="디지털배움터 교육 사진 증빙",
                      font=self.font(18, True), anchor="center")
        head = HB.headline_text(st).rstrip()
        c.create_text(X(TBL_R - 1.4), Y(Y_SUB), text=head,
                      font=self.font_fit(head, 12, False, (TBL_R - 1.4 - 20.0) * s),
                      anchor="e")

        thin, thick = self.lw(THIN), self.lw(THICK)
        labels = ["교육과정명", None, "교육실시ID", None, "교육일자", None]
        vals = [None, st["course"], None, st["eduid"], None, HB.date_text(st)]
        for i in range(6):
            if labels[i]:
                c.create_rectangle(X(TBL_L + TBL_W * COL_F[i]), Y(Y_A1),
                                   X(TBL_L + TBL_W * COL_F[i + 1]), Y(Y_A2),
                                   fill=FILL_HEAD, outline="")
        c.create_rectangle(X(TBL_L), Y(Y_A1), X(TBL_R), Y(Y_A2),
                           outline="black", width=thin)
        for i in range(6):
            x1 = X(TBL_L + TBL_W * COL_F[i])
            x2 = X(TBL_L + TBL_W * COL_F[i + 1])
            if i:
                c.create_line(x1, Y(Y_A1), x1, Y(Y_A2), fill="black", width=thin)
            txt = labels[i] if labels[i] else vals[i]
            if labels[i]:
                f = self.font_fit(txt, 10, True, (x2 - x1) + 0.5 * s)
                lines = [txt]
            else:
                f = self.font(10)
                lines = self.wrap(txt or "", f, (x2 - x1) - 4 * s)
            lh = 10 * 0.3528 * 1.35 * s
            y0 = Y((Y_A1 + Y_A2) / 2.0) - (len(lines) - 1) * lh / 2.0
            for k, ln in enumerate(lines):
                c.create_text((x1 + x2) / 2.0, y0 + k * lh, text=ln, font=f,
                              anchor="center")

        c.create_rectangle(X(TBL_L), Y(Y_B1), X(TBL_R), Y(Y_B2),
                           fill=FILL_HEAD, outline="")
        c.create_rectangle(X(TBL_L), Y(Y_B1), X(TBL_R), Y(Y_B4),
                           outline="black", width=thick)
        c.create_line(X(TBL_L), Y(Y_B2), X(TBL_R), Y(Y_B2), fill="black", width=thin)
        c.create_line(X(TBL_L), Y(Y_B3), X(TBL_R), Y(Y_B3), fill="black", width=thin)
        for k in (1, 2):
            x = X(TBL_L + TBL_W * k / 3.0)
            c.create_line(x, Y(Y_B1), x, Y(Y_B3), fill="black", width=thin)

        for i, (big, small) in enumerate(PHOTO_CAPS):
            x1 = TBL_L + TBL_W * i / 3.0
            x2 = TBL_L + TBL_W * (i + 1) / 3.0
            avail = (x2 - x1 - 2.0) * s
            fb = self.font_fit([big, small], 14, True, avail)
            fs = self.font_fit([big, small], 10, True, avail)
            wb, ws = fb.measure(big), fs.measure(small)
            x0 = X((x1 + x2) / 2.0) - (wb + ws) / 2.0
            ym = Y((Y_B1 + Y_B2) / 2.0)
            c.create_text(x0, ym, text=big, font=fb, anchor="w")
            c.create_text(x0 + wb, ym, text=small, font=fs, anchor="w")

        ch_mm = Y_B3 - Y_B2 - 1.0
        for i in range(3):
            x1 = TBL_L + TBL_W * i / 3.0
            x2 = TBL_L + TBL_W * (i + 1) / 3.0
            im = self.photos[i]
            if im is None:
                c.create_text(X((x1 + x2) / 2.0), Y((Y_B2 + Y_B3) / 2.0),
                              text="%s 사진" % SLOT_NAMES[i], fill="#c9ced6",
                              font=self.font(9))
                continue
            th = max(8, int(round(ch_mm * s)))
            tw = max(8, int(round(th * im.size[0] / float(im.size[1]))))
            maxw = int(round((x2 - x1 - 1.0) * s))
            if tw > maxw:
                tw = maxw
                th = max(8, int(round(tw * im.size[1] / float(im.size[0]))))
            ph = ImageTk.PhotoImage(im.resize((tw, th), Image.LANCZOS))
            self._imgcache["p%d" % i] = ph
            c.create_image(X((x1 + x2) / 2.0), Y((Y_B2 + Y_B3) / 2.0),
                           image=ph, anchor="center")

        f = self.font_fit([t for t, _ in Q_SEGS], 10, True, (TBL_W - 2.0) * s)
        total = sum(f.measure(t) for t, _ in Q_SEGS)
        x = cx - total / 2.0
        yq = Y(Y_Q)
        for t, circ in Q_SEGS:
            w = f.measure(t)
            c.create_text(x, yq, text=t, font=f, anchor="w")
            if circ:
                r = 2.2 * s
                c.create_oval(x + w / 2.0 - r, yq - r, x + w / 2.0 + r, yq + r,
                              outline="black", width=thin)
            x += w

        sub_t = HB.submitter_text(st)
        c.create_text(X(TBL_R) - 1.0 * s, Y(Y_SUBM), text=sub_t,
                      font=self.font_fit(sub_t, 11, True, (TBL_W - 2.0) * s),
                      anchor="e")

        if self.signature is not None:
            sh = max(8, int(round(SIG_H_MM * self.sig_scale * s)))
            sw = max(8, int(round(sh * self.signature.size[0] /
                                  float(self.signature.size[1]))))
            ph = ImageTk.PhotoImage(self.signature.resize((sw, sh), Image.LANCZOS))
            self._imgcache["sig"] = ph
            sx = X(TBL_R) - 0.6 * s + self.sig_dx / self.HU_MM * s
            sy = Y(Y_SIG) + self.sig_dy / self.HU_MM * s
            c.create_image(sx, sy, image=ph, anchor="ne")
            self._sig_box = (sx - sw, sy, sx, sy + sh)
            st_ui = "normal" if getattr(self, "_sig_hot", False) else "hidden"
            c.create_rectangle(sx - sw - 2, sy - 2, sx + 2, sy + sh + 2,
                               outline=C_ACC, dash=(3, 2), tags="sigui", state=st_ui)
            c.create_rectangle(sx - sw - 5, sy + sh - 5, sx - sw + 5, sy + sh + 5,
                               fill=C_ACC, outline="white", tags="sigui", state=st_ui)
        else:
            self._sig_box = None

        nw = (PAGE_W - 40.0) * s
        c.create_text(X(20.0), Y(Y_N1), text=NOTE1, anchor="w",
                      font=self.font_fit(NOTE1, 11, False, nw, italic=True))
        c.create_text(X(20.0), Y(Y_N2), text=NOTE2, anchor="w",
                      font=self.font_fit(NOTE2, 11, False, nw, italic=True))

    # ---------------- 왼쪽 썸네일 ----------------
    def update_thumbs(self):
        if not hasattr(self, "sig_lbl"):
            return
        if self.signature is None:
            self.sig_lbl.config(image="",
                                text="클릭해서 서명 이미지 불러오기 (한 번 등록하면 저장됨)",
                                height=4)
            self._thumbs.pop("sig", None)
        else:
            bg = Image.new("RGB", self.signature.size, (244, 246, 248))
            bg.paste(self.signature, (0, 0), self.signature)
            bg.thumbnail((340, 70), Image.LANCZOS)
            ph = ImageTk.PhotoImage(bg)
            self._thumbs["sig"] = ph
            self.sig_lbl.config(image=ph, text="", height=72)

    def destroy(self):
        self.save_config()
        tk.Tk.destroy(self)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
