import sys, json, os, tempfile
from pathlib import Path
from io import BytesIO
from PIL import Image
from PySide6.QtCore import Qt, QDate, QTimer, QProcess, QByteArray, QBuffer, QIODevice, QStandardPaths, QSaveFile, QLocale
from PySide6.QtGui import QImage, QPixmap, QShortcut, QKeySequence, QPainter, QColor, QTextCharFormat
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,QCheckBox,QComboBox,QDateEdit,QPushButton,QScrollArea,QSplitter,QFileDialog,QMessageBox,QGroupBox,QCalendarWidget,QTabBar,QListWidget,QListWidgetItem)
from document import COURSES, load_photo, make_document, prepare_signature, output_filename
from preview import resolve_svg_fonts, font_status, form_view

BASE = Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))

class Calendar(QCalendarWidget):
    def paintCell(self,painter,rect,date):
        painter.save();painter.fillRect(rect,QColor('white'))
        if date.month()==self.monthShown() and date.year()==self.yearShown():
            selected=date==self.selectedDate()
            if selected:painter.fillRect(rect.adjusted(5,2,-5,-2),QColor('#2563eb'))
            color='#ffffff' if selected else ('#ef4444' if date.dayOfWeek()==7 else '#2563eb' if date.dayOfWeek()==6 else '#243448')
            painter.setPen(QColor(color));painter.drawText(rect,Qt.AlignCenter,str(date.day()))
        painter.restore()

class Collapsible(QWidget):
    def __init__(self,title,expanded=True):
        super().__init__()
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(8)
        self.toggle=QPushButton();self.toggle.setObjectName('sectionToggle');self.toggle.setCheckable(True);self.toggle.setChecked(expanded)
        self.content=QWidget();self.body_layout=QVBoxLayout(self.content);self.body_layout.setContentsMargins(0,0,0,0);self.body_layout.setSpacing(10)
        self.title=title;self.toggle.toggled.connect(self.set_expanded);layout.addWidget(self.toggle);layout.addWidget(self.content)
        self.set_expanded(expanded)

    def set_expanded(self,expanded):
        self.content.setVisible(expanded);self.toggle.setText(('▼  ' if expanded else '▶  ')+self.title)

class Window(QMainWindow):
    def __init__(self, profile_dir=None):
        super().__init__()
        self.setWindowTitle('증빙 니가해 · Attendance Proof Helper')
        self.resize(1480,930)
        self._restoring=False;self.lessons={};self.active_lesson=None;self.lesson_number=0;self.closed_lessons=[]
        self.photos=[None]*3; self.photo_labels=[]; self.active_photo=0
        self.profile_dir=Path(profile_dir) if profile_dir else Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation))/'AttendanceProofHelper'
        self.signature=None
        self.signature_error=''
        try:
            if (self.profile_dir/'signature.png').exists():
                with Image.open(self.profile_dir/'signature.png') as saved:self.signature=saved.convert('RGBA')
        except Exception as exc:self.signature_error='저장된 서명을 읽지 못했습니다. 다시 선택하세요.'
        self.temp=tempfile.TemporaryDirectory(prefix='attendance-proof-')
        self.work=Path(self.temp.name); self.revision=0; self.render_revision=-1
        self.current_bytes=None; self.ready_bytes=None; self.pending_save=False
        self.process=QProcess(self); self.process.finished.connect(self.render_done)
        self.process.errorOccurred.connect(self.render_error)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(250);self.timer.timeout.connect(self.render)
        central=QWidget();central_layout=QVBoxLayout(central);central_layout.setContentsMargins(0,0,0,0);central_layout.setSpacing(0);self.setCentralWidget(central)
        tabs_row=QHBoxLayout();tabs_row.setContentsMargins(10,8,10,0)
        self.tabs=QTabBar();self.tabs.setTabsClosable(True);self.tabs.setMovable(True);self.tabs.setExpanding(False);self.tabs.setDrawBase(False)
        self.tabs.setStyleSheet('QTabBar::tab{background:#e4eaf2;padding:10px 22px;border-top-left-radius:7px;border-top-right-radius:7px;min-width:65px} QTabBar::tab:selected{background:white;color:#2563eb;font-weight:bold}')
        self.tabs.currentChanged.connect(self.switch_lesson);self.tabs.tabCloseRequested.connect(self.close_lesson);self.tabs.tabMoved.connect(self.refresh_order)
        add=QPushButton('+');add.setFixedSize(34,32);add.setToolTip('새 교시 (Ctrl+T)');add.clicked.connect(self.add_lesson)
        restore=QPushButton('닫은 교시 복원');restore.setToolTip('Ctrl+Shift+T');restore.clicked.connect(self.restore_lesson)
        tabs_row.addWidget(self.tabs);tabs_row.addWidget(add);tabs_row.addStretch();tabs_row.addWidget(restore);central_layout.addLayout(tabs_row)
        splitter=QSplitter();central_layout.addWidget(splitter,1)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setMinimumWidth(395);scroll.setMaximumWidth(560)
        left=QWidget(); panel=QVBoxLayout(left);panel.setContentsMargins(22,20,22,20);panel.setSpacing(15);scroll.setWidget(left);sidebar=QWidget();sidebar_layout=QVBoxLayout(sidebar);sidebar_layout.setContentsMargins(0,0,0,0);sidebar_layout.addWidget(scroll);splitter.addWidget(sidebar)
        title=QLabel('증빙 니가해');title.setObjectName('title');panel.addWidget(title)
        panel.addWidget(QLabel('공통 정보를 한 번 입력하고 아래에서 모든 교시를 편집하세요.'))
        self.common_section=Collapsible('공통 설정');panel.addWidget(self.common_section)
        common_layout=self.common_section.body_layout
        group=QGroupBox('공통 · 강사 / 보조강사');form=QFormLayout(group)
        self.roles={}
        for key,label in [('teacher','강사'),('assistant','보조강사')]:
            cb=QCheckBox(label); edit=QLineEdit();edit.setPlaceholderText('이름');edit.setMaxLength(25);edit.setEnabled(False)
            cb.toggled.connect(edit.setEnabled);cb.toggled.connect(self.changed);edit.textChanged.connect(self.changed)
            form.addRow(cb,edit);self.roles[key]=(cb,edit)
        common_layout.addWidget(group)
        group=QGroupBox('공통 · 교육장소');form=QFormLayout(group)
        self.place=QLineEdit();self.place.setPlaceholderText('교육장소를 입력하세요');self.place.setMaxLength(100)
        form.addRow('교육장소',self.place);self.place.textChanged.connect(self.changed);common_layout.addWidget(group)
        group=QGroupBox('공통 · 교육 월 / 날짜');form=QFormLayout(group)
        self.date=QDateEdit(QDate.currentDate(),group);self.date.hide()
        self.calendar=Calendar();self.calendar.setLocale(QLocale('ko_KR'));self.calendar.setFirstDayOfWeek(Qt.Sunday)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader);self.calendar.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
        self.calendar.setGridVisible(False);self.calendar.setSelectedDate(self.date.date());self.calendar.setFixedHeight(190);self.calendar.setNavigationBarVisible(False)
        nav=QWidget();nav_layout=QHBoxLayout(nav);nav_layout.setContentsMargins(0,0,0,0)
        previous=QPushButton('‹');previous.setFixedWidth(32);previous.clicked.connect(self.calendar.showPreviousMonth)
        following=QPushButton('›');following.setFixedWidth(32);following.clicked.connect(self.calendar.showNextMonth)
        self.calendar_title=QLabel();self.calendar_title.setAlignment(Qt.AlignCenter)
        def month_title(year,month):self.calendar_title.setText(f'{year}년 {month}월')
        self.calendar.currentPageChanged.connect(month_title);month_title(self.calendar.yearShown(),self.calendar.monthShown())
        nav_layout.addWidget(previous);nav_layout.addWidget(self.calendar_title,1);nav_layout.addWidget(following)
        for day,color in [(Qt.Sunday,'#ef4444'),(Qt.Saturday,'#2563eb')]:
            fmt=QTextCharFormat();fmt.setForeground(QColor(color));self.calendar.setWeekdayTextFormat(day,fmt)
        self.calendar.setStyleSheet('QCalendarWidget QWidget{background:white;color:#243448} QCalendarWidget QToolButton{background:white;color:#243448;font-weight:bold;padding:6px;border:none} QCalendarWidget QAbstractItemView{background:white;selection-background-color:#2563eb;selection-color:white;outline:0} QCalendarWidget QSpinBox{background:white;color:#243448}')
        self.calendar.selectionChanged.connect(lambda:self.date.setDate(self.calendar.selectedDate()))
        self.date.dateChanged.connect(self.calendar.setSelectedDate);self.date.dateChanged.connect(self.changed)
        form.addRow(nav);form.addRow(self.calendar)
        common_layout.addWidget(group)
        group=QGroupBox('공통 · 제출자 / 서명');form=QFormLayout(group)
        self.submitter_choice=QComboBox();self.submitter_choice.currentIndexChanged.connect(self.changed)
        self.submitter=QLineEdit();self.submitter.setReadOnly(True);self.submitter.setPlaceholderText('선택한 강사 이름과 자동 연동')
        form.addRow('제출자 선택',self.submitter_choice);form.addRow('제출자 이름',self.submitter)
        self.signature_label=QLabel();self.signature_label.setFixedHeight(60);self.signature_label.setAlignment(Qt.AlignCenter);self.signature_label.setStyleSheet('background:white;border:1px dashed #b4c3d4;')
        form.addRow(self.signature_label)
        self.signature_enabled=QCheckBox('저장된 서명 사용');self.signature_enabled.setChecked(self.signature is not None);self.signature_enabled.setEnabled(self.signature is not None);self.signature_enabled.toggled.connect(self.changed)
        signature_button=QPushButton('서명 이미지 선택 / 변경');signature_button.clicked.connect(self.upload_signature)
        form.addRow(self.signature_enabled);form.addRow(signature_button)
        note=QLabel('서명은 이 PC에 저장되어 다음 실행에도 유지됩니다.\n흰 배경은 투명하게 처리하며 (서명)과 겹쳐집니다.');note.setWordWrap(True);note.setObjectName('hint');form.addRow(note);common_layout.addWidget(group)
        self.update_signature_thumbnail()
        self.individual_section=Collapsible('개별 설정');panel.addWidget(self.individual_section)
        individual_layout=self.individual_section.body_layout
        group=QGroupBox('교육과정명 · 교시별');self.course_rows=QVBoxLayout(group);individual_layout.addWidget(group)
        group=QGroupBox('교육실시ID · 교시별');self.id_rows=QVBoxLayout(group);individual_layout.addWidget(group)
        group=QGroupBox('시작 · 종료시간 · 교시별');self.time_rows=QVBoxLayout(group);individual_layout.addWidget(group)
        group=QGroupBox('증빙사진 · 전체 교시 순서');photo_layout=QVBoxLayout(group)
        photo_layout.addWidget(QLabel('목록 순서대로 각 교시의 전 · 중 · 후에 배치합니다.'))
        buttons=QHBoxLayout()
        for label,fn in [('사진 여러 장 추가',self.upload_many),('붙여넣기',self.paste_many)]:
            button=QPushButton(label);button.clicked.connect(fn);buttons.addWidget(button)
        photo_layout.addLayout(buttons)
        self.photo_list=QListWidget();self.photo_list.setMinimumHeight(190);self.photo_list.setMaximumHeight(300);photo_layout.addWidget(self.photo_list)
        buttons=QHBoxLayout()
        for label,fn in [('↑ 앞으로',lambda:self.move_photo(-1)),('↓ 뒤로',lambda:self.move_photo(1)),('비우기',self.clear_selected_photo)]:
            button=QPushButton(label);button.clicked.connect(fn);buttons.addWidget(button)
        photo_layout.addLayout(buttons)
        note=QLabel('사진을 한꺼번에 추가하면 빈 위치부터 채웁니다.\n사진을 선택하고 ↑ ↓로 교시·전중후 위치를 바꾸세요.\n교시를 추가하면 사진 자리도 3개씩 늘어납니다.');note.setWordWrap(True);photo_layout.addWidget(note);individual_layout.addWidget(group)
        self.save_button=QPushButton('HWPX 저장');self.save_button.setObjectName('save');self.save_button.clicked.connect(self.save);sidebar_layout.addWidget(self.save_button);panel.addStretch()
        right=QWidget();layout=QVBoxLayout(right);layout.setContentsMargins(24,20,24,20)
        toolbar=QHBoxLayout();label=QLabel('문서 미리보기');label.setObjectName('heading');toolbar.addWidget(label);toolbar.addStretch()
        self.zoom_form=QCheckBox('양식 확대');self.zoom_form.setChecked(True);self.zoom_form.toggled.connect(self.show_page);toolbar.addWidget(self.zoom_form)
        self.page=QComboBox();self.page.addItems(['1 · 사진 증빙','2 · 교육 프로그램']);self.page.currentIndexChanged.connect(self.show_page);toolbar.addWidget(self.page);layout.addLayout(toolbar)
        self.status=QLabel('미리보기 준비 중…');layout.addWidget(self.status)
        self.font_note=QLabel(font_status());self.font_note.setWordWrap(True);layout.addWidget(self.font_note)
        self.view_scroll=QScrollArea();self.view_scroll.setWidgetResizable(True)
        self.svg=QSvgWidget();self.svg.setStyleSheet('background:white');self.view_scroll.setWidget(self.svg);layout.addWidget(self.view_scroll)
        foot=QLabel('로컬 실행 · 파일 외부 전송 없음 · 원본 HWPX 양식 사용');foot.setObjectName('hint');layout.addWidget(foot)
        splitter.addWidget(right);splitter.setSizes([435,1045])
        self.setStyleSheet('QWidget{background:#f7f9fc;font-family:"맑은 고딕";font-size:12px;color:#243448} QMainWindow{background:#eef2f6} QGroupBox{font-weight:bold;border:1px solid #d6dfe8;border-radius:8px;margin-top:12px;padding:14px 8px 8px} QGroupBox::title{subcontrol-origin:margin;left:12px} QLineEdit,QComboBox,QDateEdit{background:white;border:1px solid #ced7e1;border-radius:5px;padding:6px} QPushButton{background:#fff;border:1px solid #ccd7e2;border-radius:5px;padding:7px} QPushButton:hover{background:#e8f0fa} QPushButton#sectionToggle{background:#dce7f5;border:1px solid #bfd0e4;text-align:left;font-size:14px;font-weight:bold;padding:10px} QPushButton#sectionToggle:hover{background:#cedff2} QPushButton#save{background:#2563eb;color:white;font-size:15px;font-weight:bold;padding:13px} QLabel#title{font-size:26px;font-weight:bold} QLabel#heading{font-size:19px;font-weight:bold} QLabel#hint{color:#69788b;font-size:11px} QScrollArea{border:none} QCheckBox{spacing:7px}')
        self.add_lesson()
        QShortcut(QKeySequence('Ctrl+T'),self,activated=self.add_lesson)
        QShortcut(QKeySequence('Ctrl+W'),self,activated=lambda:self.close_lesson(self.tabs.currentIndex()))
        QShortcut(QKeySequence('Ctrl+Shift+T'),self,activated=self.restore_lesson)

    def lesson_keys(self):
        return [self.tabs.tabData(i) for i in range(self.tabs.count())]

    def add_lesson(self):
        self.lesson_number+=1;key=self.lesson_number
        course=QComboBox();course.addItems(COURSES);course.setCurrentIndex(1);course.setMinimumContentsLength(18);course.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        education_id=QLineEdit();education_id.setPlaceholderText('교육실시ID');education_id.setMaxLength(40)
        course_row=QWidget();course_layout=QHBoxLayout(course_row);course_layout.setContentsMargins(0,0,0,0);course_layout.addWidget(QLabel(f'{key}교시'));course_layout.addWidget(course,1)
        id_row=QWidget();id_layout=QHBoxLayout(id_row);id_layout.setContentsMargins(0,0,0,0);id_layout.addWidget(QLabel(f'{key}교시'));id_layout.addWidget(education_id,1)
        times=[]
        time_row=QWidget();time_layout=QVBoxLayout(time_row);time_layout.setContentsMargins(0,0,0,0)
        heading=QHBoxLayout();heading.addWidget(QLabel(f'{key}교시'));preview=QPushButton('미리보기');preview.clicked.connect(lambda checked=False,k=key:self.select_lesson(k));heading.addStretch();heading.addWidget(preview);time_layout.addLayout(heading)
        for label,hour in [('시작',10),('종료',11)]:
            row=QWidget();layout=QHBoxLayout(row);layout.setContentsMargins(0,0,0,0);layout.addWidget(QLabel(label))
            h=QComboBox();h.addItems([f'{i:02d}' for i in range(24)]);h.setCurrentIndex(hour)
            m=QComboBox();m.addItems(['00','30']);m.setCurrentIndex(1)
            layout.addWidget(h);layout.addWidget(QLabel('시'));layout.addWidget(m);layout.addWidget(QLabel('분'));times.extend([h,m]);time_layout.addWidget(row)
        rows=[course_row,id_row,time_row]
        self.lessons[key]={'rows':rows,'course':course,'education_id':education_id,'times':times,'photos':[None]*3,'photo_names':['']*3}
        for target,row in zip((self.course_rows,self.id_rows,self.time_rows),rows):target.addWidget(row)
        for widget in [course,*times]:widget.currentIndexChanged.connect(self.changed)
        course.currentTextChanged.connect(course.setToolTip);course.setToolTip(course.currentText());education_id.textChanged.connect(self.changed)
        self.tabs.blockSignals(True);index=self.tabs.addTab(f'{key}교시');self.tabs.setTabData(index,key);self.tabs.blockSignals(False)
        self.tabs.setCurrentIndex(index);self.switch_lesson(index);self.refresh_order()

    def select_lesson(self,key):
        self.tabs.setCurrentIndex(self.lesson_keys().index(key))

    def switch_lesson(self,index):
        if index<0:return
        key=self.tabs.tabData(index)
        if key not in self.lessons:return
        self.active_lesson=key;data=self.lessons[key]
        self.course=data['course'];self.education_id=data['education_id'];self.times=data['times'];self.photos=data['photos']
        self.ready_bytes=None;self.current_bytes=None
        self.svg.load(QByteArray(b'<svg xmlns="http://www.w3.org/2000/svg" width="995" height="565"><rect width="995" height="565" fill="white"/></svg>'))
        self.save_button.setText(f'{key}교시 HWPX 저장');self.changed()

    def refresh_order(self,*args):
        for key in self.lesson_keys():
            for target,row in zip((self.course_rows,self.id_rows,self.time_rows),self.lessons[key]['rows']):target.removeWidget(row);target.addWidget(row)
        self.refresh_photos()

    def close_lesson(self,index):
        if index<0:return
        key=self.tabs.tabData(index);data=self.lessons.pop(key)
        for target,row in zip((self.course_rows,self.id_rows,self.time_rows),data['rows']):row.hide();target.removeWidget(row)
        self.closed_lessons.append((key,self.tabs.tabText(index),data))
        if len(self.closed_lessons)>10:
            _,_,old=self.closed_lessons.pop(0)
            for row in old['rows']:row.deleteLater()
        self.tabs.blockSignals(True);self.tabs.removeTab(index);self.tabs.blockSignals(False)
        if self.tabs.count():self.switch_lesson(self.tabs.currentIndex())
        else:self.add_lesson()
        self.refresh_order()

    def restore_lesson(self):
        if not self.closed_lessons:return
        key,label,data=self.closed_lessons.pop();self.lessons[key]=data
        for target,row in zip((self.course_rows,self.id_rows,self.time_rows),data['rows']):target.addWidget(row);row.show()
        self.tabs.blockSignals(True);index=self.tabs.addTab(label);self.tabs.setTabData(index,key);self.tabs.blockSignals(False)
        self.tabs.setCurrentIndex(index);self.switch_lesson(index);self.refresh_order()

    def photo_slots(self):
        return [(key,i) for key in self.lesson_keys() for i in range(3)]

    def refresh_photos(self,selected=None):
        if selected is None:selected=self.photo_list.currentRow()
        self.photo_list.clear()
        for key,i in self.photo_slots():
            data=self.lessons[key];name=data['photo_names'][i] or ('사진 있음' if data['photos'][i] is not None else '사진 없음')
            self.photo_list.addItem(f"{key}교시 · {['전','중','후'][i]}   {name}")
        if self.photo_list.count():self.photo_list.setCurrentRow(max(0,min(selected,self.photo_list.count()-1)))

    def insert_photos(self,items):
        slots=[(key,i) for key,i in self.photo_slots() if self.lessons[key]['photos'][i] is None]
        if len(items)>len(slots):
            QMessageBox.information(self,'사진 자리 부족',f'빈 자리는 {len(slots)}개입니다. 교시를 추가한 뒤 다시 넣어주세요.');return
        for (photo,name),(key,i) in zip(items,slots):self.lessons[key]['photos'][i]=photo;self.lessons[key]['photo_names'][i]=name
        self.refresh_photos();self.changed()

    def upload_many(self):
        paths,_=QFileDialog.getOpenFileNames(self,'증빙사진 여러 장 선택','','이미지 (*.jpg *.jpeg *.png *.bmp *.webp)')
        if not paths:return
        try:self.insert_photos([(load_photo(path),Path(path).name) for path in paths])
        except Exception as exc:QMessageBox.warning(self,'사진 읽기 실패',str(exc))

    def paste_many(self):
        clipboard=QApplication.clipboard();mime=clipboard.mimeData()
        try:
            if mime.hasUrls():
                paths=[url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
                if not paths:raise ValueError('복사한 로컬 이미지 파일이 없습니다.')
                self.insert_photos([(load_photo(path),Path(path).name) for path in paths])
            elif mime.hasImage():
                buffer=QBuffer();buffer.open(QIODevice.WriteOnly);clipboard.image().save(buffer,'PNG')
                self.insert_photos([(load_photo(BytesIO(bytes(buffer.data()))),'붙여넣은 사진')])
            else:QMessageBox.information(self,'붙여넣기','이미지 또는 이미지 파일들을 먼저 복사하세요.')
        except Exception as exc:QMessageBox.warning(self,'붙여넣기 실패',str(exc))

    def move_photo(self,delta):
        row=self.photo_list.currentRow();other=row+delta;slots=self.photo_slots()
        if row<0 or other<0 or other>=len(slots):return
        key,i=slots[row];other_key,j=slots[other]
        for field in ['photos','photo_names']:
            a=self.lessons[key][field];b=self.lessons[other_key][field];a[i],b[j]=b[j],a[i]
        self.refresh_photos(other);self.changed()

    def clear_selected_photo(self):
        row=self.photo_list.currentRow()
        if row<0:return
        key,i=self.photo_slots()[row];self.lessons[key]['photos'][i]=None;self.lessons[key]['photo_names'][i]=''
        self.refresh_photos(row);self.changed()

    def state(self):
        d=self.date.date();h1,m1,h2,m2=[int(x.currentText()) for x in self.times]
        s={'place':self.place.text(),'course':self.course.currentText(),'education_id':self.education_id.text(),'submitter':self.submitter.text(),'date_text':f'{d.month()}월 {d.day()}일 {h1}시 {m1:02d}분 ~ {h2}시 {m2:02d}분'}
        for key,(cb,edit) in self.roles.items():s[key]=edit.text();s[key+'_enabled']=cb.isChecked()
        return s

    def changed(self,*args):
        if self._restoring:return
        old=getattr(self,'_preferred_submitter',self.submitter_choice.currentData())
        if hasattr(self,'_preferred_submitter'):del self._preferred_submitter
        selected=[(key,cb,edit) for key,(cb,edit) in self.roles.items() if cb.isChecked()]
        self.submitter_choice.blockSignals(True);self.submitter_choice.clear()
        for key,cb,edit in selected:self.submitter_choice.addItem(cb.text()+'/'+(edit.text().strip() or '이름 입력'),key)
        index=self.submitter_choice.findData(old)
        if index>=0:self.submitter_choice.setCurrentIndex(index)
        self.submitter_choice.setEnabled(len(selected)>1);self.submitter_choice.blockSignals(False)
        key=self.submitter_choice.currentData()
        self.submitter.setText(self.roles[key][1].text().strip() if key else '')
        self.revision+=1;self.status.setText('미리보기 업데이트 중…');self.timer.start()

    def update_signature_thumbnail(self):
        if self.signature is None:self.signature_label.setText(self.signature_error or '저장된 서명 없음');return
        buf=BytesIO();self.signature.save(buf,format='PNG');pix=QPixmap();pix.loadFromData(buf.getvalue())
        self.signature_label.setPixmap(pix.scaled(250,56,Qt.KeepAspectRatio,Qt.SmoothTransformation))

    def upload_signature(self):
        path,_=QFileDialog.getOpenFileName(self,'서명 이미지 선택','','이미지 (*.png *.jpg *.jpeg *.bmp *.webp)')
        if not path:return
        try:
            signature=prepare_signature(path)
            self.profile_dir.mkdir(parents=True,exist_ok=True)
            buf=BytesIO();signature.save(buf,format='PNG');data=buf.getvalue()
            saved=QSaveFile(str(self.profile_dir/'signature.png'))
            if not saved.open(QIODevice.WriteOnly):raise OSError(saved.errorString())
            if saved.write(data)!=len(data) or not saved.commit():raise OSError(saved.errorString())
            self.signature=signature;self.signature_enabled.setEnabled(True);self.signature_enabled.setChecked(True);self.update_signature_thumbnail();self.changed()
        except Exception as exc:QMessageBox.warning(self,'서명 저장 실패',str(exc))

    def set_photo(self,i,photo):
        self.photos[i]=photo;self.active_photo=i
        self.lessons[self.active_lesson]['photo_names'][i]='사진 있음' if photo is not None else ''
        self.refresh_photos();self.changed()

    def upload(self,i):
        path,_=QFileDialog.getOpenFileName(self,'증빙사진 선택','','이미지 (*.jpg *.jpeg *.png *.bmp *.webp)')
        if path:
            try:self.set_photo(i,load_photo(path))
            except Exception as exc:QMessageBox.warning(self,'사진을 읽을 수 없습니다',str(exc))

    def paste(self,i):
        clipboard=QApplication.clipboard();mime=clipboard.mimeData()
        try:
            if mime.hasImage():
                image=clipboard.image();buffer=QBuffer();buffer.open(QIODevice.WriteOnly);image.save(buffer,'PNG');self.set_photo(i,load_photo(BytesIO(bytes(buffer.data()))))
            elif mime.hasUrls() and mime.urls()[0].isLocalFile():self.set_photo(i,load_photo(mime.urls()[0].toLocalFile()))
            else:QMessageBox.information(self,'붙여넣기','먼저 이미지 또는 이미지 파일 하나를 복사하세요.')
        except Exception as exc:QMessageBox.warning(self,'붙여넣기 실패',str(exc))

    def clear_photo(self,i):self.set_photo(i,None)

    def render(self):
        if self.process.state()!=QProcess.NotRunning:return
        try:
            self.current_bytes=make_document(BASE/'template.hwpx',self.state(),self.photos,self.signature if self.signature_enabled.isChecked() else None)
            self.render_revision=self.revision
            (self.work/'preview.hwpx').write_bytes(self.current_bytes)
            self.process.setProgram(str(BASE/'rhwp.exe'))
            self.process.setArguments(['export-svg',str(self.work/'preview.hwpx'),'-o',str(self.work/'svg'),'--json'])
            self.process.start()
        except Exception as exc:self.status.setText('미리보기 생성 실패: '+str(exc))

    def render_done(self,code,status):
        if self.render_revision!=self.revision:self.render();return
        if code!=0:
            self.status.setText('미리보기 실패: '+bytes(self.process.readAllStandardError()).decode('utf-8','replace')[-180:]);return
        for svg_path in (self.work/'svg').glob('preview_*.svg'):
            svg_path.write_bytes(resolve_svg_fonts(svg_path))
        self.ready_bytes=self.current_bytes
        self.show_page();self.status.setText(f'{self.active_lesson}교시 · 미리보기 최신 · 사진 '+str(sum(x is not None for x in self.photos))+'/3')

    def render_error(self,error):self.status.setText('미리보기 엔진을 실행할 수 없습니다: '+self.process.errorString())

    def show_page(self,*args):
        path=self.work/'svg'/f'preview_{self.page.currentIndex()+1:03d}.svg'
        if path.exists():
            if self.page.currentIndex()==0 and self.zoom_form.isChecked():self.svg.load(QByteArray(form_view(path)))
            else:self.svg.load(str(path))

    def save(self):
        s=self.state();missing=[]
        if not s['submitter']:missing.append('강사 또는 보조강사 선택 및 제출자 이름')
        for key,label in [('place','교육장소'),('education_id','교육실시ID')]:
            if not s[key].strip():missing.append(label)
        for key,label in [('teacher','강사 이름'),('assistant','보조강사 이름')]:
            if s[key+'_enabled'] and not s[key].strip():missing.append(label)
        for i,label in enumerate(['전 사진','중 사진','후 사진']):
            if self.photos[i] is None:missing.append(label)
        h1,m1,h2,m2=[int(x.currentText()) for x in self.times]
        if h1*60+m1>=h2*60+m2:missing.append('시작보다 늦은 종료 시간')
        if missing:QMessageBox.information(self,'입력 확인','다음 항목을 확인하세요.\n\n'+'\n'.join('• '+x for x in missing));return
        if self.render_revision!=self.revision or self.process.state()!=QProcess.NotRunning or self.ready_bytes!=self.current_bytes:
            QMessageBox.information(self,'미리보기 준비 중','미리보기 업데이트가 끝난 후 저장하세요.');return
        name=output_filename(s)
        path,_=QFileDialog.getSaveFileName(self,'HWPX 저장',str(Path.home()/'Documents'/name),'HWPX 문서 (*.hwpx)')
        if not path:return
        if not path.lower().endswith('.hwpx'):path+='.hwpx'
        try:
            from zipfile import ZipFile,ZIP_DEFLATED
            from PySide6.QtSvg import QSvgRenderer
            renderer=QSvgRenderer(str(self.work/'svg'/'preview_001.svg'));image=QImage(1122,793,QImage.Format_RGB32);image.fill(Qt.white);painter=QPainter(image);renderer.render(painter);painter.end()
            buf=QBuffer();buf.open(QIODevice.WriteOnly);image.save(buf,'PNG')
            data=BytesIO(self.ready_bytes)
            with ZipFile(data,'a',ZIP_DEFLATED) as archive:archive.writestr('Preview/PrvImage.png',bytes(buf.data()))
            # Atomic replace: a failed write leaves an existing destination intact.
            from PySide6.QtCore import QSaveFile
            out=QSaveFile(path)
            if not out.open(QIODevice.WriteOnly):raise OSError(out.errorString())
            payload=data.getvalue()
            if out.write(payload)!=len(payload) or not out.commit():raise OSError(out.errorString())
            self.status.setText('저장 완료 · '+path)
            QMessageBox.information(self,'저장 완료',path)
        except Exception as exc:QMessageBox.warning(self,'저장 실패',str(exc))

    def closeEvent(self,event):
        if self.process.state()!=QProcess.NotRunning:self.process.kill();self.process.waitForFinished(3000)
        self.temp.cleanup();event.accept()

if __name__=='__main__':
    app=QApplication(sys.argv);app.setStyle('Fusion');app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    window=Window();window.show()
    if '--smoke-test' in sys.argv:
        target=Path(sys.argv[sys.argv.index('--smoke-test')+1]);target.mkdir(parents=True,exist_ok=True)
        def check_packaged():
            if window.ready_bytes and window.render_revision==window.revision:
                (target/'render-ok.hwpx').write_bytes(window.ready_bytes)
                window.grab().save(str(target/'packaged-app.png'))
                window.close();app.quit()
        timer=QTimer();timer.timeout.connect(check_packaged);timer.start(100)
        QTimer.singleShot(20000,lambda:app.exit(2))
    sys.exit(app.exec())
