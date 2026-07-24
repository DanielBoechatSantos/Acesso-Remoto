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
                             QPushButton, QLabel, QInputDialog, QMessageBox, QComboBox)
from PyQt5.QtGui import QImage, QPixmap, QIcon
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer, QDateTime, QRect
from pynput.mouse import Controller as MouseController, Button
from pynput.keyboard import Controller as KeyboardController, KeyCode, Key

# Configurações de Rede
PORT_VIDEO = 9999
PORT_INPUT = 9998
CONFIG_FILE = "remote_config.json"

BUTTON_MAP = {
    'left': Button.left,
    'right': Button.right,
    'middle': Button.middle
}

# --- FUNÇÕES UTILITÁRIAS ---
def get_local_ip():
    """Obtém o IP local primário do computador."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def load_last_ip():
    """Carrega o último IP salvo no JSON."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                return data.get("last_ip", "192.168.1.50")
        except Exception:
            pass
    return "192.168.1.50"

def save_last_ip(ip):
    """Salva o IP informado para as próximas sessões."""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump({"last_ip": ip}, f)
    except Exception as e:
        print(f"Erro ao salvar configuração: {e}")

# --- THREAD DE RECEPÇÃO DE VÍDEO (CLIENTE) ---
class VideoThread(QThread):
    change_pixmap_signal = pyqtSignal(QImage, int, int, int)

    def __init__(self, server_ip):
        super().__init__()
        self.server_ip = server_ip
        self.running = True

    def run(self):
        client_video = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            client_video.connect((self.server_ip, PORT_VIDEO))
        except Exception as e:
            print(f"Erro ao conectar ao servidor de vídeo: {e}")
            return

        data = b""
        payload_size = struct.calcsize(">L")
        
        while self.running:
            try:
                while len(data) < payload_size:
                    packet = client_video.recv(4096)
                    if not packet: break
                    data += packet
                
                if len(data) < payload_size: break
                
                packed_msg_size = data[:payload_size]
                data = data[payload_size:]
                msg_size = struct.unpack(">L", packed_msg_size)[0]
                
                while len(data) < msg_size:
                    packet = client_video.recv(4096)
                    if not packet: break
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
            except Exception:
                break
        client_video.close()

# --- JANELA DE VISUALIZAÇÃO/CONTROLE REMOTO (CLIENTE) ---
class ViewerWindow(QWidget):
    def __init__(self, server_ip):
        super().__init__()
        self.server_ip = server_ip
        
        try:
            self.hostname = socket.gethostbyaddr(self.server_ip)[0]
        except Exception:
            self.hostname = self.server_ip

        self.setWindowTitle("Acesso Remoto - Conectado")
        self.setWindowIcon(QIcon(":/img/ico.png"))
        self.resize(1280, 720)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # Barra superior para seleção do monitor
        self.top_bar = QHBoxLayout()
        self.top_bar.setContentsMargins(5, 5, 5, 5)
        self.monitor_combo = QComboBox(self)
        self.monitor_combo.addItems(["Monitor 1", "Monitor 2"])
        self.monitor_combo.currentIndexChanged.connect(self.change_monitor)
        
        self.top_bar.addWidget(QLabel(" Selecionar Display: ", self))
        self.top_bar.addWidget(self.monitor_combo)
        self.top_bar.addStretch()
        self.layout.addLayout(self.top_bar)

        self.screen_label = QLabel(self)
        self.screen_label.setAlignment(Qt.AlignCenter)
        self.screen_label.setStyleSheet("background-color: black;")
        self.layout.addWidget(self.screen_label)
        
        self.setMouseTracking(True)
        self.screen_label.setMouseTracking(True)
        
        self.client_input = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.client_input.connect((self.server_ip, PORT_INPUT))
        except Exception as e:
            print(f"Erro ao conectar canal de comandos: {e}")

        self.remote_w = 1920
        self.remote_h = 1080
        self.current_pixmap = None

        self.fps_counter = 0
        self.data_counter = 0
        
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self.update_title_bar)
        self.stats_timer.start(1000)

        self.thread = VideoThread(self.server_ip)
        self.thread.change_pixmap_signal.connect(self.update_image)
        self.thread.start()

    def change_monitor(self, index):
        self.send_cmd({'type': 'select_monitor', 'index': index + 1})

    def update_image(self, qt_img, actual_w, actual_h, bytes_received):
        self.remote_w = actual_w
        self.remote_h = actual_h
        self.fps_counter += 1
        self.data_counter += bytes_received
        
        try:
            self.current_pixmap = QPixmap.fromImage(qt_img)
            self.resize_screen()
        except Exception as e:
            print(f"Erro de renderização: {e}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resize_screen()

    def resize_screen(self):
        if self.current_pixmap and not self.current_pixmap.isNull():
            lbl_size = self.screen_label.size()
            if lbl_size.width() > 0 and lbl_size.height() > 0:
                scaled_pixmap = self.current_pixmap.scaled(lbl_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.screen_label.setPixmap(scaled_pixmap)

    def update_title_bar(self):
        fps = self.fps_counter
        mbps = (self.data_counter * 8) / (1024 * 1024)
        self.fps_counter = 0
        self.data_counter = 0
        
        current_time = QDateTime.currentDateTime().toString("hh:mm:ss")
        title = f"Remoto: {self.hostname} | FPS: {fps} | Rede: {mbps:.2f} Mbps | {current_time}"
        self.setWindowTitle(title)
        self.setWindowIcon(QIcon(":/img/ico.png"))

    def get_remote_coords(self, global_pos):
        """Calcula com precisão a coordenada dentro do frame remoto sem interferência das barras pretas."""
        pixmap = self.screen_label.pixmap()
        if not pixmap or pixmap.isNull():
            return 0, 0

        # Mapeia a posição global do cursor para o espaço local do QLabel
        local_pos = self.screen_label.mapFromGlobal(global_pos)
        lx, ly = local_pos.x(), local_pos.y()

        lbl_w, lbl_h = self.screen_label.width(), self.screen_label.height()
        pm_w, pm_h = pixmap.width(), pixmap.height()

        # Descobre o retângulo exato onde a imagem foi desenhada (descontando as bordas pretas)
        offset_x = (lbl_w - pm_w) / 2
        offset_y = (lbl_h - pm_h) / 2

        rel_x = lx - offset_x
        rel_y = ly - offset_y

        # Limita o cursor para não enviar posições fora do quadro visível
        rel_x = max(0, min(rel_x, pm_w))
        rel_y = max(0, min(rel_y, pm_h))

        # Converte a escala relativa para a resolução real remota
        rx = int((rel_x / pm_w) * self.remote_w)
        ry = int((rel_y / pm_h) * self.remote_h)

        return rx, ry

    def send_cmd(self, cmd):
        try:
            data = pickle.dumps(cmd)
            self.client_input.sendall(struct.pack(">L", len(data)) + data)
        except Exception:
            pass

    def mouseMoveEvent(self, event):
        rx, ry = self.get_remote_coords(event.globalPos())
        self.send_cmd({'type': 'move', 'x': rx, 'y': ry})

    def mousePressEvent(self, event):
        btn = 'left'
        if event.button() == Qt.RightButton: btn = 'right'
        elif event.button() == Qt.MidButton: btn = 'middle'
        self.send_cmd({'type': 'click_press', 'button': btn})

    def mouseReleaseEvent(self, event):
        btn = 'left'
        if event.button() == Qt.RightButton: btn = 'right'
        elif event.button() == Qt.MidButton: btn = 'middle'
        self.send_cmd({'type': 'click_release', 'button': btn})

    def keyPressEvent(self, event):
        self.handle_key(event, 'key_press')

    def keyReleaseEvent(self, event):
        self.handle_key(event, 'key_release')

    def handle_key(self, event, event_type):
        vk = event.nativeVirtualKey()
        key_text = event.text()
        if not key_text or event.key() >= Qt.Key_Escape:
            meta_keys = {Qt.Key_Control: 'ctrl', Qt.Key_Shift: 'shift', Qt.Key_Alt: 'alt', 
                         Qt.Key_Enter: 'enter', Qt.Key_Return: 'enter', Qt.Key_Backspace: 'backspace'}
            key_text = meta_keys.get(event.key(), '')
        self.send_cmd({'type': event_type, 'key': key_text, 'vk': vk})

    def closeEvent(self, event):
        self.thread.running = False
        self.stats_timer.stop()
        try:
            self.client_input.close()
        except Exception:
            pass
        super().closeEvent(event)

# --- MÓDULO SERVIDOR DE TRANSMISSÃO E COMANDOS (RECEBER CONEXÃO) ---
class HostServer:
    def __init__(self):
        self.mouse = MouseController()
        self.keyboard = KeyboardController()
        self.selected_monitor_idx = 1
        self.monitor_offset_x = 0
        self.monitor_offset_y = 0
        self.is_running = True

    def start(self):
        threading.Thread(target=self._stream_video, daemon=True).start()
        threading.Thread(target=self._receive_inputs, daemon=True).start()

    def _stream_video(self):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(('0.0.0.0', PORT_VIDEO))
        server_socket.listen(1)
        
        with mss.mss() as sct:
            while self.is_running:
                try:
                    conn, _ = server_socket.accept()
                    while self.is_running:
                        available_monitors = len(sct.monitors) - 1
                        idx = self.selected_monitor_idx if self.selected_monitor_idx <= available_monitors else 1
                        
                        monitor = sct.monitors[idx]
                        
                        # Atualiza a posição de origem (Top/Left) do monitor selecionado no ambiente multi-tela
                        self.monitor_offset_x = monitor["left"]
                        self.monitor_offset_y = monitor["top"]

                        img = np.array(sct.grab(monitor))
                        frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                        
                        _, encoded_frame = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                        data = pickle.dumps(encoded_frame)
                        size = len(data)
                        conn.sendall(struct.pack(">L", size) + data)
                except (ConnectionResetError, BrokenPipeError):
                    continue
                except Exception:
                    break

    def _receive_inputs(self):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(('0.0.0.0', PORT_INPUT))
        server_socket.listen(1)
        
        while self.is_running:
            try:
                conn, _ = server_socket.accept()
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
                        # Aplica o offset global do monitor selecionado na máquina Host
                        abs_x = cmd['x'] + self.monitor_offset_x
                        abs_y = cmd['y'] + self.monitor_offset_y
                        self.mouse.position = (abs_x, abs_y)
                    elif cmd['type'] == 'click_press':
                        self.mouse.press(BUTTON_MAP.get(cmd['button'], Button.left))
                    elif cmd['type'] == 'click_release':
                        self.mouse.release(BUTTON_MAP.get(cmd['button'], Button.left))
                    elif cmd['type'] == 'key_press':
                        k = KeyCode.from_vk(cmd['vk']) if cmd['vk'] else getattr(Key, cmd['key'], cmd['key'])
                        self.keyboard.press(k)
                    elif cmd['type'] == 'key_release':
                        k = KeyCode.from_vk(cmd['vk']) if cmd['vk'] else getattr(Key, cmd['key'], cmd['key'])
                        self.keyboard.release(k)
            except Exception:
                continue

# --- PAINEL PRINCIPAL (INTERFACE INICIAL) ---
class MainLauncher(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.viewer_window = None
        self.host_server = None

    def init_ui(self):
        self.setWindowTitle("Painel de Controle Remoto")
        self.setFixedSize(420, 240)
        self.setWindowIcon(QIcon(":/img/ico.png"))
        
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        title_label = QLabel("Selecione o modo de operação:")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        layout.addWidget(title_label)

        self.btn_connect = QPushButton("Conectar", self)
        self.btn_connect.setStyleSheet("""
            QPushButton {
                background-color: #2ea44f; 
                color: white; 
                font-size: 14px; 
                font-weight: bold; 
                border-radius: 6px; 
                padding: 12px;
            }
            QPushButton:hover { background-color: #2c974b; }
        """)
        self.btn_connect.clicked.connect(self.action_connect)
        layout.addWidget(self.btn_connect)

        self.btn_receive = QPushButton("Receber Conexão", self)
        self.btn_receive.setStyleSheet("""
            QPushButton {
                background-color: #cb2431; 
                color: white; 
                font-size: 14px; 
                font-weight: bold; 
                border-radius: 6px; 
                padding: 12px;
            }
            QPushButton:hover { background-color: #b31d28; }
        """)
        self.btn_receive.clicked.connect(self.action_receive)
        layout.addWidget(self.btn_receive)

        self.lbl_status = QLabel("", self)
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setStyleSheet("color: #555555; font-size: 12px;")
        layout.addWidget(self.lbl_status)

        self.setLayout(layout)

    def action_connect(self):
        last_ip = load_last_ip()
        ip, ok = QInputDialog.getText(self, "Conectar a um Computador", 
                                       "Digite o endereço IP do host:", text=last_ip)
        
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
        
        self.lbl_status.setText(f"Seu IP: {local_ip}\nAguardando conexão remota...")
        self.lbl_status.setStyleSheet("color: #0066cc; font-weight: bold; font-size: 13px;")

        self.host_server = HostServer()
        self.host_server.start()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    launcher = MainLauncher()
    launcher.show()
    sys.exit(app.exec_())