"""Keep document font sizes/colors; resolve SVG font lists for Qt SVG."""
from lxml import etree as ET
from PySide6.QtGui import QFontDatabase

def resolve_svg_fonts(path):
    root=ET.parse(str(path),ET.XMLParser(resolve_entities=False,no_network=True))
    available={name.casefold():name for name in QFontDatabase.families()}
    for node in root.iter():
        family=node.get('font-family')
        if not family:continue
        candidates=[name.strip().strip("'\"") for name in family.split(',')]
        selected=next((available[name.casefold()] for name in candidates if name.casefold() in available),None)
        if selected is None:selected=available.get('batang',available.get('바탕','serif'))
        node.set('font-family',selected)
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)

def font_status():
    available={name.casefold() for name in QFontDatabase.families()}
    return '문서 글꼴: 휴먼명조' if '휴먼명조' in available else '휴먼명조 미설치 · 미리보기는 바탕체로 대체 (설치 후 앱 재실행)'

def form_view(path):
    root=ET.parse(str(path),ET.XMLParser(resolve_entities=False,no_network=True)).getroot()
    root.set('viewBox','60 110 995 565');root.set('width','995');root.set('height','565')
    return ET.tostring(root,encoding='utf-8')
