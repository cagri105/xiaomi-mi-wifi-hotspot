import sys
import os
import secrets
import string
import threading
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QFrame, QDialog,
    QSystemTrayIcon, QMenu, QGraphicsDropShadowEffect,
    QRadioButton, QButtonGroup, QGridLayout
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QIcon, QPixmap, QColor, QFont, QPainter, QImage

from wifi_service import WiFiService

class WorkerSignals(QObject):
    hotspot_status_ready = pyqtSignal(dict)
    hotspot_action_done = pyqtSignal(str)
    wifi_scan_ready = pyqtSignal(list)
    wifi_connect_done = pyqtSignal(str)
    adapters_ready = pyqtSignal(list)
    driver_status_ready = pyqtSignal(dict)
    traffic_ready = pyqtSignal(dict)
    message_box = pyqtSignal(str, str, str)

class XiaomiWiFiApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.service = WiFiService()
        self.signals = WorkerSignals()
        self.is_hotspot_active = False
        self.driver_status = {}
        
        self.init_ui()
        self.init_signals()
        self.init_tray()
        
        # Periodic timers
        self.traffic_timer = QTimer(self)
        self.traffic_timer.timeout.connect(self.update_traffic_async)
        self.traffic_timer.start(2500)
        
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.check_status_async)
        self.status_timer.start(4000)
        
        # Initial checks
        QTimer.singleShot(300, self.check_driver_async)
        QTimer.singleShot(600, self.check_status_async)
        QTimer.singleShot(1000, self.refresh_adapters_async)

    def init_ui(self):
        self.setWindowTitle("Xiaomi Mi WiFi")
        # Compact, elegant window size
        self.setFixedSize(560, 640)
        
        # Windows 11 Fluent Dark Style
        self.setStyleSheet("""
            QMainWindow {
                background-color: #202020;
            }
            QWidget {
                color: #FFFFFF;
                font-family: 'Segoe UI Variable', 'Segoe UI', Arial, sans-serif;
                font-size: 12px;
            }
            QTabWidget::pane {
                border: 1px solid #333333;
                background-color: #272727;
                border-radius: 8px;
                top: -1px;
            }
            QTabBar::tab {
                background: #1C1C1C;
                color: #A6A6A6;
                padding: 8px 14px;
                font-size: 12px;
                font-weight: 600;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 3px;
            }
            QTabBar::tab:selected {
                background: #272727;
                color: #FF6900;
                border-bottom: 2px solid #FF6900;
            }
            QTabBar::tab:hover:!selected {
                background: #232323;
                color: #E0E0E0;
            }
            QLineEdit {
                background-color: #1E1E1E;
                border: 1px solid #383838;
                border-radius: 6px;
                padding: 6px 10px;
                color: #FFFFFF;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #FF6900;
                background-color: #222222;
            }
            QRadioButton {
                color: #FFFFFF;
                font-size: 12px;
                spacing: 8px;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                border: 2px solid #555555;
                background-color: #1E1E1E;
            }
            QRadioButton::indicator:checked {
                border: 2px solid #FF6900;
                background-color: #FF6900;
            }
            QPushButton {
                background-color: #FF6900;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 7px 14px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #FF7D26;
            }
            QPushButton:pressed {
                background-color: #E05C00;
            }
            QPushButton#secondaryBtn {
                background-color: #333333;
                color: #E0E0E0;
                border: 1px solid #444444;
            }
            QPushButton#secondaryBtn:hover {
                background-color: #3E3E3E;
                color: #FFFFFF;
            }
            QPushButton#actionBtn {
                background-color: #0078D4;
                color: #FFFFFF;
            }
            QPushButton#actionBtn:hover {
                background-color: #1A86D9;
            }
            QPushButton#dangerBtn {
                background-color: #C42B1C;
                color: #FFFFFF;
            }
            QPushButton#dangerBtn:hover {
                background-color: #D83B01;
            }
            QTableWidget {
                background-color: #1E1E1E;
                border: 1px solid #333333;
                border-radius: 6px;
                gridline-color: #2D2D2D;
                color: #E0E0E0;
                font-size: 11px;
            }
            QHeaderView::section {
                background-color: #262626;
                color: #FF6900;
                padding: 5px;
                font-weight: bold;
                font-size: 11px;
                border: none;
            }
            QTableWidget::item {
                padding: 4px;
            }
            QScrollBar:vertical {
                border: none;
                background: #1E1E1E;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #383838;
                min-height: 16px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #FF6900;
            }
            QMessageBox, QDialog {
                background-color: #272727;
                color: #FFFFFF;
            }
            QMessageBox QLabel, QDialog QLabel {
                color: #FFFFFF;
                font-size: 13px;
                font-weight: 500;
                background-color: transparent;
            }
            QMessageBox QPushButton {
                background-color: #FF6900;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 6px 18px;
                font-weight: bold;
                font-size: 12px;
                min-width: 65px;
            }
            QMessageBox QPushButton:hover {
                background-color: #FF7D26;
            }
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(10)

        # Header Bar
        header_bar = self.create_header_bar()
        main_layout.addWidget(header_bar)

        # Driver Warning Banner (Shown only if driver is genuinely missing)
        self.driver_banner = self.create_driver_banner()
        self.driver_banner.setVisible(False)
        main_layout.addWidget(self.driver_banner)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self.create_hotspot_tab(), "📡 Mobil Hotspot")
        self.tabs.addTab(self.create_ip_dns_tab(), "🌐 Özel DNS")
        self.tabs.addTab(self.create_wifi_tab(), "📶 Wi-Fi Ağları")
        self.tabs.addTab(self.create_adapter_tab(), "⚙️ Ayarlar & Araçlar")
        
        main_layout.addWidget(self.tabs)

        # Bottom Compact Status Bar
        self.create_status_footer(main_layout)

    def create_header_bar(self):
        bar = QFrame()
        bar.setStyleSheet("""
            QFrame {
                background-color: #272727;
                border: 1px solid #333333;
                border-radius: 8px;
            }
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 8, 12, 8)

        # Title
        title_layout = QVBoxLayout()
        title_layout.setSpacing(1)
        title_label = QLabel("Xiaomi Mi WiFi")
        title_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #FFFFFF;")
        sub_label = QLabel("USB Wireless Hotspot")
        sub_label.setStyleSheet("font-size: 11px; color: #8C8C8C;")
        title_layout.addWidget(title_label)
        title_layout.addWidget(sub_label)
        layout.addLayout(title_layout)

        layout.addStretch()

        # Dynamic Status Badge
        self.status_badge = QLabel("● Hazır")
        self.status_badge.setStyleSheet("""
            background-color: #1B2E21;
            color: #4CC2FF;
            border: 1px solid #4CC2FF;
            border-radius: 12px;
            padding: 4px 12px;
            font-weight: 600;
            font-size: 11px;
        """)
        layout.addWidget(self.status_badge)

        # About / Info Button
        btn_about = QPushButton("ℹ️")
        btn_about.setFixedSize(28, 28)
        btn_about.setToolTip("Hakkında / About")
        btn_about.setStyleSheet("""
            QPushButton {
                background-color: #333333;
                color: #FFFFFF;
                border: 1px solid #444444;
                border-radius: 14px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #0078D4;
                border-color: #4CC2FF;
            }
        """)
        btn_about.clicked.connect(self.show_about_dialog)
        layout.addWidget(btn_about)

        return bar

    def create_driver_banner(self):
        banner = QFrame()
        banner.setStyleSheet("""
            QFrame {
                background-color: #382414;
                border: 1px solid #FF6900;
                border-radius: 6px;
            }
        """)
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(10, 6, 10, 6)

        msg_lbl = QLabel("⚠️ Sürücü eksik görünüyor.")
        msg_lbl.setStyleSheet("color: #FFCC80; font-size: 11px;")
        layout.addWidget(msg_lbl)

        layout.addStretch()

        btn_install = QPushButton("⚡ Sürücüyü Yükle")
        btn_install.setStyleSheet("background-color: #008A00; padding: 4px 10px; font-size: 11px;")
        btn_install.clicked.connect(self.on_trigger_driver_install)
        layout.addWidget(btn_install)

        return banner

    # =========================================================================
    # TAB 1: HOTSPOT (COMPACT & CLEAN)
    # =========================================================================
    def create_hotspot_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 1. Hotspot Toggle Card
        toggle_card = QFrame()
        toggle_card.setStyleSheet("background-color: #202020; border: 1px solid #333333; border-radius: 6px;")
        t_layout = QHBoxLayout(toggle_card)
        t_layout.setContentsMargins(12, 10, 12, 10)

        self.hotspot_state_label = QLabel("Hotspot: KAPALI")
        self.hotspot_state_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #FF5252;")
        t_layout.addWidget(self.hotspot_state_label)

        t_layout.addStretch()

        self.btn_toggle_hotspot = QPushButton("🚀 Hotspot'ı Başlat")
        self.btn_toggle_hotspot.setFixedWidth(160)
        self.btn_toggle_hotspot.setFixedHeight(34)
        self.btn_toggle_hotspot.clicked.connect(self.on_toggle_hotspot)
        t_layout.addWidget(self.btn_toggle_hotspot)
        layout.addWidget(toggle_card)

        # 2. Configuration & QR Row
        cfg_row = QHBoxLayout()
        cfg_row.setSpacing(10)

        # Config Box
        cfg_box = QFrame()
        cfg_box.setStyleSheet("background-color: #202020; border: 1px solid #333333; border-radius: 6px;")
        c_lay = QVBoxLayout(cfg_box)
        c_lay.setContentsMargins(10, 10, 10, 10)
        c_lay.setSpacing(6)

        c_lay.addWidget(QLabel("Wi-Fi Adı (SSID):"))
        self.input_ssid = QLineEdit("Xiaomi_MiWiFi")
        c_lay.addWidget(self.input_ssid)

        c_lay.addWidget(QLabel("Şifre (En az 8 karakter):"))
        p_lay = QHBoxLayout()
        p_lay.setSpacing(4)
        self.input_pass = QLineEdit("12345678")
        p_lay.addWidget(self.input_pass)

        btn_rand = QPushButton("🎲")
        btn_rand.setToolTip("Rastgele Şifre")
        btn_rand.setObjectName("secondaryBtn")
        btn_rand.setFixedWidth(32)
        btn_rand.clicked.connect(self.generate_random_password)
        p_lay.addWidget(btn_rand)
        c_lay.addLayout(p_lay)

        btn_save = QPushButton("💾 Ayarları Uygula")
        btn_save.setObjectName("secondaryBtn")
        btn_save.clicked.connect(self.on_save_hotspot_config)
        c_lay.addWidget(btn_save)

        cfg_row.addWidget(cfg_box, 60)

        # QR Code Box
        qr_box = QFrame()
        qr_box.setStyleSheet("background-color: #202020; border: 1px solid #333333; border-radius: 6px;")
        q_lay = QVBoxLayout(qr_box)
        q_lay.setContentsMargins(8, 8, 8, 8)
        q_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.qr_label = QLabel()
        self.qr_label.setFixedSize(110, 110)
        self.qr_label.setStyleSheet("background-color: #FFFFFF; border-radius: 4px;")
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        q_lay.addWidget(self.qr_label)

        lbl_qr_hint = QLabel("📱 Tara ve Bağlan")
        lbl_qr_hint.setStyleSheet("font-size: 10px; color: #A0A0A0;")
        lbl_qr_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        q_lay.addWidget(lbl_qr_hint)

        cfg_row.addWidget(qr_box, 40)
        layout.addLayout(cfg_row)

        # 3. Connected Devices Table
        dev_card = QFrame()
        dev_card.setStyleSheet("background-color: #202020; border: 1px solid #333333; border-radius: 6px;")
        d_lay = QVBoxLayout(dev_card)
        d_lay.setContentsMargins(10, 8, 10, 8)
        d_lay.setSpacing(6)

        self.dev_header = QLabel("Bağlı Cihazlar (0)")
        self.dev_header.setStyleSheet("font-weight: bold; color: #FF6900; font-size: 11px;")
        d_lay.addWidget(self.dev_header)

        self.table_clients = QTableWidget(0, 4)
        self.table_clients.setHorizontalHeaderLabels(["Cihaz", "IP Adresi", "MAC", "Durum"])
        self.table_clients.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_clients.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_clients.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table_clients.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_clients.setFixedHeight(120)
        d_lay.addWidget(self.table_clients)

        layout.addWidget(dev_card)
        self.update_qr_code()
        return tab

    # =========================================================================
    # TAB 2: DNS & NETWORK SECURITY CONFIGURATION
    # =========================================================================
    def create_ip_dns_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 1. Info Card
        info_card = QFrame()
        info_card.setStyleSheet("background-color: #202020; border: 1px solid #333333; border-radius: 6px;")
        i_lay = QVBoxLayout(info_card)
        i_lay.setContentsMargins(12, 10, 12, 10)
        i_lay.setSpacing(4)

        lbl_info_title = QLabel("<b>📡 Ağ Dağıtım Bloğu: 192.168.137.x (Standart)</b>")
        lbl_info_title.setStyleSheet("font-size: 12px; color: #00D26A;")
        i_lay.addWidget(lbl_info_title)

        lbl_info_desc = QLabel("Windows Mobil Etkin Nokta varsayılan IP havuzunu (192.168.137.1) kullanır.\nBağlanan cihazların daha hızlı ve güvenli internete erişmesi için aşağıdan Özel DNS seçebilirsiniz.")
        lbl_info_desc.setStyleSheet("font-size: 10px; color: #AAAAAA;")
        lbl_info_desc.setWordWrap(True)
        i_lay.addWidget(lbl_info_desc)
        layout.addWidget(info_card)

        # 2. Custom DNS Settings Card
        dns_card = QFrame()
        dns_card.setStyleSheet("background-color: #202020; border: 1px solid #333333; border-radius: 6px;")
        d_lay = QVBoxLayout(dns_card)
        d_lay.setContentsMargins(12, 10, 12, 10)
        d_lay.setSpacing(6)

        lbl_dns_title = QLabel("<b>Özel DNS Sunucuları (Telefona Dağıtılacak):</b>")
        lbl_dns_title.setStyleSheet("font-size: 11px; color: #FFFFFF;")
        d_lay.addWidget(lbl_dns_title)

        grid_dns = QHBoxLayout()
        grid_dns.setSpacing(8)

        v_pdns = QVBoxLayout()
        v_pdns.addWidget(QLabel("Birincil DNS (Primary):"))
        self.input_pdns = QLineEdit("8.8.8.8")
        v_pdns.addWidget(self.input_pdns)
        grid_dns.addLayout(v_pdns)

        v_sdns = QVBoxLayout()
        v_sdns.addWidget(QLabel("İkincil DNS (Secondary):"))
        self.input_sdns = QLineEdit("1.1.1.1")
        v_sdns.addWidget(self.input_sdns)
        grid_dns.addLayout(v_sdns)

        d_lay.addLayout(grid_dns)

        # Quick DNS Presets Row
        lbl_presets = QLabel("Hızlı DNS Şablonları:")
        lbl_presets.setStyleSheet("font-size: 10px; color: #888888; margin-top: 4px;")
        d_lay.addWidget(lbl_presets)

        preset_lay = QHBoxLayout()
        preset_lay.setSpacing(5)

        btn_google = QPushButton("⚡ Google (8.8.8.8)")
        btn_google.setObjectName("secondaryBtn")
        btn_google.clicked.connect(lambda: self.set_dns_preset("8.8.8.8", "8.8.4.4"))
        preset_lay.addWidget(btn_google)

        btn_cf = QPushButton("🛡️ Cloudflare (1.1.1.1)")
        btn_cf.setObjectName("secondaryBtn")
        btn_cf.clicked.connect(lambda: self.set_dns_preset("1.1.1.1", "1.0.0.1"))
        preset_lay.addWidget(btn_cf)

        btn_adguard = QPushButton("🚫 AdGuard (Reklam Engelle)")
        btn_adguard.setObjectName("secondaryBtn")
        btn_adguard.clicked.connect(lambda: self.set_dns_preset("94.140.14.14", "94.140.15.15"))
        preset_lay.addWidget(btn_adguard)

        btn_quad9 = QPushButton("🔒 Quad9 (Zararlı Yazılım)")
        btn_quad9.setObjectName("secondaryBtn")
        btn_quad9.clicked.connect(lambda: self.set_dns_preset("9.9.9.9", "149.112.112.112"))
        preset_lay.addWidget(btn_quad9)

        d_lay.addLayout(preset_lay)
        layout.addWidget(dns_card)

        # 3. Save & Apply Action Card
        btn_save_net = QPushButton("💾 DNS Ayarlarını Kaydet ve Uygula")
        btn_save_net.setFixedHeight(34)
        btn_save_net.setStyleSheet("background-color: #0078D4; font-weight: bold; font-size: 12px;")
        btn_save_net.clicked.connect(self.on_apply_network_settings)
        layout.addWidget(btn_save_net)

        layout.addStretch()

        # Load initial saved config
        self.load_network_ui_values()
        return tab

    def load_network_ui_values(self):
        cfg = self.service.get_network_config()
        self.input_pdns.setText(cfg.get("primary_dns", "8.8.8.8"))
        self.input_sdns.setText(cfg.get("secondary_dns", "1.1.1.1"))

    def set_dns_preset(self, p_dns: str, s_dns: str):
        self.input_pdns.setText(p_dns)
        self.input_sdns.setText(s_dns)

    def on_apply_network_settings(self):
        pdns = self.input_pdns.text().strip() or "8.8.8.8"
        sdns = self.input_sdns.text().strip() or "1.1.1.1"

        cfg = {
            "primary_dns": pdns,
            "secondary_dns": sdns
        }

        def run():
            ok, msg = self.service.apply_network_config(cfg)
            if ok:
                self.signals.message_box.emit("Yapılandırma Uygulandı", msg, "info")
            else:
                self.signals.message_box.emit("Hata", msg, "warning")

        threading.Thread(target=run, daemon=True).start()

    # =========================================================================
    # TAB 3: WIFI CLIENT
    # =========================================================================
    def create_wifi_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Connection status bar
        top_bar = QHBoxLayout()
        self.lbl_curr_wifi = QLabel("Mevcut: Bağlı Değil")
        self.lbl_curr_wifi.setStyleSheet("font-weight: bold; color: #FFFFFF;")
        top_bar.addWidget(self.lbl_curr_wifi)
        top_bar.addStretch()

        self.btn_scan = QPushButton("🔍 Tara")
        self.btn_scan.setObjectName("secondaryBtn")
        self.btn_scan.clicked.connect(self.scan_wifi_async)
        top_bar.addWidget(self.btn_scan)
        layout.addLayout(top_bar)

        # Table
        self.table_wifi = QTableWidget(0, 4)
        self.table_wifi.setHorizontalHeaderLabels(["Ağ Adı (SSID)", "Sinyal", "Güvenlik", "İşlem"])
        self.table_wifi.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_wifi.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_wifi.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_wifi.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table_wifi.setColumnWidth(3, 80)
        layout.addWidget(self.table_wifi)

        return tab

    # =========================================================================
    # TAB 3: SETTINGS & TOOLS
    # =========================================================================
    def create_adapter_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Speed Stats Row
        speed_box = QFrame()
        speed_box.setStyleSheet("background-color: #202020; border: 1px solid #333333; border-radius: 6px;")
        s_lay = QHBoxLayout(speed_box)
        s_lay.setContentsMargins(12, 10, 12, 10)

        v_down = QVBoxLayout()
        v_down.addWidget(QLabel("⬇️ İndirme (Download):"))
        self.lbl_down_speed = QLabel("0.0 KB/s")
        self.lbl_down_speed.setStyleSheet("font-size: 16px; font-weight: bold; color: #00E676;")
        v_down.addWidget(self.lbl_down_speed)
        s_lay.addLayout(v_down)

        s_lay.addStretch()

        v_up = QVBoxLayout()
        v_up.addWidget(QLabel("⬆️ Yükleme (Upload):"))
        self.lbl_up_speed = QLabel("0.0 KB/s")
        self.lbl_up_speed.setStyleSheet("font-size: 16px; font-weight: bold; color: #4CC2FF;")
        v_up.addWidget(self.lbl_up_speed)
        s_lay.addLayout(v_up)

        layout.addWidget(speed_box)

        # Hardware Info Box
        hw_box = QFrame()
        hw_box.setStyleSheet("background-color: #202020; border: 1px solid #333333; border-radius: 6px;")
        h_lay = QVBoxLayout(hw_box)
        h_lay.setContentsMargins(10, 8, 10, 8)
        h_lay.setSpacing(4)

        h_lay.addWidget(QLabel("<b>Donanım Bilgisi:</b>"))
        self.lbl_hw_status = QLabel("Xiaomi 802.11n USB Wireless Adapter (Hazır)")
        self.lbl_hw_status.setStyleSheet("color: #4CC2FF; font-size: 11px;")
        h_lay.addWidget(self.lbl_hw_status)
        layout.addWidget(hw_box)

        # Maintenance Buttons
        btn_box = QVBoxLayout()
        btn_box.setSpacing(6)

        btn_repair = QPushButton("🛠️ Hotspot & İnternet Bağlantısını Onar")
        btn_repair.setObjectName("actionBtn")
        btn_repair.clicked.connect(self.on_repair_network)
        btn_box.addWidget(btn_repair)

        btn_install = QPushButton("⚡ Sürücüyü Yeniden Yükle / Onar")
        btn_install.setObjectName("secondaryBtn")
        btn_install.clicked.connect(self.on_trigger_driver_install)
        btn_box.addWidget(btn_install)

        btn_flush = QPushButton("🔄 DNS & IP Yapılandırmasını Sıfırla")
        btn_flush.setObjectName("secondaryBtn")
        btn_flush.clicked.connect(self.on_flush_dns)
        btn_box.addWidget(btn_flush)

        btn_about = QPushButton("ℹ️ Geliştirici & Hakkında (About)")
        btn_about.setObjectName("secondaryBtn")
        btn_about.clicked.connect(self.show_about_dialog)
        btn_box.addWidget(btn_about)

        layout.addLayout(btn_box)
        layout.addStretch()
        return tab

    def create_status_footer(self, parent_layout):
        foot = QHBoxLayout()
        foot.setContentsMargins(4, 0, 4, 0)
        self.lbl_footer_speed = QLabel("Trafik: 0 KB/s")
        self.lbl_footer_speed.setStyleSheet("font-size: 10px; color: #888888;")
        foot.addWidget(self.lbl_footer_speed)
        foot.addStretch()

        lbl_ver = QLabel("v1.3 TR | cagri105")
        lbl_ver.setStyleSheet("font-size: 10px; color: #666666;")
        foot.addWidget(lbl_ver)
        parent_layout.addLayout(foot)

    # =========================================================================
    # SYSTEM TRAY
    # =========================================================================
    def init_tray(self):
        self.tray = QSystemTrayIcon(self)
        
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Modern rounded blue background
        painter.setBrush(QColor("#0078D4"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, 32, 32, 8, 8)
        
        # Wi-Fi wave symbol
        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(13, 22, 6, 6)
        
        pen = painter.pen()
        pen.setColor(QColor("#FFFFFF"))
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.SolidLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(8, 14, 16, 16, 45 * 16, 90 * 16)
        painter.drawArc(4, 8, 24, 24, 45 * 16, 90 * 16)
        painter.end()
        
        icon = QIcon(pixmap)
        self.setWindowIcon(icon)
        self.tray.setIcon(icon)

        menu = QMenu()
        act_show = menu.addAction("Arayüzü Göster")
        act_show.triggered.connect(self.showNormal)
        
        act_toggle = menu.addAction("Hotspot Başlat/Durdur")
        act_toggle.triggered.connect(self.on_toggle_hotspot)

        act_about = menu.addAction("ℹ️ Hakkında")
        act_about.triggered.connect(self.show_about_dialog)
        
        menu.addSeparator()
        act_quit = menu.addAction("Çıkış")
        act_quit.triggered.connect(self.quit_application)

        self.tray.setContextMenu(menu)
        self.tray.show()

    def show_about_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Hakkında / About")
        dlg.setFixedSize(380, 260)
        dlg.setStyleSheet("""
            QDialog {
                background-color: #1E1E1E;
                color: #FFFFFF;
                border: 1px solid #333333;
                border-radius: 8px;
            }
            QLabel {
                color: #DDDDDD;
            }
        """)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        # Title
        t_lbl = QLabel("<b>Xiaomi Mi WiFi Hotspot Controller</b>")
        t_lbl.setStyleSheet("font-size: 14px; color: #4CC2FF; font-weight: bold;")
        lay.addWidget(t_lbl)

        # Version & Info
        v_lbl = QLabel("Sürüm: v1.3 (Türkçe & Gelişmiş Ağ Araçları)")
        v_lbl.setStyleSheet("font-size: 11px; color: #888888;")
        lay.addWidget(v_lbl)

        # Description
        desc_lbl = QLabel(
            "Windows 10 & 11 için Xiaomi USB Wi-Fi adaptörleri ile sorunsuz mobil hotspot paylaşımı, özel DNS filtreleme, otomatik sürücü kurulumu ve ağ onarım aracı."
        )
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("font-size: 11px; color: #CCCCCC;")
        lay.addWidget(desc_lbl)

        # Developer Info Box
        dev_box = QFrame()
        dev_box.setStyleSheet("background-color: #262626; border: 1px solid #3A3A3A; border-radius: 6px;")
        d_lay = QVBoxLayout(dev_box)
        d_lay.setContentsMargins(10, 8, 10, 8)
        d_lay.setSpacing(3)

        dev_title = QLabel("<b>Geliştirici & İletişim:</b>")
        dev_title.setStyleSheet("font-size: 11px; color: #00E676;")
        d_lay.addWidget(dev_title)

        dev_info = QLabel("👤 cagri105\n✉️ mail: cagrii@gmail.com")
        dev_info.setStyleSheet("font-size: 11px; color: #FFFFFF; font-weight: 500;")
        d_lay.addWidget(dev_info)

        lay.addWidget(dev_box)

        # Close Button
        btn_close = QPushButton("Kapat")
        btn_close.setFixedHeight(28)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #0078D4;
                color: white;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #106EBE;
            }
        """)
        btn_close.clicked.connect(dlg.accept)
        lay.addWidget(btn_close)

        dlg.exec()

    def closeEvent(self, event):
        self.quit_application()
        event.accept()

    def quit_application(self, *args, **kwargs):
        if getattr(self, '_is_quitting', False):
            return
        self._is_quitting = True

        if hasattr(self, 'traffic_timer'):
            self.traffic_timer.stop()
        if hasattr(self, 'status_timer'):
            self.status_timer.stop()

        self.hide()
        if hasattr(self, 'tray'):
            self.tray.hide()

        try:
            self.service.stop_hotspot()
        except Exception as e:
            print("Exit stop hotspot error:", e)

        QApplication.instance().quit()

    # =========================================================================
    # SIGNALS & ASYNC METHODS
    # =========================================================================
    def init_signals(self):
        self.signals.hotspot_status_ready.connect(self.handle_hotspot_status)
        self.signals.hotspot_action_done.connect(self.handle_hotspot_action_done)
        self.signals.wifi_scan_ready.connect(self.handle_wifi_scan)
        self.signals.wifi_connect_done.connect(self.handle_wifi_connect_done)
        self.signals.adapters_ready.connect(self.handle_adapters_ready)
        self.signals.driver_status_ready.connect(self.handle_driver_status)
        self.signals.traffic_ready.connect(self.handle_traffic_ready)
        self.signals.message_box.connect(self.show_message)

    def show_message(self, title, text, icon_type):
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(text)
        if icon_type == "info":
            msg.setIcon(QMessageBox.Icon.Information)
        elif icon_type == "warning":
            msg.setIcon(QMessageBox.Icon.Warning)
        else:
            msg.setIcon(QMessageBox.Icon.Critical)
        msg.exec()

    def generate_random_password(self):
        alphabet = string.ascii_letters + string.digits
        pwd = ''.join(secrets.choice(alphabet) for _ in range(10))
        self.input_pass.setText(pwd)
        self.update_qr_code()

    def update_qr_code(self):
        ssid = self.input_ssid.text().strip() or "Xiaomi_MiWiFi"
        pwd = self.input_pass.text().strip() or "12345678"
        try:
            pil_img = self.service.generate_wifi_qr(ssid, pwd)
            pil_img = pil_img.convert("RGBA")
            data = pil_img.tobytes("raw", "RGBA")
            qimage = QImage(data, pil_img.size[0], pil_img.size[1], QImage.Format.Format_RGBA8888)
            pixmap = QPixmap.fromImage(qimage)
            self.qr_label.setPixmap(pixmap.scaled(105, 105, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        except Exception as e:
            print("QR error:", e)

    # Driver Status
    def check_driver_async(self):
        def run():
            st = self.service.check_driver_status()
            self.signals.driver_status_ready.emit(st)
        threading.Thread(target=run, daemon=True).start()

    def handle_driver_status(self, st: dict):
        self.driver_status = st
        if st.get("is_working"):
            self.driver_banner.setVisible(False)
            self.lbl_hw_status.setText(f"✅ {st.get('device_name', 'Xiaomi 802.11n')} (Çalışıyor)")
            self.lbl_hw_status.setStyleSheet("color: #00E676; font-size: 11px;")
        elif st.get("has_driver_issue"):
            self.driver_banner.setVisible(True)
            self.lbl_hw_status.setText("⚠️ Sürücü eksik. Yüklemek için tıklayın.")
            self.lbl_hw_status.setStyleSheet("color: #FFB300; font-size: 11px;")
        else:
            self.driver_banner.setVisible(False)

    def on_trigger_driver_install(self):
        try:
            ok, msg = self.service.install_xiaomi_driver()
            if ok:
                QMessageBox.information(self, "Sürücü Kurulumu", msg)
                QTimer.singleShot(4000, self.check_driver_async)
                QTimer.singleShot(4000, self.refresh_adapters_async)
            else:
                QMessageBox.warning(self, "Kurulum", msg)
        except Exception as e:
            QMessageBox.critical(self, "Hata", str(e))


    # Hotspot Actions
    def on_save_hotspot_config(self):
        ssid = self.input_ssid.text().strip()
        pwd = self.input_pass.text().strip()
        if len(pwd) < 8:
            QMessageBox.warning(self, "Geçersiz Şifre", "Wi-Fi şifresi en az 8 karakter olmalıdır.")
            return
        
        self.update_qr_code()
        
        def run():
            self.service.set_hotspot_config(ssid, pwd)
            self.signals.message_box.emit("Başarılı", f"Hotspot ağ adı '{ssid}' ve şifresi kaydedildi.", "info")
            self.check_status_async()
        
        threading.Thread(target=run, daemon=True).start()

    def on_toggle_hotspot(self):
        self.is_hotspot_action_in_progress = True
        self.btn_toggle_hotspot.setEnabled(False)
        self.btn_toggle_hotspot.setText("İşleniyor...")
        
        ssid = self.input_ssid.text().strip()
        pwd = self.input_pass.text().strip()

        def run():
            try:
                if self.is_hotspot_active:
                    res = self.service.stop_hotspot()
                    self.signals.hotspot_action_done.emit(f"STOPPED:{res}")
                else:
                    res = self.service.start_hotspot(ssid, pwd)
                    self.signals.hotspot_action_done.emit(f"STARTED:{res}")
            except Exception as e:
                self.signals.hotspot_action_done.emit(f"STARTED:ERROR:{str(e)}")

        threading.Thread(target=run, daemon=True).start()

    def handle_hotspot_action_done(self, result: str):
        self.is_hotspot_action_in_progress = False
        self.btn_toggle_hotspot.setEnabled(True)
        if "STARTED:ERROR:" in result:
            err_msg = result.split("STARTED:ERROR:", 1)[-1].strip()
            self.show_message("Hotspot Başlatılamadı", err_msg, "warning")
        elif "STOPPED:ERROR:" in result:
            err_msg = result.split("STOPPED:ERROR:", 1)[-1].strip()
            self.show_message("Hotspot Durdurulamadı", err_msg, "warning")
        self.check_status_async()

    def check_status_async(self):
        def run():
            try:
                status = self.service.get_hotspot_status()
                curr_wifi = self.service.get_current_wifi_connection()
                status["curr_wifi"] = curr_wifi
                self.signals.hotspot_status_ready.emit(status)
            except Exception as e:
                print("Status check error:", e)

        threading.Thread(target=run, daemon=True).start()

    def handle_hotspot_status(self, data: dict):
        state = data.get("state", "Off")
        ssid = data.get("ssid", "")
        passphrase = data.get("passphrase", "")

        if ssid and not self.input_ssid.hasFocus():
            self.input_ssid.setText(ssid)
        if passphrase and not self.input_pass.hasFocus():
            self.input_pass.setText(passphrase)

        if state.lower() == "on":
            self.is_hotspot_active = True
            self.hotspot_state_label.setText("Hotspot: YAYINDA")
            self.hotspot_state_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #00E676;")
            if not getattr(self, 'is_hotspot_action_in_progress', False):
                self.btn_toggle_hotspot.setEnabled(True)
                self.btn_toggle_hotspot.setText("🛑 Hotspot'ı Durdur")
                self.btn_toggle_hotspot.setObjectName("dangerBtn")
                self.btn_toggle_hotspot.setStyleSheet("background-color: #C42B1C; font-weight: bold;")
            self.status_badge.setText("● Yayında")
            self.status_badge.setStyleSheet("background-color: #1B2E21; color: #00E676; border: 1px solid #00E676; border-radius: 12px; padding: 4px 12px; font-weight: 600; font-size: 11px;")
        else:
            self.is_hotspot_active = False
            self.hotspot_state_label.setText("Hotspot: KAPALI")
            self.hotspot_state_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #FF5252;")
            if not getattr(self, 'is_hotspot_action_in_progress', False):
                self.btn_toggle_hotspot.setEnabled(True)
                self.btn_toggle_hotspot.setText("🚀 Hotspot'ı Başlat")
                self.btn_toggle_hotspot.setObjectName("")
                self.btn_toggle_hotspot.setStyleSheet("background-color: #FF6900; font-weight: bold;")
            self.status_badge.setText("● Hazır")
            self.status_badge.setStyleSheet("background-color: #2D2D2D; color: #4CC2FF; border: 1px solid #4CC2FF; border-radius: 12px; padding: 4px 12px; font-weight: 600; font-size: 11px;")

        # Update Clients Table
        clients = data.get("clients", [])
        if isinstance(clients, dict):
            clients = [clients]
        elif not isinstance(clients, list):
            clients = []

        self.dev_header.setText(f"Bağlı Cihazlar ({len(clients)})")
        self.table_clients.setRowCount(len(clients))
        for row, cl in enumerate(clients):
            if not isinstance(cl, dict):
                continue
            name_item = QTableWidgetItem(f"📱 {cl.get('name', 'Cihaz')}")
            name_item.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            self.table_clients.setItem(row, 0, name_item)
            self.table_clients.setItem(row, 1, QTableWidgetItem(cl.get("ip", "")))
            self.table_clients.setItem(row, 2, QTableWidgetItem(cl.get("mac", "")))
            st_item = QTableWidgetItem(cl.get("status", "Bağlı"))
            st_item.setForeground(QColor("#00E676"))
            self.table_clients.setItem(row, 3, st_item)

        # Update Current WiFi
        curr_wifi = data.get("curr_wifi", {})
        if curr_wifi.get("connected"):
            self.lbl_curr_wifi.setText(f"Mevcut: {curr_wifi.get('ssid')} (%{curr_wifi.get('signal', 0)})")
            self.lbl_curr_wifi.setStyleSheet("font-weight: bold; color: #00E676;")
        else:
            self.lbl_curr_wifi.setText("Mevcut: Bağlı Değil")
            self.lbl_curr_wifi.setStyleSheet("font-weight: bold; color: #FFFFFF;")

    # WiFi Scan
    def scan_wifi_async(self):
        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("...")

        def run():
            nets = self.service.scan_wifi_networks()
            self.signals.wifi_scan_ready.emit(nets)

        threading.Thread(target=run, daemon=True).start()

    def handle_wifi_scan(self, networks: list):
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("🔍 Tara")
        self.table_wifi.setRowCount(len(networks))

        for row, net in enumerate(networks):
            ssid_item = QTableWidgetItem(f"📶 {net['ssid']}")
            self.table_wifi.setItem(row, 0, ssid_item)

            sig = net['signal']
            sig_color = "#00E676" if sig > 65 else ("#FFB300" if sig > 40 else "#FF5252")
            sig_item = QTableWidgetItem(f"%{sig}")
            sig_item.setForeground(QColor(sig_color))
            self.table_wifi.setItem(row, 1, sig_item)

            auth_item = QTableWidgetItem(net['auth'])
            self.table_wifi.setItem(row, 2, auth_item)

            btn_conn = QPushButton("Bağlan")
            btn_conn.setStyleSheet("padding: 2px 6px; font-size: 10px;")
            btn_conn.clicked.connect(lambda checked, s=net['ssid']: self.prompt_connect_wifi(s))
            self.table_wifi.setCellWidget(row, 3, btn_conn)

    def prompt_connect_wifi(self, ssid: str):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{ssid} Ağına Bağlan")
        dialog.setFixedWidth(320)
        dialog.setStyleSheet("background-color: #252525; color: #FFFFFF;")
        d_layout = QVBoxLayout(dialog)
        d_layout.setSpacing(10)

        d_layout.addWidget(QLabel(f"<b>{ssid}</b> şifresi:"))
        input_p = QLineEdit()
        input_p.setEchoMode(QLineEdit.EchoMode.Password)
        d_layout.addWidget(input_p)

        btn_box = QHBoxLayout()
        btn_ok = QPushButton("Bağlan")
        btn_ok.clicked.connect(dialog.accept)
        btn_cancel = QPushButton("İptal")
        btn_cancel.setObjectName("secondaryBtn")
        btn_cancel.clicked.connect(dialog.reject)
        btn_box.addWidget(btn_cancel)
        btn_box.addWidget(btn_ok)
        d_layout.addLayout(btn_box)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            password = input_p.text().strip()
            def run():
                res = self.service.connect_wifi_network(ssid, password)
                self.signals.wifi_connect_done.emit(res)
            threading.Thread(target=run, daemon=True).start()

    def handle_wifi_connect_done(self, res: str):
        QMessageBox.information(self, "Bağlantı", f"Bağlantı isteği gönderildi.\n{res}")
        self.check_status_async()

    # Traffic
    def update_traffic_async(self):
        def run():
            stats = self.service.get_traffic_stats()
            self.signals.traffic_ready.emit(stats)
        threading.Thread(target=run, daemon=True).start()

    def handle_traffic_ready(self, stats: dict):
        down = stats.get("down_speed_str", "0.0 KB/s")
        up = stats.get("up_speed_str", "0.0 KB/s")
        self.lbl_down_speed.setText(down)
        self.lbl_up_speed.setText(up)
        self.lbl_footer_speed.setText(f"⬇ {down}  •  ⬆ {up}")

    # Adapters
    def refresh_adapters_async(self):
        def run():
            self.service.get_adapters()
            st = self.service.check_driver_status()
            self.signals.driver_status_ready.emit(st)
        threading.Thread(target=run, daemon=True).start()

    def handle_adapters_ready(self, adapters: list):
        pass

    def on_repair_network(self):
        def run():
            ok, msg = self.service.repair_hotspot_network()
            if ok:
                self.signals.message_box.emit("Onarım Tamamlandı", msg, "info")
            else:
                self.signals.message_box.emit("Onarım Hatası", msg, "warning")
        threading.Thread(target=run, daemon=True).start()

    def on_flush_dns(self):
        def run():
            msg = self.service.flush_dns_and_renew()
            self.signals.message_box.emit("Başarılı", msg, "info")
        threading.Thread(target=run, daemon=True).start()

    def on_open_driver_dir(self):
        self.service.open_driver_folder()

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Xiaomi Mi WiFi")
    app.setStyle("Fusion")
    
    window = XiaomiWiFiApp()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
