#Разработал sf-brat https://github.com/sf-brat
#С помощью нейросети ChatGPT

import sys,json,copy,math
from pathlib import Path
import numpy as np, soundfile as sf
from PySide6.QtCore import Qt,QUrl,Signal
from PySide6.QtGui import QPainter,QPen,QColor,QFont, QShortcut, QKeySequence
from PySide6.QtWidgets import *
from PySide6.QtMultimedia import QMediaPlayer,QAudioOutput
TPS=48

def rd(p):
 d=json.loads(Path(p).read_bytes().rstrip(b"\0").decode("utf-8-sig"))
 if not isinstance(d,dict) or not isinstance(d.get("Clips"),list): raise ValueError("Не найдена коллекция Clips")
 return d


def get_musictrack_tempo(path):
 """Определяет BPM и целевой TPS по временным меткам musictrack.tpl."""
 raw = Path(path).read_bytes().rstrip(b"\0")
 data = json.loads(raw.decode("utf-8-sig"))

 def find_markers(obj):
  if isinstance(obj, dict):
   for key, value in obj.items():
    if key.lower() == "markers" and isinstance(value, list):
     return value
   for value in obj.values():
    result = find_markers(value)
    if result is not None:
     return result
  elif isinstance(obj, list):
   for value in obj:
    result = find_markers(value)
    if result is not None:
     return result
  return None

 markers = find_markers(data)
 if not markers or len(markers) < 2:
  raise ValueError("В musictrack.tpl не найдено достаточно маркеров")

 times = []
 for marker in markers:
  value = marker if isinstance(marker, (int, float)) else None
  if isinstance(marker, dict):
   for key in ("time", "Time", "position", "Position", "startTime", "StartTime", "value", "Value"):
    if key in marker:
     try:
      value = float(marker[key])
     except (TypeError, ValueError):
      value = None
     break
  if value is not None:
   try:
    times.append(float(value))
   except (TypeError, ValueError):
    pass

 times = sorted(set(times))
 intervals = [times[i + 1] - times[i] for i in range(len(times) - 1) if times[i + 1] > times[i]]
 if not intervals:
  raise ValueError("Не удалось определить интервалы музыкальных маркеров")
 average_interval = sum(intervals) / len(intervals)
 bpm = 60 * 48000 / average_interval
 return bpm, bpm * 0.4
def ticks(s): return max(0,round(float(s)*TPS))
def secs(t): return float(t)/TPS
def splittext(t,n):
 w=t.strip().split()
 if len(w)>=n:
  a=[[] for _ in range(n)]
  for i,x in enumerate(w): a[min(n-1,i*n//len(w))].append(x)
  return [" ".join(x) for x in a if x]
 return [t.strip()[round(i*len(t.strip())/n):round((i+1)*len(t.strip())/n)].strip() for i in range(n) if t.strip()[round(i*len(t.strip())/n):round((i+1)*len(t.strip())/n)].strip()]


class Wave(QWidget):
 seek=Signal(float); selected=Signal(float,float)
 clipChanged = Signal(int, float, float)
 groupClipsMoved = Signal(object, float)
 playhead = 0.0

 drag_clip = None
 drag_edge = None
 drag_original = None
 clips = []
 
 def __init__(self):
  super().__init__(); self.setMinimumHeight(170); self.peaks=None; self.duration=0; self.zoom=1.; self.offset=0.; self.sel=None; self.drag=None
  self.playhead = 0.0
  self.drag_playhead = False
  self.drag_clip = None
  self.drag_edge = None
  self.drag_original = None
  self.clips = []
  # Групповое выделение и перемещение клипов
  self.selected_clips = set()
  self.drag_group = False
  self.group_drag_anchor = 0.0
  self.group_drag_original = {}
  self.group_preview_delta = 0.0
  
 
 def set_clips(self, clips):
    self.clips = clips
    self.update()
 def set_playhead(self, seconds):
    self.playhead = seconds
    self.update()

 def paintEvent(self,e):
    p = QPainter(self)

    p.fillRect(self.rect(), QColor("#151922"))
    p.setRenderHint(QPainter.Antialiasing)

    w = self.width()
    h = self.height()
    mid = h * 0.52

    #def time_x(t):
    #    return int((t - self.offset) / self.vis() * w)
    
    def time_x(t):
         #p.end()
        try:
         xx_time = int((t - self.offset) / self.vis() * w)
        except ZeroDivisionError:
         print("0")
         return 0  # значение по умолчанию при ошибке
        else:
            return xx_time
       

    # Сетка
    p.setPen(QPen(QColor("#303846"), 1))

    for y in (h * 0.2, mid, h * 0.8):
        p.drawLine(0, int(y), w, int(y))

    # Волна
    if self.peaks is not None:
        p.setPen(QPen(QColor("#70c6a4"), 1))

        for x in range(w):
            t = self.xt(x)
            i = int(t / max(0.001, self.duration) * len(self.peaks))

            if 0 <= i < len(self.peaks):
                lo, hi = self.peaks[i]

                p.drawLine(
                    x,
                    int(mid - hi * h * 0.42),
                    x,
                    int(mid - lo * h * 0.42)
                )

    # Рамки всех клипов
        # Рамки всех клипов
    for i, clip in enumerate(self.clips):

        start = secs(clip["StartTime"])
        duration = secs(clip["Duration"])

        # Во время группового перемещения показываем предварительный сдвиг
        if self.drag_group and i in self.selected_clips:
            start += self.group_preview_delta

        end = start + duration

        x1 = time_x(start)
        x2 = time_x(end)

        if x2 < 0 or x1 > w:
            continue

        # Выделенные клипы окрашиваем в красный
        if i in self.selected_clips:
            p.setPen(QPen(QColor("#ff6666"), 2))
            p.setBrush(QColor(255, 70, 70, 100))
        else:
            p.setPen(QPen(QColor("#7c9ac7"), 1))
            p.setBrush(QColor(70, 110, 170, 55))

        p.drawRect(
            x1,
            8,
            max(2, x2 - x1),
            h - 16
        )

        p.setPen(QColor("#dce7f5"))
        p.drawText(x1 + 3, 22, str(i + 1))

    # Выделение
    if self.sel:
        a, b = self.sel

        p.setPen(QPen(QColor("#ffd166"), 2))
        p.setBrush(QColor(255, 209, 102, 45))

        p.drawRect(
            time_x(a),
            3,
            max(1, time_x(b) - time_x(a)),
            h - 6
        )

    # Курсор воспроизведения
    cursor_x = time_x(self.playhead)

    p.setPen(QPen(QColor("#ff5555"), 2))
    p.drawLine(cursor_x, 0, cursor_x, h)

    p.setBrush(QColor("#ff5555"))
    p.drawEllipse(cursor_x - 4, 2, 8, 8)

    # Подписи времени
    p.setPen(QColor("#aab4c3"))
    p.drawText(8, h - 7, f"{self.offset:.1f} сек.")
    p.drawText(
        w - 90,
        h - 7,
        f"{self.offset + self.vis():.1f} сек."
    )
    

    p.end()
    
    
    
    
    
    
 #clipChanged = Signal(float)
 def mousePressEvent(self, e):

    x = e.position().x()

    if e.button() == Qt.LeftButton:

        # CTRL + ЛКМ — добавить клип в выделение
        # или убрать его из выделения
        if e.modifiers() & Qt.ControlModifier:

            for i in range(len(self.clips) - 1, -1, -1):

                clip = self.clips[i]

                start = secs(clip["StartTime"])
                end = start + secs(clip["Duration"])

                x1 = (start - self.offset) / self.vis() * self.width()
                x2 = (end - self.offset) / self.vis() * self.width()

                if x1 <= x <= x2:

                    if i in self.selected_clips:
                        self.selected_clips.remove(i)
                    else:
                        self.selected_clips.add(i)

                    self.update()
                    return

            return

        # Сначала проверяем края блоков:
        # обычное изменение начала или конца остаётся доступным
        for i, clip in enumerate(self.clips):

            start = secs(clip["StartTime"])
            end = start + secs(clip["Duration"])

            x1 = (start - self.offset) / self.vis() * self.width()
            x2 = (end - self.offset) / self.vis() * self.width()

            if abs(x - x1) < 7:
                self.drag_clip = i
                self.drag_edge = "left"
                self.drag_original = (start, end)
                self.preview_drag = (start, end)
                return

            if abs(x - x2) < 7:
                self.drag_clip = i
                self.drag_edge = "right"
                self.drag_original = (start, end)
                self.preview_drag = (start, end)
                return

        # Если нажали на один из выделенных блоков —
        # начинаем перемещение всей группы
        for i in range(len(self.clips) - 1, -1, -1):

            clip = self.clips[i]

            start = secs(clip["StartTime"])
            end = start + secs(clip["Duration"])

            x1 = (start - self.offset) / self.vis() * self.width()
            x2 = (end - self.offset) / self.vis() * self.width()

            if i in self.selected_clips and x1 <= x <= x2:

                self.drag_group = True
                self.group_drag_anchor = self.xt(x)

                self.group_drag_original = {
                    index: secs(self.clips[index]["StartTime"])
                    for index in self.selected_clips
                }

                self.group_preview_delta = 0.0

                self.update()
                return

        # Если не попали на блок — перемещаем курсор
        self.drag_playhead = True
        self.seek.emit(self.xt(x))

    elif e.button() == Qt.RightButton:

        self.drag = self.xt(x)
        self.sel = (self.drag, self.drag)
        self.update()

  #event



 

 
 
 
 def load(self,p):
  a,sr=sf.read(p,dtype="float32",always_2d=True); a=a.mean(axis=1); self.duration=len(a)/sr
  step=max(1,math.ceil(len(a)/max(2000,self.width()*8))); self.peaks=np.array([(x.min(),x.max()) for x in (a[i:i+step] for i in range(0,len(a),step))])
  self.zoom=1.;self.offset=0.;self.sel=None;self.update()
 def vis(self): return self.duration/max(1,self.zoom)
 def clamp(self): self.offset=min(max(0,self.offset),max(0,self.duration-self.vis()))
 def xt(self,x): return self.offset+x/max(1,self.width())*self.vis()
 def zoomby(self,f,x=None):
  x=self.width()/2 if x is None else x; anchor=self.xt(x); self.zoom=min(40,max(1,self.zoom*f)); self.offset=anchor-x/max(1,self.width())*self.vis();self.clamp();self.update()
 def wheelEvent(self,e):
  if e.modifiers()&Qt.ControlModifier:self.zoomby(1.25 if e.angleDelta().y()>0 else .8,e.position().x())
  else:self.offset-=self.vis()*(.12 if e.angleDelta().y()>0 else -.12);self.clamp();self.update()
 
 def mouseReleaseEvent(self, e):

    if e.button() == Qt.LeftButton:

        # Завершение группового перемещения
        if self.drag_group:

            delta = self.group_preview_delta

            indices = list(self.selected_clips)

            self.drag_group = False
            self.group_preview_delta = 0.0
            self.group_drag_original = {}

            if abs(delta) > 0.001:
                self.groupClipsMoved.emit(indices, delta)

            self.update()
            return

        # Завершение изменения одного клипа
        if self.drag_clip is not None:

            start, end = self.preview_drag

            self.clipChanged.emit(
                self.drag_clip,
                start,
                end - start
            )

            self.drag_clip = None
            self.drag_edge = None
            self.drag_original = None

            self.update()
            return

        self.drag_playhead = False

    if e.button() == Qt.RightButton and self.drag is not None:

        a, b = sorted(
            (self.drag, self.xt(e.position().x()))
        )

        self.drag = None

        if b - a > 0.03:
            self.sel = (a, b)
            self.selected.emit(a, b)

    self.update()
 
 
  
  
  
  
 def mouseMoveEvent(self, event):

    x = event.position().x()

    # Перемещение группы клипов
    if self.drag_group:

        current_time = self.xt(x)

        delta = current_time - self.group_drag_anchor

        # Не разрешаем увести блоки раньше нулевой секунды
        if self.group_drag_original:
            min_start = min(self.group_drag_original.values())
            delta = max(delta, -min_start)

        self.group_preview_delta = delta

        self.update()
        return

    # Обычное изменение границ одного клипа
    if self.drag_clip is not None:

        current_time = self.xt(x)

        start, end = self.drag_original

        if self.drag_edge == "left":
            start = min(current_time, end - 0.05)
        else:
            end = max(current_time, start + 0.05)

        self.preview_drag = (start, end)

        self.update()
        return

    # Выделение интервала правой кнопкой
    if self.drag is not None:

        self.sel = tuple(sorted((self.drag, self.xt(x))))
        self.update()
  

   
 

class KaraokePreview(QWidget):

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(220)
        self.parts = []
        self.next_text = ""
        self.current_text = ""
        self.progress = 0.0
        self.next_progress = 0.0

    def set_lines(self, current, next_line, progress):

        self.current_text = current
        self.next_text = next_line
        self.progress = max(0.0, min(1.0, progress))
        self.update()

    def set_parts(self, parts, next_text=""):
        self.parts = parts
        self.next_text = next_text
        self.update()
    def paintEvent(self, e):
        p = QPainter(self)

        p.fillRect(self.rect(), QColor("#10141c"))
        p.setRenderHint(QPainter.Antialiasing)

        font = QFont("Arial", 18, QFont.Bold)
        p.setFont(font)

        metrics = p.fontMetrics()

        # Собираем ширину всей строки.
        total_width = sum(
            metrics.horizontalAdvance(text)
            for text, progress in self.parts
        )

        x = (self.width() - total_width) / 2
        y = 80

        # Рисуем каждый фрагмент отдельно.
        for text, progress in self.parts:

            part_width = metrics.horizontalAdvance(text)

            # Сначала весь фрагмент серым.
            p.setPen(QColor("#687386"))
            p.drawText(
                int(x),
                y,
                text
            )

            # Затем его заполненную часть белым.
            fill_width = int(
                part_width * max(0, min(1, progress))
            )

            p.save()

            p.setClipRect(
                int(x),
                y - metrics.ascent(),
                fill_width,
                metrics.height() + 5
            )

            p.setPen(QColor("#ffffff"))
            p.drawText(
                int(x),
                y,
                text
            )

            p.restore()

            x += part_width

        # Следующая строка.
        p.setFont(QFont("Arial", 16))
        p.setPen(QColor("#9ca8ba"))

        p.drawText(
            20,
            155,
            self.width() - 40,
            40,
            Qt.AlignCenter,
            self.next_text
        )

    






class App(QMainWindow):
 def update_clock(self, milliseconds):
    self.clock.setText(
        f"{milliseconds / 60000:02.0f}:"
        f"{milliseconds / 1000 % 60:04.1f}"
    )
    
 def __init__(self):
  super().__init__();self.setWindowTitle("Just Dance Line Karaoke Maker, by sf-brat");self.resize(1300,880);self.data=None;self.ktpath="";self.audio="";self.player=QMediaPlayer(self);self.out=QAudioOutput(self);self.player.setAudioOutput(self.out)
  self.musictrack_path = ""
  self.detected_bpm = None
  self.detected_tps = None
  
  
  self.player.positionChanged.connect(
     self.update_clock
  )  
  
  
  
  root=QWidget();self.setCentralWidget(root);L=QVBoxLayout(root)
  top=QHBoxLayout()
  
  #self.playhead = 0.0

  #self.drag_clip = None
  #self.drag_edge = None
  #self.drag_original = None
  #self.clips = []
  #self.clipChanged = Signal(float)
  
  for label,fn in [("Открыть .ktape…",self.openkt),("Сохранить",self.save),("Сохранить как…",self.saveas),("Загрузить аудио…",self.loadaudio)]:
   b=QPushButton(label);b.clicked.connect(fn);top.addWidget(b)
  self.info=QLabel("Открой .ktape и аудио");top.addWidget(self.info,1);L.addLayout(top)
  box=QGroupBox("Аудиодорожка: ЛКМ — перейти и слушать; ПКМ с протяжкой — выделить интервал; Ctrl+колесо — масштаб; колесо — прокрутка")
  
  bl=QVBoxLayout(box)
  self.wave=Wave()
  self.wave.clipChanged.connect(self.change_clip_time)
  self.wave.groupClipsMoved.connect(self.move_selected_clips)
  self.wave.seek.connect(self.seek)
  self.wave.selected.connect(self.assign)
  
  row=QHBoxLayout()
  
  bl.addWidget(self.wave)
  for label,fn in [("−",lambda:self.wave.zoomby(.8)),("+",lambda:self.wave.zoomby(1.25)),("Вся песня",self.zoomall),("Воспроизвести",lambda:self.player.play()),("Стоп",lambda:self.player.stop())]:
   b=QPushButton(label);b.clicked.connect(fn);row.addWidget(b)
  
  self.tps_btn = QPushButton(f"Шкала редактора: {TPS:g}")
  self.tps_btn.clicked.connect(self.edit_tps)
  row.addWidget(self.tps_btn)
  self.musictrack_btn = QPushButton("Выбрать musictrack…")
  self.musictrack_btn.clicked.connect(self.choose_musictrack)
  row.addWidget(self.musictrack_btn)
  self.bpm_label = QLabel("BPM: не определён | TPS сохранения: 48")
  row.addWidget(self.bpm_label)
  
  self.clock=QLabel("00:00.0");row.addWidget(self.clock);self.assignbtn=QPushButton("Назначить выделение строке");self.assignbtn.clicked.connect(self.assigncurrent);row.addWidget(self.assignbtn);bl.addLayout(row);L.addWidget(box)
  sp=QSplitter(Qt.Horizontal);left=QWidget();ll=QVBoxLayout(left);ll.addWidget(QLabel("Строки караоке"))
  self.table=QTableWidget(0,5);self.table.setHorizontalHeaderLabels(["№","Текст","StartTime, сек.","Duration, сек.", "Конец строки"]);self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch);self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.itemSelectionChanged.connect(self.preview);self.table.itemChanged.connect(lambda _:self.refresh());ll.addWidget(self.table)
  er=QHBoxLayout();self.parts=QComboBox();self.parts.addItems(["2 части","3 части"]);er.addWidget(self.parts)
  self.fill_parts = QComboBox()
  self.fill_parts.addItems(["2 блока заливки", "3 блока заливки"])
  er.addWidget(self.fill_parts)
  self.fill_split_btn = QPushButton("Разделить заливку")
  self.fill_split_btn.clicked.connect(self.split_fill)
  er.addWidget(self.fill_split_btn)
  
  
  for label,fn in [("Разделить строку",self.splitrow),("Удалить строку",self.delete)]:
   b=QPushButton(label);b.clicked.connect(fn);er.addWidget(b)
  ll.addLayout(er);sp.addWidget(left)
  
  
  
  right=QWidget()
  rl=QVBoxLayout(right)
  #rl.addWidget(QLabel("Предпросмотр двух строк")) #<------
  
  self.preview_widget = KaraokePreview()
  rl.addWidget(self.preview_widget)
  
  self.player.positionChanged.connect(self.update_karaoke_preview)
  
  self.pv=QFrame();self.pv.setMinimumHeight(110);self.pv.setStyleSheet("background:#10141c;border:1px solid #465166;border-radius:8px;");pl=QVBoxLayout(self.pv);pl.addStretch()
  self.cur=QLabel("Выбери строку");self.cur.setAlignment(Qt.AlignCenter);self.cur.setStyleSheet("color:white;font-size:22px;font-weight:bold;border:0")
  self.nxt=QLabel("");self.nxt.setAlignment(Qt.AlignCenter);self.nxt.setStyleSheet("color:#9ca8ba;font-size:17px;border:0")
  pl.addWidget(self.cur)
  pl.addWidget(self.nxt)
  pl.addStretch()
  rl.addWidget(self.pv)
  self.pvinfo=QLabel("Текущая и следующая строка")
  rl.addWidget(self.pvinfo)
  rl.addStretch()
  
  rl.addSpacing(20)

  rl.addWidget(QLabel("Автоматическое распределение текста"))

  self.auto_margin_start = QDoubleSpinBox()
  self.auto_margin_start.setRange(0, 60)
  self.auto_margin_start.setValue(0.5)
  self.auto_margin_start.setSuffix(" сек.")

  self.auto_margin_end = QDoubleSpinBox()
  self.auto_margin_end.setRange(0, 60)
  self.auto_margin_end.setValue(0.5)
  self.auto_margin_end.setSuffix(" сек.")

  rl.addWidget(QLabel("Отступ в начале"))
  rl.addWidget(self.auto_margin_start)

  rl.addWidget(QLabel("Отступ в конце"))
  rl.addWidget(self.auto_margin_end)

  self.auto_distribute_btn = QPushButton(
    "Распределить текст по песне"
  )

  self.auto_distribute_btn.clicked.connect(
    self.distribute_text
  )

  rl.addWidget(self.auto_distribute_btn)
  
  sp.addWidget(right)
  sp.setSizes([850,400])
  L.addWidget(sp,1)
  
  self.status=QLabel("Готово");L.addWidget(self.status)
  
  
  self.space_shortcut = QShortcut(
    QKeySequence(Qt.Key_Space),
    self
  )

  self.space_shortcut.setContext(
    Qt.WindowShortcut
  )

  self.space_shortcut.activated.connect(
    self.toggle_playback
  )

  
  
  
  
 
 def find_musictrack(self, ktape_path):
    folder = Path(ktape_path).parent
    candidates = [folder / "musictrack.tpl", folder / "musictrack.tpl.ckd", folder / "musictrack.ckd"]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    for candidate in folder.glob("*musictrack*"):
        if candidate.is_file():
            return str(candidate)
    return None

 def apply_musictrack(self, path, show_errors=True):
    try:
        bpm, target_tps = get_musictrack_tempo(path)
        self.musictrack_path = path
        self.detected_bpm = bpm
        self.detected_tps = target_tps
        self.bpm_label.setText(f"BPM: {bpm:.2f} | TPS сохранения: {target_tps:.2f}")
        self.status.setText(f"Musictrack: {Path(path).name}; определено BPM {bpm:.2f}, TPS {target_tps:.2f}")
        return True
    except Exception as e:
        if show_errors:
            QMessageBox.warning(self, "Ошибка musictrack", f"Не удалось определить BPM/TPS:\n{e}")
        return False

 def choose_musictrack(self):
    start_dir = str(Path(self.ktpath).parent) if self.ktpath else ""
    path, _ = QFileDialog.getOpenFileName(self, "Выбрать musictrack.tpl", start_dir,
        "Musictrack (*.tpl *.ckd *.json);;Все файлы (*.*)")
    if path:
        self.apply_musictrack(path)

 def normalize_clips_to_editor_tps(self, source_tps):
    """Переводит загруженные тики из TPS musictrack во внутреннюю шкалу редактора."""
    if not self.data or not source_tps or source_tps <= 0:
        return
    factor = TPS / source_tps
    for clip in self.data.get("Clips", []):
        clip["StartTime"] = max(0, round(float(clip.get("StartTime", 0)) * factor))
        clip["Duration"] = max(1, round(float(clip.get("Duration", 0)) * factor))

 def save_tps_dialog(self):
    dialog = QDialog(self)
    dialog.setWindowTitle("Параметры TPS при сохранении")
    layout = QVBoxLayout(dialog)
    form = QFormLayout()
    default_tps = self.detected_tps if self.detected_tps is not None else 48.0

    start_box = QDoubleSpinBox()
    start_box.setRange(1.0, 200.0)
    start_box.setDecimals(3)
    start_box.setSingleStep(0.1)
    start_box.setValue(default_tps)
    start_box.setSuffix(" TPS")

    duration_box = QDoubleSpinBox()
    duration_box.setRange(1.0, 200.0)
    duration_box.setDecimals(3)
    duration_box.setSingleStep(0.1)
    duration_box.setValue(default_tps)
    duration_box.setSuffix(" TPS")

    source_label = f"{TPS:g} TPS (шкала редактора)"
    form.addRow("Исходная шкала:", QLabel(source_label))
    form.addRow("TPS начала слов (StartTime):", start_box)
    form.addRow("TPS длительности слов (Duration):", duration_box)
    layout.addLayout(form)

    if self.detected_tps is None:
        note = QLabel("TPS из musictrack не определён. Укажи значения вручную.")
    else:
        note = QLabel(f"Автоматически определено по musictrack: {self.detected_tps:.3f} TPS. Значения можно изменить.")
    note.setWordWrap(True)
    layout.addWidget(note)

    buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    if dialog.exec() != QDialog.Accepted:
        return None
    return start_box.value(), duration_box.value()

 def edit_tps(self):

    global TPS

    value, ok = QInputDialog.getDouble(
        self,
        "Настройка временной шкалы",
        "Количество временных делений в секунду:",
        TPS,
        1.0,
        200.0,
        3
    )

    if not ok:
        return

    TPS = value

    self.tps_btn.setText(
        f"Шкала редактора: {TPS:g}"
    )

    # Перечитываем таблицу из исходных временных отметок.
    # Это важно: не пересчитываем старые секунды по новой шкале.
    if self.data is not None:
        self.loadtable()

    self.status.setText(
        f"Временная шкала изменена: {TPS:g} делений/сек."
    )
 
 def toggle_playback(self):

    if self.player.playbackState() == QMediaPlayer.PlayingState:
        self.player.pause()
    else:
        self.player.play()
        
 def distribute_text(self):

    if not self.audio:
        QMessageBox.warning(
            self,
            "Нет аудио",
            "Сначала загрузи аудиофайл."
        )
        return

    text, ok = QInputDialog.getMultiLineText(
        self,
        "Текст песни",
        "Вставь текст. Каждая строка — отдельная фраза:"
    )

    if not ok:
        return

    lines = [
        x.strip()
        for x in text.splitlines()
        if x.strip()
    ]

    if not lines:
        return

    start = self.auto_margin_start.value()
    end = self.wave.duration - self.auto_margin_end.value()

    if end <= start:
        return

    weights = [max(4, len(line)) for line in lines]

    total = sum(weights)
    span = end - start

    self.table.blockSignals(True)
    self.table.setRowCount(len(lines))

    cursor = start

    for i, line in enumerate(lines):

        duration = span * weights[i] / total

        values = [
            str(i + 1),
            line,
            f"{cursor:.3f}",
            f"{duration:.3f}",
            "1"
        ]

        for col, value in enumerate(values):

            item = QTableWidgetItem(value)

            if col == 0:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)

            self.table.setItem(i, col, item)

        cursor += duration

    self.table.blockSignals(False)

    self.refresh()

    self.status.setText(
        f"Распределено строк: {len(lines)}. "
        "Время приблизительное — скорректируй его по аудио."
    )
 
 
 
 
 
 
 def update_karaoke_preview(self, milliseconds):
    if self.data is None:
        return

    current_time = milliseconds / 1000

    # Курсор обновляется ВСЕГДА, даже если караоке уже закончилось.
    self.wave.set_playhead(current_time)

    clips = sorted(
        self.data["Clips"],
        key=lambda c: c["StartTime"]
    )

    # Собираем клипы в строки.
    lines = []
    current_group = []

    for clip in clips:
        current_group.append(clip)

        if clip.get("IsEndOfLine", 1) == 1:
            lines.append(current_group)
            current_group = []

    if current_group:
        lines.append(current_group)

    active_index = None

    for i, line in enumerate(lines):
        start = secs(line[0]["StartTime"])

        last = line[-1]
        end = secs(last["StartTime"]) + secs(last["Duration"])

        if start <= current_time <= end:
            active_index = i
            break

    if active_index is None:
        self.preview_widget.set_lines("", "", 0)
        return

    line = lines[active_index]

    current_text = "".join(
        clip.get("Lyrics", "")
        for clip in line
    )

    next_text = ""
    parts = []
    if active_index + 1 < len(lines):
        next_text = "".join(
            clip.get("Lyrics", "")
            for clip in lines[active_index + 1]
        )

    # Прогресс заливки.
    progress = 0.0

    for clip in line:

     text = clip.get("Lyrics", "")

     start = secs(clip["StartTime"])
     duration = secs(clip["Duration"])
     end = start + duration

     if current_time < start:
        progress = 0.0

     elif current_time >= end:
        progress = 1.0

     else:
        progress = (
            (current_time - start) /
            max(duration, 0.001)
        )

     parts.append((text, progress))

    next_text = ""

    if active_index + 1 < len(lines):
     next_text = "".join(
        clip.get("Lyrics", "")
        for clip in lines[active_index + 1]
     )

    self.preview_widget.set_parts(
     parts,
     next_text
    )
    
 def move_selected_clips(self, indices, delta):

    if not indices:
        return

    self.table.blockSignals(True)

    # Меняем только StartTime в таблице.
    # Duration остаётся прежним.
    for row in indices:

        if row >= self.table.rowCount():
            continue

        item = self.table.item(row, 2)

        if item is None:
            continue

        start = float(item.text().replace(",", "."))

        self.table.item(row, 2).setText(
            f"{max(0, start + delta):.3f}"
        )

    self.table.blockSignals(False)

    # Сбрасываем выделение перед возможной сортировкой
    self.wave.selected_clips.clear()

    # Обновляем данные и таблицу
    self.refresh()
    self.loadtable()

    self.status.setText(
        f"Групповое перемещение: {delta:+.3f} сек. "
        f"Перемещено блоков: {len(indices)}"
    )
    
 def change_clip_time(self, row, start, duration):
    if row >= self.table.rowCount():
        return
    self.table.blockSignals(True)

    self.table.item(row, 2).setText(f"{start:.3f}")
    self.table.item(row, 3).setText(f"{duration:.3f}")

    self.table.blockSignals(False)

    self.refresh()
    self.preview()
 
 
 def split_fill(self):
    row = self.selectedrow()
    if row < 0:
        return
    text = self.table.item(row, 1).text()
    start = float(self.table.item(row, 2).text())
    duration = float(self.table.item(row, 3).text())
    count = self.fill_parts.currentIndex() + 2
    # Делим текст на части по словам.
    words = text.split()

    if len(words) < count:
        QMessageBox.warning(
            self,
            "Недостаточно слов",
            "В строке недостаточно слов для такого разделения."
        )
        return
    parts = []
    for i in range(count):
        a = i * len(words) // count
        b = (i + 1) * len(words) // count
        
        part = " ".join(words[a:b])

        # Пробел между соседними блоками сохраняем
        if i < count - 1:
          part += " "

        parts.append(part)
        
        
    # Время сначала распределяем поровну.
    part_duration = duration / count
    self.table.blockSignals(True)
    self.table.removeRow(row)

    for i, part in enumerate(parts):
        self.table.insertRow(row + i)
        values = [
            str(row + i + 1),
            part,
            f"{start + i * part_duration:.3f}",
            f"{part_duration:.3f}",
            "0" if i < len(parts) - 1 else "1"
        ]
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            if col == 0:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row + i, col, item)
    self.table.blockSignals(False)
    self.refresh()
    self.table.selectRow(row)
    self.status.setText("Заливка разделена. Теперь можно отдельно менять время каждого блока.")


 def openkt(self):
  p,_=QFileDialog.getOpenFileName(self,"Открыть .ktape","","Karaoke tape (*.ktape *.txt *.json *.ckd);;Все файлы (*.*)")
  if not p:return
  try:
   self.data=rd(p)
   self.ktpath=p
   self.detected_bpm = None
   self.detected_tps = None
   self.musictrack_path = ""
   self.info.setText(Path(p).name)
   musictrack = self.find_musictrack(p)
   if musictrack:
    if self.apply_musictrack(musictrack, show_errors=False):
     # Внутри редактора все времена приводим к базовой шкале (обычно 48 TPS).
     self.normalize_clips_to_editor_tps(self.detected_tps)
   else:
    self.detected_bpm = None
    self.detected_tps = None
    self.musictrack_path = ""
    self.bpm_label.setText("BPM: не определён | TPS сохранения: 48")
   self.loadtable()
   if self.detected_tps is not None:
    self.status.setText(f"Открыто клипов: {len(self.data['Clips'])} | BPM: {self.detected_bpm:.2f} | TPS сохранения: {self.detected_tps:.2f}")
   else:
    self.status.setText(f"Открыто клипов: {len(self.data['Clips'])}. Выбери musictrack или укажи TPS при сохранении.")
  except Exception as e:QMessageBox.critical(self,"Ошибка",str(e))
  
  
 def loadtable(self):
    cs = sorted(
        self.data["Clips"],
        key=lambda c: c.get("StartTime", 0)
    )

    self.data["Clips"] = cs

    self.table.blockSignals(True)
    self.table.setRowCount(len(cs))

    for i, c in enumerate(cs):
        values = [
            str(i + 1),
            str(c.get("Lyrics", "")),
            f"{secs(c.get('StartTime', 0)):.3f}",
            f"{secs(c.get('Duration', 0)):.3f}",
            str(c.get("IsEndOfLine", 1))
        ]

        for j, value in enumerate(values):
            item = QTableWidgetItem(value)

            if j == 0:
                item.setFlags(
                    item.flags() & ~Qt.ItemIsEditable
                )

            self.table.setItem(i, j, item)

    self.table.blockSignals(False)

    self.refresh()
    self.preview()
  
  
  
 def loadaudio(self):
  p,_=QFileDialog.getOpenFileName(self,"Аудио","","Аудио (*.mp3 *.wav *.flac *.ogg *.m4a)")
  if not p:return
  try:self.wave.load(p);self.audio=p;self.player.setSource(QUrl.fromLocalFile(p));self.status.setText(f"Аудио: {self.wave.duration:.2f} сек.")
  except Exception as e:QMessageBox.critical(self,"Ошибка аудио",f"{e}\\nПопробуй WAV или FLAC, если MP3 не читается.")
 def selectedrow(self):
  r=self.table.selectionModel().selectedRows();return r[0].row() if r else -1
 def assign(self,a,b):
  self.status.setText(f"Выделено {a:.2f}–{b:.2f} сек.; назначаю выбранной строке.");self.assigncurrent()
 def assigncurrent(self):
  r=self.selectedrow()
  if r<0 or not self.wave.sel:self.status.setText("Сначала выбери строку, затем выдели интервал ПКМ.");return
  a,b=self.wave.sel;self.table.blockSignals(True);self.table.item(r,2).setText(f"{a:.3f}");self.table.item(r,3).setText(f"{max(.02,b-a):.3f}");self.table.blockSignals(False);self.refresh();self.preview()
 
 def splitrow(self):
  r=self.selectedrow()
  if r<0:return
  text=self.table.item(r,1).text();st=float(self.table.item(r,2).text());du=float(self.table.item(r,3).text());n=self.parts.currentIndex()+2;parts=splittext(text,n)
  if len(parts)<2:QMessageBox.warning(self,"Ошибка","Недостаточно текста для разделения.");return
  self.table.blockSignals(True);self.table.removeRow(r)
  for j,t in enumerate(parts):
   self.table.insertRow(r+j)
   for col,v in enumerate([str(r+j+1),t,f"{st+du*j/len(parts):.3f}",f"{du/len(parts):.3f}"]):
    it=QTableWidgetItem(v)
    if col==0:it.setFlags(it.flags()&~Qt.ItemIsEditable)
    self.table.setItem(r+j,col,it)
  self.table.blockSignals(False);self.refresh();self.table.selectRow(r);self.status.setText("Разделено. Теперь выдели точное время для каждой части.")
 
 def delete(self):
  r=self.selectedrow()
  if r>=0:self.table.removeRow(r);self.refresh()
  
 def refresh(self):
    if self.data is None:
        return

    old = sorted(
        self.data.get("Clips", []),
        key=lambda c: c.get("StartTime", 0)
    )

    template = (
        copy.deepcopy(old[0])
        if old else {
            "__class": "KaraokeClip",
            "Id": 0,
            "TrackId": 0,
            "IsActive": 1,
            "StartTime": 0,
            "Duration": 48,
            "Pitch": 8.661958,
            "Lyrics": "",
            "IsEndOfLine": 1,
            "ContentType": 1,
            "StartTimeTolerance": 0,
            "EndTimeTolerance": 0,
            "SemitoneTolerance": 0
        }
    )

    clips = []

    for i in range(self.table.rowCount()):
        try:
            t = self.table.item(i, 1).text()

            s = float(
                self.table.item(i, 2).text().replace(",", ".")
            )

            d = float(
                self.table.item(i, 3).text().replace(",", ".")
            )

            # Читаем признак окончания строки.
            end_item = self.table.item(i, 4)

            end_line = (
                int(end_item.text())
                if end_item else 1
            )

            c = (
                copy.deepcopy(old[i])
                if i < len(old)
                else copy.deepcopy(template)
            )

            c.update({
                "Id": i,
                "Lyrics": t,
                "StartTime": ticks(s),
                "Duration": max(1, ticks(d)),
                "IsEndOfLine": end_line
            })

            if i == self.table.rowCount() - 1:
                c["IsEndOfLine"] = 1

            clips.append(c)

        except (ValueError, AttributeError, TypeError) as e:
            print(f"Ошибка строки {i + 1}: {e}")

    self.data["Clips"] = sorted(
        clips,
        key=lambda c: c["StartTime"]
    )

    # Передаём все клипы волне для отрисовки.
    self.wave.set_clips(self.data["Clips"])
  
  
  
  
 def preview(self):
  r=self.selectedrow()
  if r<0:self.cur.setText("Выбери строку");self.nxt.setText("");return
  self.cur.setText(self.table.item(r,1).text());self.nxt.setText(self.table.item(r+1,1).text() if r+1<self.table.rowCount() else "")
  self.pvinfo.setText(f"Строка {r+1}: начало {self.table.item(r,2).text()} сек. | длительность {self.table.item(r,3).text()} сек.")
 
 def seek(self, s):
    self.player.setPosition(int(s * 1000))
    self.wave.set_playhead(s)
    self.update_karaoke_preview(int(s * 1000))
 
 def zoomall(self):self.wave.zoom=1.;self.wave.offset=0.;self.wave.update()
 
 def save(self):
  if not self.data:return
  if not self.ktpath:self.saveas();return
  values = self.save_tps_dialog()
  if values is None:return
  self.write(self.ktpath, *values)

 def saveas(self):
  if not self.data:return
  p,_=QFileDialog.getSaveFileName(self,"Сохранить как","Edited.ktape","Karaoke tape (*.ktape *.ckd)")
  if p:
   if not p.lower().endswith(".ktape"):p+=".ktape"
   values = self.save_tps_dialog()
   if values is None:return
   if self.write(p, *values):
    self.ktpath=p

 def write(self,p,start_tps,duration_tps):
  try:
   # Сначала обновляем внутренние данные в шкале редактора (обычно 48 TPS).
   self.refresh()
   output_data = copy.deepcopy(self.data)
   start_factor = start_tps / TPS
   duration_factor = duration_tps / TPS
   for clip in output_data.get("Clips", []):
    clip["StartTime"] = max(0, round(float(clip.get("StartTime", 0)) * start_factor))
    clip["Duration"] = max(1, round(float(clip.get("Duration", 0)) * duration_factor))
   Path(p).write_bytes(json.dumps(output_data,ensure_ascii=False,indent=2).encode("utf-8")+b"\x00")
   self.info.setText(Path(p).name)
   self.status.setText(f"Сохранено клипов: {len(output_data['Clips'])} | TPS начала: {start_tps:g} | TPS длительности: {duration_tps:g}")
   return True
  except Exception as e:
   QMessageBox.critical(self,"Ошибка сохранения",str(e))
   return False

if __name__=="__main__":
 app=QApplication(sys.argv);w=App();w.show();sys.exit(app.exec())
