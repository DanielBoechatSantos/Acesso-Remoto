import sys
import os
import json
import socket
import pickle
import struct
import threading
import numpy as np
import cv2
import mss
import resources_rc

from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QInputDialog, QMessageBox, 
                             QComboBox, QScrollArea, QFrame, QFileDialog)
from PyQt5.QtGui import QImage, QPixmap, QIcon
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer
from pynput.mouse import Controller as MouseController, Button
from pynput.keyboard import Controller as KeyboardController, Key

# --- CONFIGURAÇÕES DE REDE ---
PORT_VIDEO = 9999
PORT_INPUT = 9998
PORT_FILE = 9997
CONFIG_FILE = "remote_config.json"

BUTTON_MAP = {
    'left': Button.left,
    'right': Button.right,
    'middle': Button.middle
}

# --- FUNÇÕES UTILITÁRIAS ---
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def load_last_ip():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                return data.get("last_ip", "192.168.1.50")
        except Exception:
            pass
    return "192.168.1.50"

def save_last_ip(ip):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump({"last_ip": ip}, f)
    except Exception as e:
        print(f"Erro ao salvar configuração: {e}")


# --- THREAD DE RECEPÇÃO DE VÍDEO ---
class VideoThread(QThread):
    change_pixmap_signal = pyqtSignal(QImage, int, int, int)
    connection_lost_signal = pyqtSignal()

    def __init__(self, server_ip):
        super().__init__()
        self.server_ip = server_ip
        self.running = True

    def run(self):
        client_video = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_video.settimeout(5.0)
        try:
            client_video.connect((self.server_ip, PORT_VIDEO))
        except Exception as e:
            print(f"Erro ao conectar ao servidor de vídeo: {e}")
            self.connection_lost_signal.emit()
            return

        payload_size = struct.calcsize(">L")
        data = b""

        while self.running:
            try:
                while len(data) < payload_size:
                    packet = client_video.recv(4096)
                    if not packet:
                        raise ConnectionError("Conexão encerrada")
                    data += packet

                packed_msg_size = data[:payload_size]
                data = data[payload_size:]
                msg_size = struct.unpack(">L", packed_msg_size)[0]

                while len(data) < msg_size:
                    packet = client_video.recv(8192)
                    if not packet:
                        raise ConnectionError("Conexão encerrada no meio do quadro")
                    data += packet

                frame_data = data[:msg_size]
                data = data[msg_size:]

                bytes_received = len(frame_data) + payload_size
                encoded_frame = pickle.loads(frame_data)
                frame = cv2.imdecode(encoded_frame, cv2.IMREAD_COLOR)

                if frame is not None:
                    h, w, ch = frame.shape
                    bytes_per_line = ch * w
                    qt_img = QImage(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).data, w, h, bytes_per_line, QImage.Format_RGB888)
                    self.change_pixmap_signal.emit(qt_img.copy(), w, h, bytes_received)
            except Exception as e:
                print(f"Erro/Timeout na recepção de vídeo: {e}")
                self.connection_lost_signal.emit()
                break

        client_video.close()


# --- PAINEL FLUTUANTE TRANSLÚCIDO (OVERLAY) ---
class FloatingOverlayBar(QFrame):
    def __init__(self, parent_viewer):
        super().__init__(parent_viewer)
        self.viewer = parent_viewer
        self.is_expanded = False
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("""
            QFrame#MainFrame {
                background-color: rgba(25, 25, 25, 210);
                border-radius: 10px;
                border: 1px solid rgba(255, 255, 255, 40);
            }
            QLabel, QPushButton, QComboBox {
                color: white;
                font-family: Segoe UI, sans-serif;
                font-size: 12px;
            }
            QPushButton {
                background-color: rgba(255, 255, 255, 25);
                border: 1px solid rgba(255, 255, 255, 40);
                border-radius: 4px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 50);
            }
            QComboBox {
                background-color: rgba(0, 0, 0, 150);
                border: 1px solid rgba(255, 255, 255, 40);
                border-radius: 4px;
                padding: 2px 6px;
            }
        """)
        self.setObjectName("MainFrame")

        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(8, 5, 8, 5)
        self.main_layout.setSpacing(8)

        self.btn_toggle = QPushButton("◀ Controles", self)
        self.btn_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_toggle.clicked.connect(self.toggle_expand)
        self.main_layout.addWidget(self.btn_toggle)

        self.controls_widget = QWidget(self)
        self.controls_layout = QHBoxLayout(self.controls_widget)
        self.controls_layout.setContentsMargins(0, 0, 0, 0)
        self.controls_layout.setSpacing(6)

        self.monitor_combo = QComboBox(self)
        self.monitor_combo.addItems(["Display 1", "Display 2", "Display 3"])
        self.monitor_combo.currentIndexChanged.connect(self.viewer.change_monitor)
        self.controls_layout.addWidget(QLabel("Display:"))
        self.controls_layout.addWidget(self.monitor_combo)

        self.btn_fit = QPushButton("Ajustar", self)
        self.btn_fit.clicked.connect(self.viewer.set_fit_mode)
        self.controls_layout.addWidget(self.btn_fit)

        self.btn_real = QPushButton("Tamanho Real (1:1)", self)
        self.btn_real.clicked.connect(self.viewer.set_real_size_mode)
        self.controls_layout.addWidget(self.btn_real)

        self.btn_zoom_in = QPushButton("🔍 +", self)
        self.btn_zoom_in.clicked.connect(lambda: self.viewer.adjust_zoom(1.2))
        self.controls_layout.addWidget(self.btn_zoom_in)

        self.btn_zoom_out = QPushButton("🔍 -", self)
        self.btn_zoom_out.clicked.connect(lambda: self.viewer.adjust_zoom(0.8))
        self.controls_layout.addWidget(self.btn_zoom_out)

        self.btn_autopan = QPushButton("Auto-Pan: ON", self)
        self.btn_autopan.setCheckable(True)
        self.btn_autopan.setChecked(True)
        self.btn_autopan.toggled.connect(self.viewer.toggle_autopan)
        self.controls_layout.addWidget(self.btn_autopan)

        self.btn_file = QPushButton("📁 Arquivo", self)
        self.btn_file.clicked.connect(self.viewer.send_file)
        self.controls_layout.addWidget(self.btn_file)

        self.btn_swap = QPushButton("🔄 Inverter Papéis", self)
        self.btn_swap.clicked.connect(self.viewer.swap_roles)
        self.controls_layout.addWidget(self.btn_swap)

        self.main_layout.addWidget(self.controls_widget)
        self.controls_widget.setVisible(False)

    def toggle_expand(self):
        self.is_expanded = not self.is_expanded
        self.controls_widget.setVisible(self.is_expanded)
        self.btn_toggle.setText("▶ Fechar" if self.is_expanded else "◀ Controles")
        self.adjustSize()
        self.viewer.reposition_overlay()


# --- JANELA DE VISUALIZAÇÃO E CONTROLE ---
class ViewerWindow(QWidget):
    def __init__(self, server_ip):
        super().__init__()
        self.server_ip = server_ip
        self.zoom_factor = 1.0
        self.is_real_size = False
        self.auto_pan_enabled = True
        self.remote_w = 1920
        self.remote_h = 1080
        self.current_pixmap = None
        self.fps_counter = 0
        self.data_counter = 0

        self.setWindowTitle("Sessão Remota")
        self.setWindowIcon(QIcon(":/img/ico.png"))
        self.resize(1280, 720)

        # Foco forte para garantir captura de teclas em evidência
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setAlignment(Qt.AlignCenter)
        self.scroll_area.setStyleSheet("background-color: #121212; border: none;")

        self.screen_label = QLabel()
        self.screen_label.setAlignment(Qt.AlignCenter)
        self.screen_label.setMouseTracking(True)
        self.scroll_area.setWidget(self.screen_label)

        self.main_layout.addWidget(self.scroll_area)

        # Filtro/Monitoramento de eventos na Label de Exibição
        self.screen_label.mousePressEvent = self.remote_mouse_press
        self.screen_label.mouseReleaseEvent = self.remote_mouse_release
        self.screen_label.mouseMoveEvent = self.remote_mouse_move

        self.overlay = FloatingOverlayBar(self)
        self.overlay.show()

        self.client_input = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.client_input.connect((self.server_ip, PORT_INPUT))
        except Exception as e:
            print(f"Erro canal de comando: {e}")

        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self.update_title)
        self.stats_timer.start(1000)

        self.thread = VideoThread(self.server_ip)
        self.thread.change_pixmap_signal.connect(self.update_image)
        self.thread.connection_lost_signal.connect(self.on_connection_lost)
        self.thread.start()

    def reposition_overlay(self):
        margin = 15
        x = self.width() - self.overlay.width() - margin
        y = margin
        self.overlay.move(max(margin, x), y)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reposition_overlay()
        self.render_screen()

    def update_image(self, qt_img, actual_w, actual_h, bytes_received):
        self.remote_w = actual_w
        self.remote_h = actual_h
        self.fps_counter += 1
        self.data_counter += bytes_received
        self.current_pixmap = QPixmap.fromImage(qt_img)
        self.render_screen()

    def render_screen(self):
        if not self.current_pixmap or self.current_pixmap.isNull():
            return

        viewport_size = self.scroll_area.viewport().size()

        if not self.is_real_size and self.zoom_factor == 1.0:
            scaled_pixmap = self.current_pixmap.scaled(
                viewport_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        else:
            target_w = int(self.remote_w * self.zoom_factor) if self.is_real_size else int(viewport_size.width() * self.zoom_factor)
            target_h = int(self.remote_h * self.zoom_factor) if self.is_real_size else int(viewport_size.height() * self.zoom_factor)
            scaled_pixmap = self.current_pixmap.scaled(
                target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )

        self.screen_label.setPixmap(scaled_pixmap)
        self.screen_label.resize(scaled_pixmap.size())

    def set_fit_mode(self):
        self.is_real_size = False
        self.zoom_factor = 1.0
        self.render_screen()

    def set_real_size_mode(self):
        self.is_real_size = True
        self.zoom_factor = 1.0
        self.render_screen()

    def adjust_zoom(self, factor):
        self.zoom_factor = max(0.2, min(5.0, self.zoom_factor * factor))
        self.render_screen()

    def toggle_autopan(self, checked):
        self.auto_pan_enabled = checked

    def change_monitor(self, index):
        self.send_cmd({'type': 'select_monitor', 'index': index + 1})

    def update_title(self):
        mbps = (self.data_counter * 8) / (1024 * 1024)
        self.setWindowTitle(f"Conectado: {self.server_ip} | FPS: {self.fps_counter} | {mbps:.2f} Mbps")
        self.fps_counter = 0
        self.data_counter = 0

    def get_remote_coords(self, pos):
        """Calcula com precisão cirúrgica a posição no Host independente de Zoom/Fit/Scroll."""
        lbl_w = self.screen_label.width()
        lbl_h = self.screen_label.height()

        if lbl_w <= 0 or lbl_h <= 0:
            return 0, 0

        rx = int((max(0, min(pos.x(), lbl_w)) / lbl_w) * self.remote_w)
        ry = int((max(0, min(pos.y(), lbl_h)) / lbl_h) * self.remote_h)
        return rx, ry

    def remote_mouse_move(self, event):
        rx, ry = self.get_remote_coords(event.pos())
        self.send_cmd({'type': 'move', 'x': rx, 'y': ry})

        if self.auto_pan_enabled and (self.is_real_size or self.zoom_factor > 1.0):
            margin = 30
            cursor = self.mapFromGlobal(event.globalPos())
            h_bar = self.scroll_area.horizontalScrollBar()
            v_bar = self.scroll_area.verticalScrollBar()

            if cursor.x() < margin:
                h_bar.setValue(h_bar.value() - 15)
            elif cursor.x() > self.width() - margin:
                h_bar.setValue(h_bar.value() + 15)

            if cursor.y() < margin:
                v_bar.setValue(v_bar.value() - 15)
            elif cursor.y() > self.height() - margin:
                v_bar.setValue(v_bar.value() + 15)

    def remote_mouse_press(self, event):
        self.setFocus() # Garante foco no teclado ao clicar na tela
        btn = 'left'
        if event.button() == Qt.RightButton: btn = 'right'
        elif event.button() == Qt.MidButton: btn = 'middle'
        
        rx, ry = self.get_remote_coords(event.pos())
        self.send_cmd({'type': 'move', 'x': rx, 'y': ry})
        self.send_cmd({'type': 'click_press', 'button': btn})

    def remote_mouse_release(self, event):
        btn = 'left'
        if event.button() == Qt.RightButton: btn = 'right'
        elif event.button() == Qt.MidButton: btn = 'middle'
        
        rx, ry = self.get_remote_coords(event.pos())
        self.send_cmd({'type': 'move', 'x': rx, 'y': ry})
        self.send_cmd({'type': 'click_release', 'button': btn})

    def keyPressEvent(self, event):
        self.send_key(event, 'key_press')

    def keyReleaseEvent(self, event):
        self.send_key(event, 'key_release')

    def send_key(self, event, event_type):
        key_name = None
        key_code = event.key()

        special_keys = {
            Qt.Key_Control: 'ctrl', Qt.Key_Shift: 'shift', Qt.Key_Alt: 'alt',
            Qt.Key_Return: 'enter', Qt.Key_Enter: 'enter', Qt.Key_Backspace: 'backspace',
            Qt.Key_Tab: 'tab', Qt.Key_Escape: 'esc', Qt.Key_Delete: 'delete',
            Qt.Key_Left: 'left', Qt.Key_Right: 'right', Qt.Key_Up: 'up', Qt.Key_Down: 'down'
        }

        if key_code in special_keys:
            key_name = special_keys[key_code]
        else:
            key_name = event.text()

        if key_name:
            self.send_cmd({'type': event_type, 'key': key_name})

    def send_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Selecionar Arquivo para Transferir")
        if file_path:
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            
            def file_worker():
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.connect((self.server_ip, PORT_FILE))
                    header = json.dumps({"name": file_name, "size": file_size}).encode()
                    s.sendall(struct.pack(">L", len(header)) + header)
                    
                    with open(file_path, "rb") as f:
                        while chunk := f.read(65536):
                            s.sendall(chunk)
                    s.close()
                    print("Arquivo enviado com sucesso!")
                except Exception as e:
                    print(f"Erro ao enviar arquivo: {e}")

            threading.Thread(target=file_worker, daemon=True).start()

    def swap_roles(self):
        reply = QMessageBox.question(self, "Inverter Papéis", 
                                     "Deseja alternar os papéis? Você passará a ser controlado.",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.send_cmd({'type': 'swap_roles'})
            self.close()

    def send_cmd(self, cmd):
        try:
            data = pickle.dumps(cmd)
            self.client_input.sendall(struct.pack(">L", len(data)) + data)
        except Exception:
            pass

    def on_connection_lost(self):
        QMessageBox.warning(self, "Conexão Perdida", "A transmissão de vídeo com o host foi interrompida.")
        self.close()

    def closeEvent(self, event):
        self.thread.running = False
        self.stats_timer.stop()
        try:
            self.client_input.close()
        except Exception:
            pass
        super().closeEvent(event)


# --- BARRA NOTIFICADORA NO HOST QUANDO CONECTADO ---
class HostOverlayWidget(QWidget):
    stop_signal = pyqtSignal()

    def __init__(self, client_ip):
        super().__init__()
        self.client_ip = client_ip
        self.init_ui()

    def init_ui(self):
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 8, 15, 8)

        frame = QFrame(self)
        frame.setStyleSheet("""
            QFrame {
                background-color: rgba(30, 30, 30, 230);
                border-radius: 8px;
                border: 1px solid rgba(255, 255, 255, 30);
            }
            QLabel { color: white; font-weight: bold; font-family: Segoe UI; }
            QPushButton {
                background-color: #d9383a;
                color: white;
                border-radius: 4px;
                padding: 4px 10px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #b82527; }
        """)
        f_layout = QHBoxLayout(frame)
        
        lbl = QLabel(f"🟢 Conexão Ativa: {self.client_ip}")
        btn_stop = QPushButton("Encerrar Conexão")
        btn_stop.clicked.connect(self.stop_signal.emit)

        f_layout.addWidget(lbl)
        f_layout.addSpacing(10)
        f_layout.addWidget(btn_stop)

        layout.addWidget(frame)
        self.adjustSize()

        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - self.width() - 20, screen.height() - self.height() - 50)


# --- SERVIDOR HOST ---
class HostServer:
    def __init__(self):
        self.mouse = MouseController()
        self.keyboard = KeyboardController()
        self.selected_monitor_idx = 1
        self.monitor_offset_x = 0
        self.monitor_offset_y = 0
        self.is_running = True
        self.status_widget = None

    def start(self):
        threading.Thread(target=self._stream_video, daemon=True).start()
        threading.Thread(target=self._receive_inputs, daemon=True).start()
        threading.Thread(target=self._receive_files, daemon=True).start()

    def stop(self):
        self.is_running = False
        if self.status_widget:
            self.status_widget.close()

    def _stream_video(self):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(('0.0.0.0', PORT_VIDEO))
        server_socket.listen(1)

        with mss.mss() as sct:
            while self.is_running:
                try:
                    conn, addr = server_socket.accept()
                    while self.is_running:
                        available_monitors = len(sct.monitors) - 1
                        idx = self.selected_monitor_idx if self.selected_monitor_idx <= available_monitors else 1

                        monitor = sct.monitors[idx]
                        self.monitor_offset_x = monitor["left"]
                        self.monitor_offset_y = monitor["top"]

                        img = np.array(sct.grab(monitor))
                        frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

                        _, encoded_frame = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                        data = pickle.dumps(encoded_frame)
                        size = len(data)
                        conn.sendall(struct.pack(">L", size) + data)
                except Exception:
                    continue

    def _receive_inputs(self):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(('0.0.0.0', PORT_INPUT))
        server_socket.listen(1)

        while self.is_running:
            try:
                conn, addr = server_socket.accept()
                
                QTimer.singleShot(0, lambda: self._show_host_overlay(addr[0]))

                while self.is_running:
                    data_size = conn.recv(4)
                    if not data_size: break
                    size = struct.unpack(">L", data_size)[0]

                    data = b""
                    while len(data) < size:
                        packet = conn.recv(size - len(data))
                        if not packet: break
                        data += packet

                    cmd = pickle.loads(data)

                    if cmd['type'] == 'select_monitor':
                        self.selected_monitor_idx = cmd['index']
                    elif cmd['type'] == 'move':
                        self.mouse.position = (int(cmd['x'] + self.monitor_offset_x), int(cmd['y'] + self.monitor_offset_y))
                    elif cmd['type'] == 'click_press':
                        self.mouse.press(BUTTON_MAP.get(cmd['button'], Button.left))
                    elif cmd['type'] == 'click_release':
                        self.mouse.release(BUTTON_MAP.get(cmd['button'], Button.left))
                    elif cmd['type'] in ('key_press', 'key_release'):
                        k = cmd['key']
                        mapped_key = getattr(Key, k, k)
                        if cmd['type'] == 'key_press':
                            self.keyboard.press(mapped_key)
                        else:
                            self.keyboard.release(mapped_key)
                    elif cmd['type'] == 'swap_roles':
                        self.stop()
            except Exception:
                continue

    def _show_host_overlay(self, client_ip):
        self.status_widget = HostOverlayWidget(client_ip)
        self.status_widget.stop_signal.connect(self.stop)
        self.status_widget.show()

    def _receive_files(self):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(('0.0.0.0', PORT_FILE))
        server_socket.listen(1)

        # Pasta Transferencia criada na raiz do projeto
        base_dir = os.path.dirname(os.path.abspath(__file__))
        save_dir = os.path.join(base_dir, "Transferencia")
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        while self.is_running:
            try:
                conn, _ = server_socket.accept()
                header_size_data = conn.recv(4)
                if not header_size_data: continue
                header_size = struct.unpack(">L", header_size_data)[0]

                header_data = conn.recv(header_size)
                header = json.loads(header_data.decode())

                file_path = os.path.join(save_dir, header["name"])
                with open(file_path, "wb") as f:
                    remaining = header["size"]
                    while remaining > 0:
                        chunk = conn.recv(min(65536, remaining))
                        if not chunk: break
                        f.write(chunk)
                        remaining -= len(chunk)
                conn.close()
            except Exception as e:
                print(f"Erro na recepção do arquivo: {e}")


# --- PAINEL PRINCIPAL (LAUNCHER) ---
class MainLauncher(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.viewer_window = None
        self.host_server = None

    def init_ui(self):
        self.setWindowTitle("Painel Acesso Remoto")
        self.setWindowIcon(QIcon(":/img/ico.png"))
        self.setFixedSize(380, 220)
        self.setStyleSheet("""
            QWidget { background-color: #1e1e1e; color: white; font-family: Segoe UI, sans-serif; }
            QPushButton {
                font-size: 14px; font-weight: bold; border-radius: 6px; padding: 12px;
            }
        """)

        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(25, 20, 25, 20)

        title = QLabel("Selecione o modo de operação:")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #dddddd;")
        layout.addWidget(title)

        self.btn_connect = QPushButton("Conectar", self)
        self.btn_connect.setStyleSheet("QPushButton { background-color: #2e7d32; } QPushButton:hover { background-color: #1b5e20; }")
        self.btn_connect.clicked.connect(self.action_connect)
        layout.addWidget(self.btn_connect)

        self.btn_receive = QPushButton("Receber Conexão", self)
        self.btn_receive.setStyleSheet("QPushButton { background-color: #c62828; } QPushButton:hover { background-color: #b71c1c; }")
        self.btn_receive.clicked.connect(self.action_receive)
        layout.addWidget(self.btn_receive)

        self.lbl_status = QLabel("", self)
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        self.setLayout(layout)

    def action_connect(self):
        last_ip = load_last_ip()
        ip, ok = QInputDialog.getText(self, "Conectar", "IP do Computador Host:", text=last_ip)
        if ok and ip.strip():
            target_ip = ip.strip()
            save_last_ip(target_ip)
            self.viewer_window = ViewerWindow(target_ip)
            self.viewer_window.show()
            self.close()

    def action_receive(self):
        local_ip = get_local_ip()
        self.btn_connect.setEnabled(False)
        self.btn_receive.setEnabled(False)
        self.lbl_status.setText(f"Seu IP: {local_ip}\nAguardando conexão...")
        self.lbl_status.setStyleSheet("color: #4fc3f7; font-weight: bold;")

        self.host_server = HostServer()
        self.host_server.start()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    launcher = MainLauncher()
    launcher.show()
    sys.exit(app.exec_())