# -*- coding: utf-8 -*-
"""원본 hwpx 양식의 값만 바꿔 새 hwpx를 만든다. 한글(HWP) 설치 불필요."""

import base64
import io
import re
import zipfile
from xml.sax.saxutils import escape

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


# ---- 본체 --------------------------------------------------------------
def build_hwpx(st, photos, signature, sig_scale=1.0, sig_dx=0, sig_dy=0):
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

    # 8) content.hpf 에 이미지 등록
    if extra_items:
        hpf = hpf.replace('<opf:item id="headersc"',
                          "".join(extra_items) + '<opf:item id="headersc"', 1)

    # 9) zip 으로 묶기 (mimetype 은 반드시 첫 항목·무압축)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), base64.b64decode(TPL["mimetype"]),
                   zipfile.ZIP_STORED)
        for name in ZIP_ORDER:
            if name == "Contents/section0.xml":
                data = sec0.encode("utf-8")
            elif name == "Contents/content.hpf":
                data = hpf.encode("utf-8")
            else:
                data = base64.b64decode(TPL[name])
            z.writestr(name, data, zipfile.ZIP_DEFLATED)
        for name, data in bins + extra_bins:
            z.writestr(name, data, zipfile.ZIP_DEFLATED)
    return out.getvalue()
