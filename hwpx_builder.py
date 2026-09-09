# -*- coding: utf-8 -*-
"""원본 hwpx 양식의 값만 바꿔 새 hwpx를 만든다. 한글(HWP) 설치 불필요."""

import base64
import io
import re
import zipfile
from xml.sax.saxutils import escape, unescape

from PIL import Image

try:
    from template_data import TPL
except ImportError:                      # 양식은 저장소에 포함하지 않는다
    raise SystemExit(
        "template_data.py 가 없습니다." + chr(10) +
        "원본 양식으로 먼저 만들어 주세요:  python make_template.py 양식.hwpx")

# ---- 양식 치수(HWPUNIT = 1/7200 inch) ----------------------------------
CELL_W = 24023 - 282          # 사진칸 안쪽 너비
CELL_H = 22170 - 282          # 사진칸 안쪽 높이
CELL_ASPECT = CELL_W / CELL_H  # 1.0847
PIC_H = 21500                  # 사진 높이(칸을 위·아래로 꽉 채움)
SIG_H = 2254                   # 서명 높이(원본과 동일)
SIG_RIGHT = 71802              # 서명 오른쪽 끝 위치
SIG_VOFF = 791                 # 서명 세로 위치
PX2HU = 75                     # 96dpi 픽셀 -> HWPUNIT

# 마지막 쪽(수기 출석부)이 들어갈 자리. 2쪽과 같은 세로 A4(59528 x 84186) 기준.
ATT_PAPER_W, ATT_PAPER_H = 59528, 84186
ATT_L, ATT_T = 5669, 7087      # 좌우 여백 / 위 여백(4252) + 머리말(2835)
ATT_W = ATT_PAPER_W - ATT_L * 2                 # 48190
ATT_H = ATT_PAPER_H - ATT_T * 2                 # 70012
ATT_MAX_PX = 2200              # 출석부는 글씨를 읽어야 하므로 넉넉하게

# 1교시 -> 에듀버스1, 2교시 -> 에듀버스2, 3교시 -> 에듀버스3 순서
COURSES = [
    "[에듀버스1] 2026년 AI와 건강관리 앱으로 건강정보 챙기기",
    "[에듀버스2] 2026 디지털 기기와 콘텐츠 보호",
    "[지역특화] [에듀버스3] 2026 무엇이든 물어보세요",
]

DEFAULT_START = 9 * 60 + 30       # 1교시 시작 09:30


def course_minutes(course):
    """에듀버스1·2 는 1시간, 에듀버스3 은 1시간 30분."""
    return 90 if "에듀버스3" in (course or "") else 60


PHOTO_CELLS = [
    '<hp:cellAddr colAddr="0" rowAddr="4"/>',
    '<hp:cellAddr colAddr="2" rowAddr="4"/>',
    '<hp:cellAddr colAddr="6" rowAddr="4"/>',
]
ID_CELL = '<hp:cellAddr colAddr="4" rowAddr="1"/>'

ZIP_ORDER = [
    "version.xml", "settings.xml",
    "META-INF/container.xml", "META-INF/container.rdf", "META-INF/manifest.xml",
    "Contents/content.hpf", "Contents/header.xml",
    "Contents/section0.xml", "Contents/section1.xml",
    "Scripts/headerScripts", "Scripts/sourceScripts",
    "Preview/PrvText.txt", "Preview/PrvImage.png",
]


# ---- 문자열 조립 -------------------------------------------------------
def headline_text(st):
    parts = []
    if st.get("lead"):
        parts.append("강사: " + (st.get("lead_name") or ""))
    if st.get("asst"):
        parts.append("보조강사: " + (st.get("asst_name") or ""))
    parts.append("교육장소 : " + (st.get("place") or ""))
    return " / ".join(parts) + "     "


def date_text(st):
    return "%d월 %d일 %d시 %02d분 ~ %d시 %02d분" % (
        st["month"], st["day"], st["sh"], st["sm"], st["eh"], st["em"])


def submitter_name(st):
    n = (st.get("submitter") or "").strip()
    if n:
        return n
    if st.get("asst") and st.get("asst_name"):
        return st["asst_name"].strip()
    if st.get("lead") and st.get("lead_name"):
        return st["lead_name"].strip()
    return ""


def submitter_text(st):
    return "제출자: %s  (서명)" % submitter_name(st)


def file_name(st):
    eid = (st.get("eduid") or "교육실시ID").strip()
    nm = submitter_name(st) or "이름"
    bad = '\\/:*?"<>|'
    clean = lambda s: "".join(c for c in s if c not in bad).strip() or "_"
    return "%s_출결증빙자료_%s.hwpx" % (clean(eid), clean(nm))


# ---- XML 조각 ----------------------------------------------------------
def _pic_xml(pid, bin_id, w, h, ow, oh, z):
    return (
        '<hp:pic id="%d" zOrder="%d" numberingType="PICTURE" textWrap="TOP_AND_BOTTOM"'
        ' textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0"'
        ' instid="%d" reverse="0">'
        '<hp:offset x="0" y="0"/>'
        '<hp:orgSz width="%d" height="%d"/>'
        '<hp:curSz width="%d" height="%d"/>'
        '<hp:flip horizontal="0" vertical="0"/>'
        '<hp:rotationInfo angle="0" centerX="%d" centerY="%d" rotateimage="1"/>'
        '<hp:renderingInfo>'
        '<hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        '<hc:scaMatrix e1="%.6f" e2="0" e3="0" e4="0" e5="%.6f" e6="0"/>'
        '<hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        '</hp:renderingInfo>'
        '<hc:img binaryItemIDRef="%s" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
        '<hp:imgRect><hc:pt0 x="0" y="0"/><hc:pt1 x="%d" y="0"/>'
        '<hc:pt2 x="%d" y="%d"/><hc:pt3 x="0" y="%d"/></hp:imgRect>'
        '<hp:imgClip left="0" right="%d" top="0" bottom="%d"/>'
        '<hp:inMargin left="0" right="0" top="0" bottom="0"/>'
        '<hp:imgDim dimwidth="%d" dimheight="%d"/><hp:effects/>'
        '<hp:sz width="%d" widthRelTo="ABSOLUTE" height="%d" heightRelTo="ABSOLUTE" protect="0"/>'
        '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0"'
        ' holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="CENTER"'
        ' horzAlign="CENTER" vertOffset="0" horzOffset="0"/>'
        '<hp:outMargin left="0" right="0" top="0" bottom="0"/></hp:pic>'
    ) % (pid, z, pid + 7, ow, oh, w, h, w // 2, h // 2,
         w / ow, h / oh, bin_id, ow, ow, oh, oh, ow, oh, ow, oh, w, h)


def _u32(v):
    """HWPML 은 음수 위치를 32비트 부호없는 값으로 적는다."""
    v = int(round(v))
    return v if v >= 0 else v + (1 << 32)


def _sig_xml(w, h, ow, oh, dx=0, dy=0):
    return (
        '<hp:pic id="1198036548" zOrder="3" numberingType="PICTURE" textWrap="BEHIND_TEXT"'
        ' textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0"'
        ' instid="124294725" reverse="0">'
        '<hp:offset x="0" y="0"/>'
        '<hp:orgSz width="%d" height="%d"/>'
        '<hp:curSz width="%d" height="%d"/>'
        '<hp:flip horizontal="0" vertical="0"/>'
        '<hp:rotationInfo angle="0" centerX="%d" centerY="%d" rotateimage="1"/>'
        '<hp:renderingInfo>'
        '<hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        '<hc:scaMatrix e1="%.6f" e2="0" e3="0" e4="0" e5="%.6f" e6="0"/>'
        '<hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        '</hp:renderingInfo>'
        '<hc:img binaryItemIDRef="image1" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
        '<hp:imgRect><hc:pt0 x="0" y="0"/><hc:pt1 x="%d" y="0"/>'
        '<hc:pt2 x="%d" y="%d"/><hc:pt3 x="0" y="%d"/></hp:imgRect>'
        '<hp:imgClip left="0" right="%d" top="0" bottom="%d"/>'
        '<hp:inMargin left="0" right="0" top="0" bottom="0"/>'
        '<hp:imgDim dimwidth="%d" dimheight="%d"/><hp:effects/>'
        '<hp:sz width="%d" widthRelTo="ABSOLUTE" height="%d" heightRelTo="ABSOLUTE" protect="0"/>'
        '<hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="1" allowOverlap="0"'
        ' holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP"'
        ' horzAlign="LEFT" vertOffset="%d" horzOffset="%d"/>'
        '<hp:outMargin left="0" right="0" top="0" bottom="0"/></hp:pic>'
    ) % (ow, oh, w, h, w // 2, h // 2, w / ow, h / oh,
         ow, ow, oh, oh, ow, oh, ow, oh, w, h,
         _u32(SIG_VOFF + dy), _u32(SIG_RIGHT - w + dx))


def _fill_cell(xml, cell_addr, inner, para_pr=None, char_pr=None):
    """cellAddr 로 지정한 칸의 빈 문단에 내용을 넣는다."""
    idx = xml.index(cell_addr)
    head, tail = xml[:idx], xml[idx:]
    m = head.rindex('<hp:run charPrIDRef=')
    end = head.index('/>', m) + 2
    cid = char_pr or re.search(r'charPrIDRef="(\d+)"', head[m:end]).group(1)
    pre, post = head[:m], head[end:]
    if para_pr is not None:
        p = pre.rindex('<hp:p ')
        pe = pre.index('>', p) + 1
        tag = re.sub(r'paraPrIDRef="\d+"', 'paraPrIDRef="%s"' % para_pr, pre[p:pe])
        pre = pre[:p] + tag + pre[pe:]
    return pre + '<hp:run charPrIDRef="%s">%s</hp:run>' % (cid, inner) + post + tail


# ---- 2쪽(교육 프로그램 표) 읽어오기 — 미리보기용 -----------------------
_PROGRAM = None


def program_page():
    """양식 2쪽에 이미 들어 있는 교육 프로그램 표를 그대로 읽어온다.

    돌려주는 값: {"title": 제목, "cols": [칸 너비], "rows": [줄 높이],
                  "cells": [(열, 줄, 열병합, 줄병합, 글자)]}
    치수는 모두 HWPUNIT.
    """
    global _PROGRAM
    if _PROGRAM is not None:
        return _PROGRAM
    sec1 = base64.b64decode(TPL["Contents/section1.xml"]).decode("utf-8")
    body = sec1[:sec1.index("<hp:tbl")]
    title = "".join(re.findall(r"<hp:t>([^<]*)</hp:t>", body)).strip()

    cells, cols, rows = [], {}, {}
    for m in re.finditer(r"<hp:tc[ >].*?</hp:tc>", sec1, re.S):
        tc = m.group(0)
        a = re.search(r'<hp:cellAddr colAddr="(\d+)" rowAddr="(\d+)"/>', tc)
        sp = re.search(r'<hp:cellSpan colSpan="(\d+)" rowSpan="(\d+)"/>', tc)
        sz = re.search(r'<hp:cellSz width="(\d+)" height="(\d+)"/>', tc)
        if not (a and sp and sz):
            continue
        col, row = int(a.group(1)), int(a.group(2))
        cs, rs = int(sp.group(1)), int(sp.group(2))
        w, h = int(sz.group(1)), int(sz.group(2))
        txt = "".join(re.findall(r"<hp:t>([^<]*)</hp:t>", tc)).strip()
        cells.append((col, row, cs, rs, txt))
        if cs == 1:
            cols[col] = w
        if rs == 1:
            rows[row] = h
    _PROGRAM = {
        "title": title,
        "cols": [cols.get(i, 10000) for i in range(max(cols) + 1)] if cols else [],
        "rows": [rows.get(i, 2600) for i in range(max(rows) + 1)] if rows else [],
        "cells": cells,
    }
    return _PROGRAM


# ---- 3쪽(수기 출석부) --------------------------------------------------
def attend_fit(im):
    """출석부 이미지를 쪽 크기에 맞춰 줄인다."""
    im = im.convert("RGB")
    w, h = im.size
    m = max(w, h)
    if m > ATT_MAX_PX:
        k = ATT_MAX_PX / float(m)
        im = im.resize((max(1, int(round(w * k))), max(1, int(round(h * k)))),
                       Image.LANCZOS)
    return im


def _attend_size(pw, ph):
    """쪽 안에 꽉 차되 넘치지 않는 크기(HWPUNIT)."""
    w, h = ATT_W, int(round(ATT_W * ph / float(pw)))
    if h > ATT_H:
        h = ATT_H
        w = int(round(ATT_H * pw / float(ph)))
    return max(1, w), max(1, h)


def _attend_xml(bin_id, w, h, ow, oh):
    """출석부 그림을 종이 한가운데에 고정한다.

    문단 안에 글자처럼 넣으면 줄간격(180%) 때문에 쪽을 넘어가므로,
    종이 기준 절대 위치로 붙인다.
    """
    x = ATT_L + (ATT_W - w) // 2
    y = ATT_T + (ATT_H - h) // 2
    return (
        '<hp:pic id="1600000001" zOrder="20" numberingType="PICTURE"'
        ' textWrap="BEHIND_TEXT" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None"'
        ' href="" groupLevel="0" instid="1600000002" reverse="0">'
        '<hp:offset x="0" y="0"/>'
        '<hp:orgSz width="%d" height="%d"/>'
        '<hp:curSz width="%d" height="%d"/>'
        '<hp:flip horizontal="0" vertical="0"/>'
        '<hp:rotationInfo angle="0" centerX="%d" centerY="%d" rotateimage="1"/>'
        '<hp:renderingInfo>'
        '<hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        '<hc:scaMatrix e1="%.6f" e2="0" e3="0" e4="0" e5="%.6f" e6="0"/>'
        '<hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        '</hp:renderingInfo>'
        '<hc:img binaryItemIDRef="%s" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
        '<hp:imgRect><hc:pt0 x="0" y="0"/><hc:pt1 x="%d" y="0"/>'
        '<hc:pt2 x="%d" y="%d"/><hc:pt3 x="0" y="%d"/></hp:imgRect>'
        '<hp:imgClip left="0" right="%d" top="0" bottom="%d"/>'
        '<hp:inMargin left="0" right="0" top="0" bottom="0"/>'
        '<hp:imgDim dimwidth="%d" dimheight="%d"/><hp:effects/>'
        '<hp:sz width="%d" widthRelTo="ABSOLUTE" height="%d" heightRelTo="ABSOLUTE" protect="0"/>'
        '<hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="0" allowOverlap="1"'
        ' holdAnchorAndSO="0" vertRelTo="PAPER" horzRelTo="PAPER" vertAlign="TOP"'
        ' horzAlign="LEFT" vertOffset="%d" horzOffset="%d"/>'
        '<hp:outMargin left="0" right="0" top="0" bottom="0"/></hp:pic>'
    ) % (ow, oh, w, h, w // 2, h // 2, w / ow, h / oh, bin_id,
         ow, ow, oh, oh, ow, oh, ow, oh, w, h, y, x)


# ---- 이미 만들어 둔 hwpx 다시 읽기 -------------------------------------
COURSE_CELL = '<hp:cellAddr colAddr="1" rowAddr="1"/>'
DATE_CELL = '<hp:cellAddr colAddr="7" rowAddr="1"/>'


def _s32(v):
    """HWPML 이 32비트 부호없는 값으로 적어둔 위치를 되돌린다."""
    v = int(v)
    return v - (1 << 32) if v >= (1 << 31) else v


def _tc_span(xml, cell_addr):
    """cellAddr 로 지정한 칸의 XML 범위."""
    idx = xml.index(cell_addr)
    return xml.rindex("<hp:tc", 0, idx), idx


def _cell_text(xml, cell_addr):
    try:
        a, b = _tc_span(xml, cell_addr)
    except ValueError:
        return ""
    return unescape("".join(re.findall(r"<hp:t>([^<]*)</hp:t>", xml[a:b])))


def _cell_bin(xml, cell_addr):
    try:
        a, b = _tc_span(xml, cell_addr)
    except ValueError:
        return None
    m = re.search(r'binaryItemIDRef="([^"]+)"', xml[a:b])
    return m.group(1) if m else None


def _norm(s):
    return " ".join((s or "").split())


def match_course(text):
    """띄어쓰기가 조금 달라도 원래 과정명으로 맞춰준다."""
    t = _norm(text)
    for c in COURSES:
        if _norm(c) == t:
            return c
    for c in COURSES:
        key = c.split("]")[0] + "]"          # [에듀버스2] 같은 앞머리
        if key and key in t:
            return c
    return text or COURSES[0]


def parse_headline(text):
    """'강사: A / 보조강사: B / 교육장소 : C' 를 도로 나눈다."""
    out = {"lead": False, "lead_name": "", "asst": False, "asst_name": "",
           "place": ""}
    for part in (text or "").split(" / "):
        part = part.strip()
        if part.startswith("보조강사:"):
            out["asst"] = True
            out["asst_name"] = part[len("보조강사:"):].strip()
        elif part.startswith("강사:"):
            out["lead"] = True
            out["lead_name"] = part[len("강사:"):].strip()
        elif part.startswith("교육장소"):
            out["place"] = part.split(":", 1)[-1].strip()
    return out


def parse_date(text):
    m = re.search(r"(\d+)월\s*(\d+)일\s*(\d+)시\s*(\d+)분\s*~\s*(\d+)시\s*(\d+)분",
                  text or "")
    if not m:
        return {}
    n = [int(x) for x in m.groups()]
    return {"month": n[0], "day": n[1], "sh": n[2], "sm": n[3],
            "eh": n[4], "em": n[5]}


def read_hwpx(path):
    """이 프로그램이 만든 .hwpx 를 다시 읽어 입력값과 그림을 돌려준다.

    양식이 다르면 ValueError 를 낸다.
    """
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        if "Contents/section0.xml" not in names:
            raise ValueError("hwpx 파일이 아닙니다.")
        sec0 = z.read("Contents/section0.xml").decode("utf-8")
        sec1 = (z.read("Contents/section1.xml").decode("utf-8")
                if "Contents/section1.xml" in names else "")
        if ID_CELL not in sec0 or PHOTO_CELLS[0] not in sec0:
            raise ValueError("이 프로그램이 쓰는 증빙 양식이 아닙니다.")

        def img(bid, ext):
            for nm in ("BinData/%s.%s" % (bid, ext), "BinData/%s.jpg" % bid,
                       "BinData/%s.png" % bid):
                if nm in names:
                    im = Image.open(io.BytesIO(z.read(nm)))
                    im.load()
                    return im
            return None

        m = re.search(r'paraPrIDRef="24"[^>]*><hp:run charPrIDRef="20">'
                      r"<hp:t>([^<]*)</hp:t>", sec0)
        d = parse_headline(unescape(m.group(1)) if m else "")

        d.update(parse_date(_cell_text(sec0, DATE_CELL)))
        d.setdefault("month", 1)
        d.setdefault("day", 1)
        for k, dv in (("sh", 9), ("sm", 30), ("eh", 10), ("em", 30)):
            d.setdefault(k, dv)
        d["course"] = match_course(_cell_text(sec0, COURSE_CELL))
        d["eduid"] = _cell_text(sec0, ID_CELL).strip()

        m = re.search(r"<hp:t>제출자:([^<]*)</hp:t>", sec0)
        sub = unescape(m.group(1)) if m else ""
        d["submitter"] = sub.replace("(서명)", "").strip()

        d["photos"] = [img(_cell_bin(sec0, c) or "", "jpg") if _cell_bin(sec0, c)
                       else None for c in PHOTO_CELLS]

        att_id = None
        m = re.search(r'binaryItemIDRef="(image9)"', sec1)
        if m:
            att_id = m.group(1)
        d["att"] = img(att_id, "jpg") if att_id else None

        d["signature"] = None
        d["sig_scale"], d["sig_dx"], d["sig_dy"] = 1.0, 0, 0
        m = re.search(r'<hp:pic id="1198036548".*?</hp:pic>', sec0, re.S)
        if m:
            pic = m.group(0)
            sz = re.search(r'<hp:sz width="(\d+)"[^>]*height="(\d+)"', pic)
            pos = re.search(r'vertOffset="(\d+)" horzOffset="(\d+)"', pic)
            if sz and pos:
                w, h = int(sz.group(1)), int(sz.group(2))
                d["sig_scale"] = round(max(0.25, min(3.0, h / float(SIG_H))), 3)
                d["sig_dy"] = _s32(pos.group(1)) - SIG_VOFF
                d["sig_dx"] = _s32(pos.group(2)) - (SIG_RIGHT - w)
            d["signature"] = img("image1", "png")
    return d


# ---- 본체 --------------------------------------------------------------
def build_hwpx(st, photos, signature, sig_scale=1.0, sig_dx=0, sig_dy=0,
               attend=None):
    """st: 입력값 dict, photos: [PIL.Image|None]*3, signature: PIL.Image|None"""
    sec0 = base64.b64decode(TPL["Contents/section0.xml"]).decode("utf-8")
    hpf = base64.b64decode(TPL["Contents/content.hpf"]).decode("utf-8")
    extra_bins, extra_items = [], []

    # 1) 강사/보조강사 + 교육장소
    sec0 = re.sub(r'(paraPrIDRef="24"[^>]*><hp:run charPrIDRef="20">)<hp:t>[^<]*</hp:t>',
                  lambda m: m.group(1) + "<hp:t>" + escape(headline_text(st)) + "</hp:t>",
                  sec0, count=1)
    # 2) 교육과정명
    sec0 = re.sub(r'<hp:t>\[에듀버스2\][^<]*</hp:t>',
                  "<hp:t>" + escape(st["course"]) + "</hp:t>", sec0, count=1)
    # 3) 교육실시ID (원본은 빈 칸)
    sec0 = _fill_cell(sec0, ID_CELL,
                      "<hp:t>" + escape(st.get("eduid") or "") + "</hp:t>", "25", "11")
    # 4) 교육일자
    sec0 = re.sub(r'<hp:t>8월 31일[^<]*</hp:t>',
                  "<hp:t>" + escape(date_text(st)) + "</hp:t>", sec0, count=1)
    # 5) 제출자
    sec0 = re.sub(r'<hp:t>제출자:[^<]*</hp:t>',
                  "<hp:t>" + escape(submitter_text(st)) + "</hp:t>", sec0, count=1)

    # 6) 증빙사진 (전·중·후)
    for i, im in enumerate(photos):
        if im is None:
            continue
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=92)
        data = buf.getvalue()
        pw, ph = im.size
        h = PIC_H
        w = int(round(h * pw / ph))
        if w > CELL_W:
            w = CELL_W
            h = int(round(w * ph / pw))
        bid = "image%d" % (i + 2)
        extra_bins.append(("BinData/%s.jpg" % bid, data))
        extra_items.append('<opf:item id="%s" href="BinData/%s.jpg"'
                           ' media-type="image/jpeg" isEmbeded="1"/>' % (bid, bid))
        sec0 = _fill_cell(sec0, PHOTO_CELLS[i],
                          _pic_xml(1500000000 + i * 13, bid, w, h,
                                   pw * PX2HU, ph * PX2HU, 10 + i))

    # 7) 서명 이미지
    sig_re = re.compile(r'<hp:pic id="1198036548".*?</hp:pic>', re.S)
    bins = []
    if signature is not None:
        buf = io.BytesIO()
        signature.save(buf, "PNG")
        sw, sh = signature.size
        h = max(400, int(round(SIG_H * sig_scale)))
        w = int(round(h * sw / sh))
        sec0 = sig_re.sub(
            lambda m: _sig_xml(w, h, sw * PX2HU, sh * PX2HU,
                               int(sig_dx), int(sig_dy)), sec0, count=1)
        bins.append(("BinData/image1.png", buf.getvalue()))
    else:
        sec0 = sig_re.sub("", sec0, count=1)
        bins.append(("BinData/image1.png", base64.b64decode(TPL["BinData/image1.png"])))

    # 8) 수기 출석부 — 문서 맨 끝(3쪽)에 한 장 통째로 붙인다
    sec1 = None
    if attend is not None:
        im = attend_fit(attend)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=90)
        pw, ph = im.size
        w, h = _attend_size(pw, ph)
        bid = "image9"
        extra_bins.append(("BinData/%s.jpg" % bid, buf.getvalue()))
        extra_items.append('<opf:item id="%s" href="BinData/%s.jpg"'
                           ' media-type="image/jpeg" isEmbeded="1"/>' % (bid, bid))
        sec1 = base64.b64decode(TPL["Contents/section1.xml"]).decode("utf-8")
        blank = ('<hp:p id="0" paraPrIDRef="25" styleIDRef="0" pageBreak="1"'
                 ' columnBreak="0" merged="0"><hp:run charPrIDRef="11"/></hp:p>')
        pic = ('<hp:p id="0" paraPrIDRef="25" styleIDRef="0" pageBreak="0"'
               ' columnBreak="0" merged="0"><hp:run charPrIDRef="11">%s</hp:run></hp:p>'
               % _attend_xml(bid, w, h, pw * PX2HU, ph * PX2HU))
        sec1 = sec1.replace("</hs:sec>", blank + pic + "</hs:sec>", 1)

    # 9) content.hpf 에 이미지 등록
    if extra_items:
        hpf = hpf.replace('<opf:item id="headersc"',
                          "".join(extra_items) + '<opf:item id="headersc"', 1)

    # 10) 첫 질문의 "네,아니오" 글자색을 검게 (원본은 파란색)
    hdr = base64.b64decode(TPL["Contents/header.xml"]).decode("utf-8")
    hdr = hdr.replace('<hh:charPr id="16" height="1000" textColor="#3057B9"',
                      '<hh:charPr id="16" height="1000" textColor="#000000"', 1)

    # 11) zip 으로 묶기 (mimetype 은 반드시 첫 항목·무압축)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), base64.b64decode(TPL["mimetype"]),
                   zipfile.ZIP_STORED)
        for name in ZIP_ORDER:
            if name == "Contents/section0.xml":
                data = sec0.encode("utf-8")
            elif name == "Contents/section1.xml" and sec1 is not None:
                data = sec1.encode("utf-8")
            elif name == "Contents/content.hpf":
                data = hpf.encode("utf-8")
            elif name == "Contents/header.xml":
                data = hdr.encode("utf-8")
            else:
                data = base64.b64decode(TPL[name])
            z.writestr(name, data, zipfile.ZIP_DEFLATED)
        for name, data in bins + extra_bins:
            z.writestr(name, data, zipfile.ZIP_DEFLATED)
    return out.getvalue()
