# -*- coding: utf-8 -*-
"""원본 HWPX 양식을 `template_data.py` 로 변환한다.

양식 파일 자체는 이 저장소에 포함하지 않는다(원본 서식의 저작권, 그리고
원본에 들어 있을 수 있는 서명 이미지·기관 정보 때문). 각자 가지고 있는
양식으로 이 스크립트를 한 번 돌려서 `template_data.py` 를 만든 뒤 실행한다.

    python make_template.py 양식.hwpx
"""

import base64
import os
import sys
import zipfile

# `hwpx_builder` 가 값을 갈아끼울 때 필요한 파일들
NEEDED = [
    "mimetype", "version.xml", "settings.xml",
    "META-INF/container.xml", "META-INF/container.rdf", "META-INF/manifest.xml",
    "Contents/content.hpf", "Contents/header.xml",
    "Contents/section0.xml", "Contents/section1.xml",
]
OPTIONAL = [
    "Scripts/headerScripts", "Scripts/sourceScripts",
    "Preview/PrvText.txt", "Preview/PrvImage.png", "BinData/image1.png",
]

# 값을 바꿔 넣을 자리. 하나라도 없으면 다른 양식이라는 뜻이다.
ANCHORS = [
    ('<hp:cellAddr colAddr="4" rowAddr="1"/>', "교육실시ID 칸"),
    ('<hp:cellAddr colAddr="0" rowAddr="4"/>', "전 사진칸"),
    ('<hp:cellAddr colAddr="2" rowAddr="4"/>', "중 사진칸"),
    ('<hp:cellAddr colAddr="6" rowAddr="4"/>', "후 사진칸"),
    ('paraPrIDRef="24"', "강사/교육장소 줄"),
    ("<hp:t>제출자:", "제출자 줄"),
    ("<hp:t>8월 31일", "교육일자 칸"),
    ("[에듀버스2]", "교육과정명 칸"),
]


def main(src, out="template_data.py"):
    if not zipfile.is_zipfile(src):
        sys.exit("HWPX 파일이 아닙니다: %s" % src)
    z = zipfile.ZipFile(src)
    names = set(z.namelist())

    missing = [n for n in NEEDED if n not in names]
    if missing:
        sys.exit("양식에 없는 파일이 있습니다: %s" % ", ".join(missing))

    sec0 = z.read("Contents/section0.xml").decode("utf-8")
    bad = [why for tag, why in ANCHORS if tag not in sec0]
    if bad:
        sys.exit("이 양식에는 아래 자리가 없어 값을 채울 수 없습니다.\n  - "
                 + "\n  - ".join(bad))

    with open(out, "w", encoding="utf-8") as f:
        f.write("# -*- coding: utf-8 -*-\n")
        f.write("# 원본 hwpx 양식 (make_template.py 가 자동 생성. 저장소에 올리지 말 것)\n")
        f.write("TPL = {\n")
        for n in NEEDED + OPTIONAL:
            if n not in names:
                continue
            f.write("  %r: %r,\n" % (n, base64.b64encode(z.read(n)).decode()))
        f.write("}\n")
    print("%s 생성 완료 (%.0f KB)" % (out, os.path.getsize(out) / 1024.0))
    if "BinData/image1.png" in names:
        print("주의: 원본에 들어 있던 이미지(서명 등)도 함께 담겼습니다. "
              "이 파일은 공개 저장소에 올리지 마세요.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("사용법: python make_template.py 양식.hwpx")
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "template_data.py")
