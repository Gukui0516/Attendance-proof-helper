"""Run with Python + development requirements; uses synthetic photos only."""
import sys, tempfile, time
from pathlib import Path
from zipfile import ZipFile
from io import BytesIO
from unittest.mock import patch
from PIL import Image, ImageDraw
from lxml import etree as ET
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PySide6.QtCore import QDate, QProcess
from PySide6.QtGui import QImage
from document import make_document, COURSES, photo_canvas, output_filename
from main import Window, BASE

def run():
    app=QApplication.instance() or QApplication([])
    folder=Path(sys.argv[1]) if len(sys.argv)>1 else Path(tempfile.mkdtemp())
    folder.mkdir(parents=True,exist_ok=True)
    import uuid
    profile=folder/"profile"/uuid.uuid4().hex
    w=Window(profile_dir=profile);w.show()
    photos=[Image.new('RGB',s,c) for s,c in [((600,1000),'#80aacc'),((1600,900),'#bcd19a'),((900,900),'#e6b58c')]]
    for index,im in enumerate(photos):
        path=folder/f'photo{index}.png';im.save(path)
        with patch.object(QFileDialog,'getOpenFileName',return_value=(str(path),'')):w.upload(index)
    w.roles['teacher'][0].setChecked(True);w.roles['teacher'][1].setText('홍길동')
    w.roles['assistant'][1].setText('숨겨진이름')
    w.place.setText('제대병원 1층 로비');w.education_id.setText('TEST-20260908');w.date.setDate(QDate(2026,9,8))
    w.course.setCurrentIndex(2)
    w.calendar.setSelectedDate(QDate(2026,10,15));assert w.date.date()==QDate(2026,10,15) and '10월 15일' in w.state()['date_text']
    w.calendar.showPreviousMonth();assert w.calendar_title.text()=='2026년 9월'
    w.calendar.setSelectedDate(QDate(2026,9,8))
    assert all([w.times[i].itemText(j) for j in range(w.times[i].count())]==['00','30'] for i in (1,3))
    end=time.monotonic()+20
    while time.monotonic()<end:
        app.processEvents();time.sleep(.02)
        if w.ready_bytes and w.render_revision==w.revision and w.process.state()==QProcess.NotRunning:break
    assert w.ready_bytes and w.render_revision==w.revision,w.status.text()
    assert w.svg.renderer().isValid()
    with ZipFile(BytesIO(w.ready_bytes)) as archive:
        assert archive.testzip() is None
        root=ET.fromstring(archive.read('Contents/section0.xml'));text=''.join(root.itertext())
        assert '강사: 홍길동' in text and '숨겨진이름' not in text
        assert '9월 8일 10시 30분 ~ 11시 30분' in text
        assert len(root.findall('.//hp:pic',root.nsmap))==3
        assert 'BinData/image1.png' not in archive.namelist()
        with ZipFile(BASE/'template.hwpx') as original:assert archive.read('Contents/section1.xml')==original.read('Contents/section1.xml')
    for course in COURSES:
        state=w.state();state['course']=course;state['assistant_enabled']=True
        output=make_document(BASE/'template.hwpx',state,photos)
        with ZipFile(BytesIO(output)) as z:
            text=''.join(ET.fromstring(z.read('Contents/section0.xml')).itertext())
            assert course in text and '보조강사: 숨겨진이름' in text
    output=folder/'saved.hwpx'
    with patch.object(QFileDialog,'getSaveFileName',return_value=(str(output),'')),patch.object(QMessageBox,'information'),patch.object(QMessageBox,'warning') as warning:
        w.save();assert output.exists();warning.assert_not_called()
    with ZipFile(output) as z:assert 'Preview/PrvImage.png' in z.namelist();assert z.testzip() is None
    assert w.state()['submitter']=='홍길동'
    w.roles['assistant'][0].setChecked(True);w.roles['assistant'][1].setText('오상협')
    w.submitter_choice.setCurrentIndex(w.submitter_choice.findData('assistant'))
    assert w.state()['submitter']=='오상협'
    assert output_filename(w.state())=='TEST-20260908_출결증빙자료_오상협.hwpx'
    sign=Image.new('RGB',(400,150),'white');draw=ImageDraw.Draw(sign)
    draw.line([(20,110),(95,30),(80,120),(200,40),(165,100),(320,60),(380,100)],fill='black',width=9)
    signpath=folder/'signature-input.png';sign.save(signpath)
    with patch.object(QFileDialog,'getOpenFileName',return_value=(str(signpath),'')):w.upload_signature()
    assert w.signature.mode=='RGBA' and w.signature.getchannel('A').getextrema()==(0,255)
    assert (profile/'signature.png').exists()
    end=time.monotonic()+20
    while time.monotonic()<end:
        app.processEvents();time.sleep(.02)
        if w.ready_bytes and w.render_revision==w.revision and w.process.state()==QProcess.NotRunning:break
    signed=folder/'signed.hwpx'
    with patch.object(QFileDialog,'getSaveFileName',return_value=(str(signed),'')),patch.object(QMessageBox,'information'),patch.object(QMessageBox,'warning') as warning:
        w.save();warning.assert_not_called()
    with ZipFile(signed) as z:
        root=ET.fromstring(z.read('Contents/section0.xml'));text=''.join(root.itertext())
        assert '제출자: 오상협' in text and '보조강사: 오상협' in text
        assert len(root.findall('.//hp:pic',root.nsmap))==4
        with Image.open(BytesIO(z.read('BinData/user_signature.png'))) as im:assert im.mode=='RGBA' and im.getchannel('A').getextrema()==(0,255)
    w.grab().save(str(folder/'app.png'))
    other=Window(profile_dir=profile)
    assert other.signature is not None and other.signature_enabled.isChecked()
    other.close()

    w.clear_photo(0)
    with patch.object(QFileDialog,'getSaveFileName') as dialog,patch.object(QMessageBox,'information') as info:
        w.save();dialog.assert_not_called();info.assert_called_once()
    class FakeMime:
        def hasImage(self):return True
    class FakeClipboard:
        def mimeData(self):return FakeMime()
        def image(self):
            im=QImage(100,200,QImage.Format_RGB32);im.fill(0xff123456);return im
    with patch.object(QApplication,'clipboard',return_value=FakeClipboard()):w.paste(0)
    assert w.photos[0].size==(100,200)
    w.close();print('PASS: roles, all courses, date/minutes, upload, clipboard, photo geometry, actual render, HWPX save, missing-photo validation, second-section preservation, submitter selection, transparent signature persistence, filename')

if __name__=='__main__':run()
