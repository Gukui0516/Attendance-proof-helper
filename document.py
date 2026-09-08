"""Original-template HWPX editor. No network or installed office application."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED
from copy import deepcopy
from io import BytesIO
from lxml import etree as ET
from PIL import Image, ImageOps, ImageChops
import re

COURSES = [
    '[지역특화] [에듀버스3] 2026 무엇이든 물어보세요',
    '[에듀버스2] 2026 디지털 기기와  콘텐츠 보호',
    '[에듀버스1] 2026년 AI와 건강관리 앱으로 건강정보 챙기기',
]

def load_photo(path):
    with Image.open(path) as source:
        source.load()
        return ImageOps.exif_transpose(source).convert('RGB')

def photo_canvas(source):
    # Exact aspect of the template photo cells; height always filled.
    w, h = 1600, round(1600 * 22170 / 24023)
    scaled = source.resize((max(1, round(source.width * h / source.height)), h), Image.Resampling.LANCZOS)
    if scaled.width > w:
        left = (scaled.width - w) // 2
        scaled = scaled.crop((left, 0, left + w, h))
    canvas = Image.new('RGB', (w, h), 'white')
    canvas.paste(scaled, ((w-scaled.width)//2, 0))
    return canvas

def prepare_signature(path):
    """Preserve existing alpha; remove paper white without an online service."""
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert('RGBA')
    rgb = image.convert('RGB')
    # Light paper becomes transparent, dark strokes remain opaque.
    gray = ImageOps.grayscale(rgb)
    ink = gray.point(lambda p: max(0, min(255, round((248-p)*255/180))))
    image.putalpha(ImageChops.multiply(image.getchannel('A'), ink))
    bounds = image.getchannel('A').getbbox()
    if not bounds: raise ValueError('서명 선을 찾을 수 없습니다. 흰 배경에 진한 서명이 있는 이미지를 선택하세요.')
    image = image.crop(bounds)
    image.thumbnail((1600,800),Image.Resampling.LANCZOS)
    return image

def output_filename(state):
    def safe(value): return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value.strip()).rstrip('. ')
    return f"{safe(state['education_id'])}_출결증빙자료_{safe(state['submitter'])}.hwpx"

def make_document(template, state, photos, signature=None):
    with ZipFile(template) as z:
        files = {i.filename: z.read(i.filename) for i in z.infolist()}
    parser = ET.XMLParser(resolve_entities=False, no_network=True)
    root = ET.fromstring(files['Contents/section0.xml'], parser)
    ns = root.nsmap
    def element(prefix, tag, **attrs):
        return ET.Element('{'+ns[prefix]+'}'+tag, **{k:str(v) for k,v in attrs.items()})
    table = root.find('.//hp:tbl', ns)
    cells = {}
    for cell in table.findall('hp:tr/hp:tc', ns):
        a = cell.find('hp:cellAddr', ns)
        cells[int(a.get('rowAddr')), int(a.get('colAddr'))] = cell
    picture_model = deepcopy(root.find('.//hp:pic', ns))
    checked_footer = deepcopy(cells[5,0].find('hp:subList/hp:p', ns))
    for obj in checked_footer.findall('.//hp:pic', ns): obj.getparent().remove(obj)
    for brush in checked_footer.findall('.//hp:ellipse/hc:fillBrush', ns): brush.getparent().remove(brush)
    for circle in checked_footer.findall('.//hp:ellipse', ns):
        pos = circle.find('hp:pos', ns)
        correction = {40558: 625, 67158: 1250}.get(int(pos.get('horzOffset')), 0)
        pos.set('horzOffset', str(int(pos.get('horzOffset')) - correction))
    # The latest reference uses black text for all three confirmation items.
    for run in checked_footer.findall('.//hp:run',ns):
        if run.get('charPrIDRef')=='16':run.set('charPrIDRef','13')
    # Remove existing handwritten signature and preselected circles.
    for tag in ('pic', 'ellipse'):
        for obj in root.findall('.//hp:'+tag, ns):
            obj.getparent().remove(obj)
    def set_paragraph(p, text, char=None):
        run = p.find('hp:run', ns)
        style = char or (run.get('charPrIDRef') if run is not None else '11')
        for child in list(p): p.remove(child)
        r = element('hp', 'run', charPrIDRef=style)
        t = element('hp', 't'); t.text = text; r.append(t); p.append(r)
    def set_cell(key, text):
        sub = cells[key].find('hp:subList', ns)
        p = sub.find('hp:p', ns)
        for extra in list(sub)[1:]: sub.remove(extra)
        p.set('paraPrIDRef', '25')
        set_paragraph(p, text, '11')
    roles = [f'{label}: {state[key].strip()}' for key,label in [('teacher','강사'),('assistant','보조강사')] if state[key+'_enabled']]
    top = cells[0,0].find('hp:subList', ns).findall('hp:p', ns)[-1]
    set_paragraph(top, ' / '.join(roles + ['교육장소 : '+state['place'].strip()]))
    set_cell((1,1), state['course'])
    set_cell((1,4), state['education_id'].strip())
    set_cell((1,7), state['date_text'])
    bottom = cells[5,0].find('hp:subList', ns).findall('hp:p', ns)
    bottom[0].getparent().replace(bottom[0], checked_footer)
    set_paragraph(bottom[1], '제출자: '+state.get('submitter','').strip()+'   (서명)', '14')
    manifest = ET.fromstring(files['Contents/content.hpf'], parser)
    items = manifest.find('opf:manifest', ns)
    for item in list(items):
        if item.get('id') == 'image1': items.remove(item)
    files.pop('BinData/image1.png', None)
    if signature is not None:
        # Anchor to the submitter paragraph; align to the right-hand (서명).
        pic = deepcopy(picture_model)
        width = min(4400, round(1900*signature.width/signature.height))
        height = min(1900, round(width*signature.height/signature.width))
        pic.set('id','2100000000');pic.set('instid','2100000000');pic.set('zOrder','30')
        pic.set('textWrap','BEHIND_TEXT')
        pic.find('hp:offset',ns).attrib.update(dict(x='0',y='0'))
        for tag in ('orgSz','curSz','sz'):pic.find('hp:'+tag,ns).attrib.update(dict(width=str(width),height=str(height)))
        pic.find('hp:rotationInfo',ns).attrib.update(dict(centerX=str(width//2),centerY=str(height//2)))
        for matrix in pic.find('hp:renderingInfo',ns):matrix.attrib.update(dict(e1='1',e2='0',e3='0',e4='0',e5='1',e6='0'))
        pic.find('hc:img',ns).set('binaryItemIDRef','user_signature')
        for pt,(x,y) in zip(pic.find('hp:imgRect',ns),[(0,0),(width,0),(width,height),(0,height)]):pt.attrib.update(dict(x=str(x),y=str(y)))
        pic.find('hp:imgClip',ns).attrib.update(dict(left='0',right=str(width),top='0',bottom=str(height)))
        pic.find('hp:imgDim',ns).attrib.update(dict(dimwidth=str(width),dimheight=str(height)))
        pic.find('hp:pos',ns).attrib.update(dict(treatAsChar='0',vertRelTo='PARA',horzRelTo='COLUMN',vertAlign='TOP',horzAlign='LEFT',horzOffset=str(71800-width),vertOffset=str((650-height//2) % 2**32)))
        bottom[1].find('hp:run',ns).insert(0,pic)
        buf=BytesIO();signature.save(buf,format='PNG');files['BinData/user_signature.png']=buf.getvalue()
        items.append(element('opf','item',id='user_signature',href='BinData/user_signature.png',**{'media-type':'image/png','isEmbeded':'1'}))
    for index, (column, source) in enumerate(zip((0,2,6), photos)):
        if source is None: continue
        c = cells[4,column]
        c.set('hasMargin','1')
        for k in ('left','right','top','bottom'): c.find('hp:cellMargin',ns).set(k,'0')
        sub = c.find('hp:subList',ns)
        p = sub.find('hp:p',ns)
        for extra in list(sub)[1:]: sub.remove(extra)
        set_paragraph(p, '', '21')
        pic = deepcopy(picture_model)
        ident = 2000000000+index
        pic.set('id',str(ident));pic.set('instid',str(ident));pic.set('zOrder',str(20+index))
        pic.set('textWrap','TOP_AND_BOTTOM')
        w,h = 24023,22170
        pic.find('hp:offset',ns).attrib.update(dict(x='0',y='0'))
        for tag in ('orgSz','curSz','sz'):
            pic.find('hp:'+tag,ns).attrib.update(dict(width=str(w),height=str(h)))
        pic.find('hp:rotationInfo',ns).attrib.update(dict(centerX=str(w//2),centerY=str(h//2)))
        for m in pic.find('hp:renderingInfo',ns):
            m.attrib.update(dict(e1='1',e2='0',e3='0',e4='0',e5='1',e6='0'))
        imgid = f'proof_photo_{index}'
        pic.find('hc:img',ns).set('binaryItemIDRef',imgid)
        for pt,(x,y) in zip(pic.find('hp:imgRect',ns),[(0,0),(w,0),(w,h),(0,h)]): pt.attrib.update(dict(x=str(x),y=str(y)))
        pic.find('hp:imgClip',ns).attrib.update(dict(left='0',right=str(w),top='0',bottom=str(h)))
        pic.find('hp:imgDim',ns).attrib.update(dict(dimwidth=str(w),dimheight=str(h)))
        pic.find('hp:pos',ns).attrib.update(dict(treatAsChar='1',affectLSpacing='0',vertRelTo='PARA',horzRelTo='PARA',vertOffset='0',horzOffset='0',vertAlign='TOP',horzAlign='LEFT'))
        p.find('hp:run',ns).insert(0,pic)
        buf = BytesIO();photo_canvas(source).save(buf,format='JPEG',quality=94)
        path = f'BinData/{imgid}.jpg';files[path] = buf.getvalue()
        items.append(element('opf','item',id=imgid,href=path,**{'media-type':'image/jpeg','isEmbeded':'1'}))
    # Old layout caches must not describe the edited paragraphs.
    for cache in root.findall('.//hp:linesegarray',ns): cache.getparent().remove(cache)
    files['Contents/section0.xml'] = ET.tostring(root,encoding='UTF-8',xml_declaration=True)
    files['Contents/content.hpf'] = ET.tostring(manifest,encoding='UTF-8',xml_declaration=True)
    files['Preview/PrvText.txt'] = '\n'.join(root.itertext()).encode('utf-8')
    files.pop('Preview/PrvImage.png',None)
    stream = BytesIO()
    with ZipFile(stream,'w',ZIP_DEFLATED) as z:
        z.writestr('mimetype',files.pop('mimetype'),compress_type=ZIP_STORED)
        for name,data in files.items(): z.writestr(name,data)
    return stream.getvalue()
