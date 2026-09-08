import sys,time
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
from unittest.mock import patch
from PIL import Image
from lxml import etree as ET
from PySide6.QtWidgets import QApplication,QFileDialog,QMessageBox
from PySide6.QtCore import QDate,QProcess,QUrl,QMimeData
from main import Window
app=QApplication([])
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
w=Window(profile_dir=out/'profile');w.show()
def ready():
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        app.processEvents();time.sleep(.02)
        if w.ready_bytes and w.render_revision==w.revision and w.process.state()==QProcess.NotRunning:return
    raise AssertionError(w.status.text())
def document_text():
    ready()
    with ZipFile(BytesIO(w.ready_bytes)) as z:return ''.join(ET.fromstring(z.read('Contents/section0.xml')).itertext())
w.roles['teacher'][0].setChecked(True);w.roles['teacher'][1].setText('공통강사')
w.place.setText('공통장소');w.date.setDate(QDate(2026,9,8))
w.education_id.setText('FIRST');w.course.setCurrentIndex(0)
w.add_lesson();assert w.photo_list.count()==6
w.education_id.setText('SECOND');w.course.setCurrentIndex(2);w.times[0].setCurrentIndex(13);w.times[2].setCurrentIndex(14)
# Editing the first lesson without switching the preview.
w.lessons[1]['education_id'].setText('FIRST-EDITED');assert w.active_lesson==2
app.processEvents();assert all(row.isVisible() for data in w.lessons.values() for row in data['rows'])
assert w.common_section.content.isVisible() and w.individual_section.content.isVisible()
w.common_section.toggle.click();assert not w.common_section.content.isVisible()
w.common_section.toggle.click();assert w.common_section.content.isVisible()
w.individual_section.toggle.click();assert not w.individual_section.content.isVisible()
w.individual_section.toggle.click();assert w.individual_section.content.isVisible()
paths=[]
for i,color in enumerate(['red','green','blue','yellow','purple','orange']):
    path=out/f'{i}.png';Image.new('RGB',(60,100),color).save(path);paths.append(str(path.resolve()))
with patch.object(QFileDialog,'getOpenFileNames',return_value=(paths,'')):w.upload_many()
assert all(p is not None for d in w.lessons.values() for p in d['photos'])
red=w.lessons[1]['photos'][0];yellow=w.lessons[2]['photos'][0]
w.photo_list.setCurrentRow(2);blue=w.lessons[1]['photos'][2];w.move_photo(1)
assert w.lessons[2]['photos'][0] is blue and w.lessons[1]['photos'][2] is yellow
with patch.object(QMessageBox,'information') as info:
    w.insert_photos([(red,'overflow')]);info.assert_called_once()
assert w.lessons[2]['photos'][0] is blue
w.roles['assistant'][0].setChecked(True);w.roles['assistant'][1].setText('공통보조')
w.submitter_choice.setCurrentIndex(w.submitter_choice.findData('assistant'))
w.place.setText('변경된 공통장소');w.date.setDate(QDate(2026,10,12))
w.signature=Image.new('RGBA',(60,30),(0,0,0,100));w.signature_enabled.setEnabled(True);w.signature_enabled.setChecked(True)
for index,identity,hour in [(0,'FIRST-EDITED',10),(1,'SECOND',13)]:
    w.tabs.setCurrentIndex(index);text=document_text()
    assert identity in text and '변경된 공통장소' in text and '공통보조' in text and f'10월 12일 {hour}시' in text
    assert w.submitter.text()=='공통보조' and w.signature_enabled.isChecked()
    with patch.object(QFileDialog,'getSaveFileName',return_value=(str(out/f'{identity}.hwpx'),'')),patch.object(QMessageBox,'information'),patch.object(QMessageBox,'warning') as warning:
        w.save();warning.assert_not_called();assert (out/f'{identity}.hwpx').exists()
w.photo_list.setCurrentRow(5);w.clear_selected_photo();assert w.lessons[2]['photos'][2] is None
mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(paths[5])]);app.clipboard().setMimeData(mime);w.paste_many();assert w.lessons[2]['photos'][2] is not None
w.close_lesson(0);assert w.photo_list.count()==3
w.place.setText('닫은 뒤 공통 변경');w.restore_lesson();assert w.photo_list.count()==6 and w.state()['place']=='닫은 뒤 공통 변경'
assert w.lessons[1]['photos'][0] is red
w.tabs.moveTab(1,0);assert w.photo_slots()[0]==(1,0)
w.add_lesson();assert w.photo_list.count()==9 and w.state()['submitter']=='공통보조' and w.state()['place']=='닫은 뒤 공통 변경'
assert w.education_id.text()=='' and w.photos==[None]*3
w.select_lesson(1);ready();w.grab().save(str(out/'settings.png'))
from PySide6.QtWidgets import QScrollArea
sidebar=[x for x in w.findChildren(QScrollArea) if x is not w.view_scroll][0]
sidebar.verticalScrollBar().setValue(sidebar.verticalScrollBar().maximum());app.processEvents();w.grab().save(str(out/'photos.png'))
w.close();print('PASS: shared fields, all-lesson editing, bulk photos, cross-lesson reorder, clipboard, capacity, restore and HWPX saves')
