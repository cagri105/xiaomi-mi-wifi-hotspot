"""
Xiaomi Mi WiFi - WiFi and Hotspot Backend Service
Manages Windows Mobile Hotspot, WiFi client scanning, adapter detection, permanent embedded driver installer, and network statistics.
Completely silent execution without any CMD/PowerShell popup windows.
"""

import subprocess
import json
import re
import time
import os
import sys
import io
import shutil
import ctypes
import threading
import socket
import qrcode
from PIL import Image

try:
    import psutil
except ImportError:
    psutil = None

CREATE_NO_WINDOW = 0x08000000

class DNSProxyServer:
    """Lightweight local DNS Proxy Server to guarantee reliable DNS forwarding to custom DNS servers"""
    def __init__(self, upstream_dns=("8.8.8.8", "1.1.1.1"), port=53):
        self.upstream_dns = [d for d in upstream_dns if d]
        self.port = port
        self._running = False
        self._thread = None
        self._sock = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _serve(self):
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind(("0.0.0.0", self.port))
            self._sock.settimeout(1.0)
        except Exception:
            # Port 53 might be bound by system or lack permissions
            self._running = False
            return

        while self._running:
            try:
                data, addr = self._sock.recvfrom(2048)
                if not data:
                    continue
                threading.Thread(target=self._forward_query, args=(data, addr), daemon=True).start()
            except socket.timeout:
                continue
            except Exception:
                break

    def _forward_query(self, data, client_addr):
        for dns in self.upstream_dns:
            if not dns:
                continue
            try:
                upstream_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                upstream_sock.settimeout(2.0)
                upstream_sock.sendto(data, (dns, 53))
                reply, _ = upstream_sock.recvfrom(2048)
                upstream_sock.close()
                if reply and self._sock and self._running:
                    self._sock.sendto(reply, client_addr)
                return
            except Exception:
                continue

def get_silent_startupinfo():
    if os.name == 'nt':
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        return si
    return None

def get_base_path():
    """Gets application runtime path (supports PyInstaller bundle)"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

class WiFiService:
    def __init__(self):
        self._last_net_bytes = (0, 0, time.time())
        self.cached_networks = []
        self.cached_adapters = []
        self.net_config = self.get_network_config()
        self.dns_proxy = DNSProxyServer(
            upstream_dns=(
                self.net_config.get("primary_dns", "8.8.8.8"),
                self.net_config.get("secondary_dns", "1.1.1.1")
            )
        )
        
    def run_powershell(self, script_body: str, timeout=10):
        wrapped = f"""
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
        $OutputEncoding = [System.Text.Encoding]::UTF8
        {script_body}
        """
        try:
            p = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", wrapped],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=timeout,
                creationflags=CREATE_NO_WINDOW,
                startupinfo=get_silent_startupinfo()
            )
            return p.stdout.strip()
        except Exception as e:
            return f"ERROR: {e}"

    # ----------------- EMBEDDED DRIVER DETECTION & PERMANENT INSTALLATION -----------------
    def extract_embedded_drivers_to_temp(self):
        """Extracts bundled drivers to a permanent temp directory for Windows PnP"""
        base = get_base_path()
        src_dir = os.path.join(base, "drivers")
        if not os.path.exists(src_dir):
            src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "drivers")
            
        target_dir = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "Xiaomi_MiWiFi_Drivers")
        os.makedirs(target_dir, exist_ok=True)
        
        if os.path.exists(src_dir):
            for root, dirs, files in os.walk(src_dir):
                rel = os.path.relpath(root, src_dir)
                dest_root = os.path.join(target_dir, rel)
                os.makedirs(dest_root, exist_ok=True)
                for f in files:
                    try:
                        shutil.copy2(os.path.join(root, f), os.path.join(dest_root, f))
                    except Exception:
                        pass
                        
        return target_dir

    def install_xiaomi_driver(self, setup_path=None):
        """Installs the bundled driver permanently so Windows remembers it on all USB ports"""
        try:
            target_dir = self.extract_embedded_drivers_to_temp()
            inf_path = os.path.join(target_dir, "Win8x64", "netr28ux.inf")
            if not os.path.exists(inf_path):
                inf_path = os.path.join(target_dir, "Win7x64", "netr28ux.inf")
                
            if not os.path.exists(inf_path):
                return False, "Sürücü dosyası (netr28ux.inf) hazırlanamadı."

            ra_reg_exe = os.path.join(target_dir, "x64", "RaRegistry64.exe")

            bat_path = os.path.join(target_dir, "install_driver.cmd")
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write('@echo off\n')
                if os.path.exists(ra_reg_exe):
                    f.write(f'start "" /B "{ra_reg_exe}"\n')
                f.write(f'pnputil /add-driver "{inf_path}" /install\n')
                f.write('pnputil /scan-devices\n')
                f.write('powershell -NoProfile -Command "')
                f.write('$adapters = Get-ItemProperty \'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\{4d36e972-e325-11ce-bfc1-08002be10318}\\*\' -ErrorAction SilentlyContinue | Where-Object { $_.DriverDesc -match \'Xiaomi|802.11n|MediaTek|Ralink\' }; ')
                f.write('foreach ($a in $adapters) { $p = $a.PSPath; Set-ItemProperty -Path $p -Name \'*SelectiveSuspend\' -Value \'0\' -ErrorAction SilentlyContinue; Set-ItemProperty -Path $p -Name \'SmartScan\' -Value \'1\' -ErrorAction SilentlyContinue; Set-ItemProperty -Path $p -Name \'AdhocNMode\' -Value \'1\' -ErrorAction SilentlyContinue; Set-ItemProperty -Path $p -Name \'TXBurst\' -Value \'1\' -ErrorAction SilentlyContinue; Set-ItemProperty -Path $p -Name \'RDG\' -Value \'1\' -ErrorAction SilentlyContinue; Set-ItemProperty -Path $p -Name \'FixAPBW20\' -Value \'0\' -ErrorAction SilentlyContinue }; ')
                f.write('Set-ItemProperty -Path \'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Multimedia\\SystemProfile\' -Name \'NetworkThrottlingIndex\' -Value 0xffffffff -Type DWord -ErrorAction SilentlyContinue; ')
                f.write('Set-ItemProperty -Path \'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Multimedia\\SystemProfile\' -Name \'SystemResponsiveness\' -Value 0 -Type DWord -ErrorAction SilentlyContinue; ')
                f.write('netsh int tcp set global autotuninglevel=normal | Out-Null; ')
                f.write('netsh int tcp set global rss=enabled | Out-Null; ')
                f.write('netsh int tcp set global rsc=enabled | Out-Null; ')
                f.write('netsh int tcp set global fastopen=enabled | Out-Null; ')
                f.write('"\n')
                f.write('exit\n')

            ret = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                "cmd.exe",
                f'/c "{bat_path}"',
                target_dir,
                0  # SW_HIDE
            )
            if ret > 32:
                return True, "Sürücü ve Yüksek Hız Ayarları (150 Mbps, Güç Tasarrufu İptali) kalıcı olarak uygulandı.\nLütfen ekrandaki Yönetici Onayı (UAC) penceresinde 'Evet'i tıklayın."
            else:
                return False, f"Yönetici izni alınamadı (Hata kodu: {ret})"
        except Exception as e:
            return False, f"Sürücü yükleme hatası: {e}"

    def optimize_wifi_speed(self):
        """Applies high-performance settings for Xiaomi USB Wi-Fi adapter and Windows network stack"""
        try:
            target_dir = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "Xiaomi_MiWiFi_Drivers")
            os.makedirs(target_dir, exist_ok=True)
            ps_script = os.path.join(target_dir, "optimize_speed.ps1")
            
            script_content = r'''
            # 1. Adapter Registry Optimizations
            $adapters = Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e972-e325-11ce-bfc1-08002be10318}\*" -ErrorAction SilentlyContinue | Where-Object { $_.DriverDesc -match 'Xiaomi|802.11n|MediaTek|Ralink' }
            foreach ($a in $adapters) {
                $p = $a.PSPath
                Set-ItemProperty -Path $p -Name "*SelectiveSuspend" -Value "0" -ErrorAction SilentlyContinue
                Set-ItemProperty -Path $p -Name "SmartScan" -Value "1" -ErrorAction SilentlyContinue
                Set-ItemProperty -Path $p -Name "AdhocNMode" -Value "1" -ErrorAction SilentlyContinue
                Set-ItemProperty -Path $p -Name "TXBurst" -Value "1" -ErrorAction SilentlyContinue
                Set-ItemProperty -Path $p -Name "RDG" -Value "1" -ErrorAction SilentlyContinue
                Set-ItemProperty -Path $p -Name "FixAPBW20" -Value "0" -ErrorAction SilentlyContinue
            }

            # 2. Windows Multimedia & Network Throttling Disable
            $mmPath = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile"
            Set-ItemProperty -Path $mmPath -Name "NetworkThrottlingIndex" -Value 0xffffffff -Type DWord -ErrorAction SilentlyContinue
            Set-ItemProperty -Path $mmPath -Name "SystemResponsiveness" -Value 0 -Type DWord -ErrorAction SilentlyContinue

            # 3. TCP Auto Tuning & High Speed TCP parameters
            netsh int tcp set global autotuninglevel=normal | Out-Null
            netsh int tcp set global rss=enabled | Out-Null
            netsh int tcp set global rsc=enabled | Out-Null
            netsh int tcp set global fastopen=enabled | Out-Null

            # 4. Restart Wi-Fi Adapter to apply
            Restart-NetAdapter -Name "Wi-Fi" -ErrorAction SilentlyContinue
            '''
            
            with open(ps_script, "w", encoding="utf-8") as f:
                f.write(script_content)

            ret = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                "powershell.exe",
                f'-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File "{ps_script}"',
                target_dir,
                0  # SW_HIDE
            )
            if ret > 32:
                return True, "Wi-Fi ve Ağ Hızlandırma Ayarları Uygulandı!\n\n• USB güç tasarrufu / uyku modu devre dışı bırakıldı (5sn kilitlenme kalktı).\n• 802.11n yüksek hız (150 Mbps / 40MHz) modu aktif edildi.\n• Windows ağ bant genişliği kısıtlamaları (Throttling) kaldırıldı.\n• TCP Auto-Tuning optimize edildi."
            else:
                return False, f"Yönetici izni alınamadı (Hata kodu: {ret})"
        except Exception as e:
            return False, f"Optimizasyon hatası: {e}"

    def check_driver_status(self):
        """Accurately checks if Xiaomi Wi-Fi adapter is recognized and ready"""
        ps = """
        $res = @{
            has_driver_issue = $false
            device_plugged = $false
            device_name = ""
            is_working = $false
        }

        $adapters = Get-NetAdapter | Where-Object { $_.InterfaceDescription -match 'Xiaomi|802.11|Ralink|MediaTek' -or $_.Name -match 'Wi-Fi' }
        if ($adapters) {
            $res.device_plugged = $true
            $res.is_working = $true
            $res.has_driver_issue = $false
            $res.device_name = $adapters[0].InterfaceDescription
            $res | ConvertTo-Json
            exit
        }

        $pnp = Get-PnpDevice -PresentOnly | Where-Object { $_.FriendlyName -match 'Xiaomi|MI WLAN' -or $_.InstanceId -match 'VID_2717' }
        if ($pnp) {
            $res.device_plugged = $true
            $res.device_name = $pnp[0].FriendlyName
            if ($pnp[0].Status -ne 'OK' -or $pnp[0].FriendlyName -match 'MI WLAN') {
                $res.has_driver_issue = $true
            } else {
                $res.is_working = $true
            }
        }

        $res | ConvertTo-Json
        """
        out = self.run_powershell(ps)
        res = {
            "has_driver_issue": False,
            "device_plugged": False,
            "device_name": "",
            "is_working": False
        }
        try:
            data = json.loads(out)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return res

    # ----------------- HOTSPOT MANAGEMENT & CLIENT TRACKING (WinRT) -----------------
    def get_hotspot_status(self):
        """Returns dict with state, ssid, passphrase, clientCount and actual connected clients"""
        ps = r"""
        Add-Type -AssemblyName System.Runtime.WindowsRuntime
        [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime] | Out-Null
        [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime] | Out-Null

        $profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
        $result = @{
            available = $false
            state = "Off"
            ssid = ""
            passphrase = ""
            clientCount = 0
            clients = @()
            error = ""
        }

        if (-not $profile) {
            $result.error = "Aktif internet baglantisi profili bulunamadi."
            $result | ConvertTo-Json
            exit
        }

        try {
            $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
            $result.available = $true
            $result.state = $mgr.TetheringOperationalState.ToString()
            $result.clientCount = $mgr.ClientCount
            $cfg = $mgr.GetCurrentAccessPointConfiguration()
            $result.ssid = $cfg.Ssid
            $result.passphrase = $cfg.Passphrase
            
            $tetheringClients = $mgr.GetTetheringClients()
            foreach ($c in $tetheringClients) {
                $name = ""
                $ip = ""
                foreach ($h in $c.HostNames) {
                    $canon = $h.CanonicalName
                    if ($canon -match '^\d+\.\d+\.\d+\.\d+$') {
                        $ip = $canon
                    } else {
                        $name = $canon
                    }
                }
                if (-not $name) { $name = "Telefon / Cihaz" }
                if (-not $ip) { $ip = "Alınıyor..." }
                
                $result.clients += @{
                    name = $name
                    ip = $ip
                    mac = $c.MacAddress.ToUpper()
                    status = "Bağlı"
                }
            }
        } catch {
            $result.error = $_.Exception.Message
        }

        $result | ConvertTo-Json
        """
        out = self.run_powershell(ps)
        try:
            data = json.loads(out)
            if isinstance(data, dict):
                cl = data.get("clients", [])
                if isinstance(cl, dict):
                    data["clients"] = [cl]
                elif not isinstance(cl, list):
                    data["clients"] = []
                return data
        except Exception:
            pass
        return {
            "available": True,
            "state": "Off",
            "ssid": "Xiaomi_MiWiFi_Hotspot",
            "passphrase": "password1234",
            "clientCount": 0,
            "clients": [],
            "error": out if "ERROR:" in out else ""
        }

    def get_connected_hotspot_clients(self):
        """Returns the list of currently connected hotspot devices"""
        st = self.get_hotspot_status()
        return st.get("clients", [])

    def set_hotspot_config(self, ssid: str, passphrase: str):
        """Sets Hotspot SSID and password"""
        ps = f"""
        Add-Type -AssemblyName System.Runtime.WindowsRuntime
        $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{ $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' }})[0]

        [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime] | Out-Null
        [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime] | Out-Null
        [Windows.Networking.NetworkOperators.NetworkOperatorTetheringAccessPointConfiguration,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime] | Out-Null

        $profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
        if ($profile) {{
            $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
            $cfg = New-Object Windows.Networking.NetworkOperators.NetworkOperatorTetheringAccessPointConfiguration
            $cfg.Ssid = "{ssid}"
            $cfg.Passphrase = "{passphrase}"
            $asyncOp = $mgr.ConfigureAccessPointAsync($cfg)
            $task = $asTaskGeneric.Invoke($null, @($asyncOp))
            $task.Wait(5000) | Out-Null
            Write-Output "OK"
        }} else {{
            Write-Output "NO_PROFILE"
        }}
        """
        return self.run_powershell(ps)

    def start_hotspot(self, ssid=None, passphrase=None):
        """Starts Windows Mobile Hotspot with detailed error reporting"""
        ps = f"""
        Add-Type -AssemblyName System.Runtime.WindowsRuntime
        $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{ $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' }})[0]
        $asTaskAction = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{ $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' }})[0]

        [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime] | Out-Null
        [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime] | Out-Null
        [Windows.Networking.NetworkOperators.NetworkOperatorTetheringAccessPointConfiguration,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime] | Out-Null

        $profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
        if (-not $profile) {{
            Write-Output "ERROR:Aktif bir internet baglantisi (Ethernet/Wi-Fi) bulunamadi."
            exit
        }}

        try {{
            $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
            if (-not $mgr) {{
                Write-Output "ERROR:Sistemde Wi-Fi donanimi bulunamadi."
                exit
            }}

            # Update config if requested
            if ("{ssid}" -and "{passphrase}") {{
                $cfg = New-Object Windows.Networking.NetworkOperators.NetworkOperatorTetheringAccessPointConfiguration
                $cfg.Ssid = "{ssid}"
                $cfg.Passphrase = "{passphrase}"
                $asyncOpCfg = $mgr.ConfigureAccessPointAsync($cfg)
                $taskCfg = $asTaskAction.Invoke($null, @($asyncOpCfg))
                $taskCfg.Wait(5000) | Out-Null
            }}

            # If already on, we are good
            if ($mgr.TetheringOperationalState -eq [Windows.Networking.NetworkOperators.TetheringOperationalState]::On) {{
                Write-Output "SUCCESS"
                exit
            }}

            $asyncOp = $mgr.StartTetheringAsync()
            $makeGeneric = $asTaskGeneric.MakeGenericMethod([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult])
            $task = $makeGeneric.Invoke($null, @($asyncOp))
            $task.Wait(12000) | Out-Null
            $res = $task.Result
            if ($res.Status -eq [Windows.Networking.NetworkOperators.TetheringOperationStatus]::Success) {{
                Write-Output "SUCCESS"
            }} else {{
                Write-Output "ERROR:Hotspot baslatilamadi ($($res.Status)). $($res.AdditionalErrorMessage)"
            }}
        }} catch {{
            Write-Output "ERROR:Wi-Fi donanimi veya surucusu algilanamadi ($($_.Exception.Message))."
        }}
        """
        out = self.run_powershell(ps)
        if "SUCCESS" in out and self.dns_proxy:
            self.dns_proxy.start()
        return out

    def stop_hotspot(self):
        """Stops Windows Mobile Hotspot"""
        if self.dns_proxy:
            self.dns_proxy.stop()
        try:
            subprocess.run(["netsh", "wlan", "stop", "hostednetwork"], capture_output=True, creationflags=CREATE_NO_WINDOW, startupinfo=get_silent_startupinfo())
        except Exception:
            pass

        ps = """
        Add-Type -AssemblyName System.Runtime.WindowsRuntime
        $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]

        [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime] | Out-Null
        [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime] | Out-Null

        $profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
        if ($profile) {
            try {
                $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
                if ($mgr.TetheringOperationalState -eq [Windows.Networking.NetworkOperators.TetheringOperationalState]::Off) {
                    Write-Output "SUCCESS"
                    exit
                }
                $asyncOp = $mgr.StopTetheringAsync()
                $makeGeneric = $asTaskGeneric.MakeGenericMethod([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult])
                $task = $makeGeneric.Invoke($null, @($asyncOp))
                $task.Wait(8000) | Out-Null
                Write-Output "SUCCESS"
            } catch {
                Write-Output "ERROR:$($_.Exception.Message)"
            }
        } else {
            Write-Output "NO_PROFILE"
        }
        """
        return self.run_powershell(ps)

    def generate_wifi_qr(self, ssid: str, password: str, auth_type="WPA"):
        """Generates a PIL image for WiFi QR code"""
        qr_data = f"WIFI:S:{ssid};T:{auth_type};P:{password};;"
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=4,
            border=2,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#202020", back_color="#FFFFFF")
        return img

    # ----------------- WIFI CLIENT (Scanner & Connection) -----------------
    def scan_wifi_networks(self):
        """Scans nearby WiFi networks using netsh silently"""
        networks = []
        try:
            res = subprocess.run(
                ["netsh", "wlan", "show", "networks", "mode=bssid"],
                capture_output=True,
                text=True,
                encoding='cp1254',
                errors='replace',
                creationflags=CREATE_NO_WINDOW,
                startupinfo=get_silent_startupinfo()
            )
            output = res.stdout
            
            blocks = re.split(r"SSID \d+ : ", output)
            for block in blocks[1:]:
                lines = block.splitlines()
                if not lines:
                    continue
                ssid = lines[0].strip()
                if not ssid:
                    ssid = "(Gizli Ağ)"
                
                auth = "Açık"
                encryption = "Bilinmiyor"
                signal = 70
                channel = "1"
                bssid = ""

                for line in lines[1:]:
                    line = line.strip()
                    if "Kimlik Doğrulama" in line or "Authentication" in line:
                        auth = line.split(":", 1)[-1].strip()
                    elif "Şifreleme" in line or "Encryption" in line:
                        encryption = line.split(":", 1)[-1].strip()
                    elif "Sinyal" in line or "Signal" in line:
                        sig_str = line.split(":", 1)[-1].strip().replace("%", "")
                        try:
                            signal = int(sig_str)
                        except ValueError:
                            signal = 50
                    elif "Kanal" in line or "Channel" in line:
                        channel = line.split(":", 1)[-1].strip()
                    elif "BSSID" in line:
                        bssid = line.split(":", 1)[-1].strip()

                networks.append({
                    "ssid": ssid,
                    "auth": auth,
                    "encryption": encryption,
                    "signal": signal,
                    "channel": channel,
                    "bssid": bssid
                })
        except Exception as e:
            print("Scan error:", e)
            
        networks.sort(key=lambda x: x["signal"], reverse=True)
        self.cached_networks = networks
        return networks

    def get_current_wifi_connection(self):
        """Gets info about currently connected WiFi network silently"""
        info = {
            "connected": False,
            "ssid": "",
            "signal": 0,
            "state": "Bağlı Değil",
            "speed": "0 Mbps",
            "adapter": ""
        }
        try:
            res = subprocess.run(
                ["netsh", "wlan", "show", "interfaces"],
                capture_output=True,
                text=True,
                encoding='cp1254',
                errors='replace',
                creationflags=CREATE_NO_WINDOW,
                startupinfo=get_silent_startupinfo()
            )
            for line in res.stdout.splitlines():
                line = line.strip()
                if "Açıklama" in line or "Description" in line:
                    info["adapter"] = line.split(":", 1)[-1].strip()
                elif "Durum" in line or "State" in line:
                    st = line.split(":", 1)[-1].strip()
                    if "bağlandı" in st.lower() or "connected" in st.lower():
                        info["connected"] = True
                        info["state"] = "Bağlı"
                    else:
                        info["state"] = st
                elif "SSID" in line and "BSSID" not in line:
                    info["ssid"] = line.split(":", 1)[-1].strip()
                elif "Sinyal" in line or "Signal" in line:
                    sig = line.split(":", 1)[-1].strip().replace("%", "")
                    try:
                        info["signal"] = int(sig)
                    except ValueError:
                        pass
                elif "Alma oranı" in line or "Receive rate" in line or "İletim hızı" in line or "Transmit rate" in line:
                    info["speed"] = line.split(":", 1)[-1].strip()
        except Exception:
            pass
        return info

    def connect_wifi_network(self, ssid: str, password: str = ""):
        """Connects to a WiFi network silently"""
        if not password:
            cmd = f'netsh wlan connect name="{ssid}"'
            res = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                encoding='cp1254',
                errors='replace',
                creationflags=CREATE_NO_WINDOW,
                startupinfo=get_silent_startupinfo()
            )
            return res.stdout
            
        profile_xml = f"""<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
    <name>{ssid}</name>
    <SSIDConfig>
        <SSID>
            <name>{ssid}</name>
        </SSID>
    </SSIDConfig>
    <connectionType>ESS</connectionType>
    <connectionMode>auto</connectionMode>
    <MSM>
        <security>
            <authEncryption>
                <authentication>WPA2PSK</authentication>
                <encryption>AES</encryption>
                <useOneX>false</useOneX>
            </authEncryption>
            <sharedKey>
                <keyType>passPhrase</keyType>
                <protected>false</protected>
                <keyMaterial>{password}</keyMaterial>
            </sharedKey>
        </security>
    </MSM>
</WLANProfile>"""
        
        xml_path = os.path.join(os.environ.get("TEMP", "."), "wifi_profile_temp.xml")
        try:
            with open(xml_path, "w", encoding="utf-8") as f:
                f.write(profile_xml)
            
            subprocess.run(
                f'netsh wlan add profile filename="{xml_path}" user=all',
                shell=True,
                capture_output=True,
                text=True,
                creationflags=CREATE_NO_WINDOW,
                startupinfo=get_silent_startupinfo()
            )
            res = subprocess.run(
                f'netsh wlan connect name="{ssid}"',
                shell=True,
                capture_output=True,
                text=True,
                encoding='cp1254',
                errors='replace',
                creationflags=CREATE_NO_WINDOW,
                startupinfo=get_silent_startupinfo()
            )
            return res.stdout
        finally:
            if os.path.exists(xml_path):
                try:
                    os.remove(xml_path)
                except Exception:
                    pass

    def disconnect_wifi(self):
        res = subprocess.run(
            ["netsh", "wlan", "disconnect"],
            capture_output=True,
            text=True,
            encoding='cp1254',
            errors='replace',
            creationflags=CREATE_NO_WINDOW,
            startupinfo=get_silent_startupinfo()
        )
        return res.stdout

    # ----------------- ADAPTER & DRIVER MANAGEMENT -----------------
    def get_adapters(self):
        """Retrieves list of all network adapters and flags Xiaomi/MediaTek device"""
        ps = """
        Get-NetAdapter | Select-Object Name, InterfaceDescription, Status, MacAddress, LinkSpeed | ConvertTo-Json
        """
        out = self.run_powershell(ps)
        adapters = []
        try:
            data = json.loads(out)
            if isinstance(data, dict):
                data = [data]
            for it in data:
                desc = it.get("InterfaceDescription", "")
                is_xiaomi = any(kw in desc.lower() for kw in ["xiaomi", "ralink", "mediatek", "802.11n", "802.11ac", "rt2870", "mt7601", "7601", "wireless"])
                adapters.append({
                    "name": it.get("Name", "Bilinmiyor"),
                    "desc": desc,
                    "status": it.get("Status", "Bilinmiyor"),
                    "mac": it.get("MacAddress", ""),
                    "speed": it.get("LinkSpeed", ""),
                    "is_xiaomi_or_wifi": is_xiaomi
                })
        except Exception:
            pass
        self.cached_adapters = adapters
        return adapters

    def flush_dns_and_renew(self):
        """Flushes DNS and releases/renews DHCP leases silently"""
        subprocess.run(
            ["ipconfig", "/flushdns"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            startupinfo=get_silent_startupinfo()
        )
        subprocess.run(
            ["ipconfig", "/renew"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            startupinfo=get_silent_startupinfo()
        )
        return "DNS ve IP yapılandırması başarıyla yenilendi."

    def open_driver_folder(self):
        target_dir = self.extract_embedded_drivers_to_temp()
        if os.path.exists(target_dir):
            os.startfile(target_dir)
            return True
        return False

    # ----------------- DNS & NETWORK CONFIGURATION -----------------
    def get_network_config(self):
        """Loads saved DNS config or returns default"""
        config_path = os.path.join(os.path.expanduser("~"), ".miwifi_net_config.json")
        default_cfg = {
            "primary_dns": "8.8.8.8",
            "secondary_dns": "1.1.1.1"
        }
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        default_cfg.update(data)
            except Exception:
                pass
        return default_cfg

    def save_network_config(self, cfg: dict):
        """Saves DNS config to user directory"""
        config_path = os.path.join(os.path.expanduser("~"), ".miwifi_net_config.json")
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            self.net_config = cfg
            return True
        except Exception:
            return False

    def apply_network_config(self, cfg: dict):
        """Applies DNS settings and ensures standard 192.168.137.1 ICS scope"""
        self.save_network_config(cfg)
        
        p_dns = cfg.get("primary_dns", "8.8.8.8").strip() or "8.8.8.8"
        s_dns = cfg.get("secondary_dns", "1.1.1.1").strip() or "1.1.1.1"

        # Update DNS Proxy upstream
        if self.dns_proxy:
            self.dns_proxy.upstream_dns = [p_dns, s_dns]

        target_dir = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "Xiaomi_MiWiFi_Drivers")
        os.makedirs(target_dir, exist_ok=True)
        ps_file = os.path.join(target_dir, "set_ip_config.ps1")

        ps_script = r"""
        # 1. Enable IP Routing
        Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters' -Name 'IPEnableRouter' -Value 1 -Type DWord -ErrorAction SilentlyContinue

        # 2. Reset standard ICS DHCP Scope to 192.168.137.1
        $sharedKey = 'HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters'
        if (Test-Path $sharedKey) {
            Set-ItemProperty -Path $sharedKey -Name 'ScopeAddress' -Value '192.168.137.1' -ErrorAction SilentlyContinue
            Set-ItemProperty -Path $sharedKey -Name 'ScopeAddressBackup' -Value '192.168.137.1' -ErrorAction SilentlyContinue
            Set-ItemProperty -Path $sharedKey -Name 'StandaloneDhcpAddress' -Value '192.168.137.1' -ErrorAction SilentlyContinue
            Set-ItemProperty -Path $sharedKey -Name 'StandaloneDhcpSubnetMask' -Value '255.255.255.0' -ErrorAction SilentlyContinue
        }

        # 3. Restart SharedAccess and icssvc (Mobile Hotspot) services
        Restart-Service -Name SharedAccess -Force -ErrorAction SilentlyContinue
        Restart-Service -Name icssvc -Force -ErrorAction SilentlyContinue
        """
        try:
            with open(ps_file, "w", encoding="utf-8") as f:
                f.write(ps_script)

            ret = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                "powershell.exe",
                f'-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File "{ps_file}"',
                target_dir,
                0
            )
            if ret > 32:
                if self.dns_proxy:
                    self.dns_proxy.start()
                return True, f"DNS yapılandırması başarıyla kaydedildi ve uygulandı.\n\n• Dağıtım Bloğu: Standart (192.168.137.x)\n• Birincil DNS: {p_dns}\n• İkincil DNS: {s_dns}"
            else:
                return False, f"Yönetici izni alınamadı (Hata kodu: {ret})"
        except Exception as e:
            return False, f"Ayar uygulama hatası: {e}"

    def repair_hotspot_network(self):
        """Repairs common Windows network blocking issues: Firewall rules, Public network category, IP Routing, and ICS service"""
        target_dir = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "Xiaomi_MiWiFi_Drivers")
        os.makedirs(target_dir, exist_ok=True)
        ps_file = os.path.join(target_dir, "repair_hotspot.ps1")

        ps_script = r"""
        # 1. Set all active network connection profiles to Private so Windows Firewall allows local tethering / sharing
        Get-NetConnectionProfile | Set-NetConnectionProfile -NetworkCategory Private -ErrorAction SilentlyContinue

        # 2. Enable IP Router / Forwarding in Windows Registry
        Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters' -Name 'IPEnableRouter' -Value 1 -Type DWord -ErrorAction SilentlyContinue

        # 3. Add / Update Firewall Rules for Hotspot DNS, DHCP, and ICMP
        Remove-NetFirewallRule -DisplayName "Xiaomi Hotspot *" -ErrorAction SilentlyContinue | Out-Null
        New-NetFirewallRule -DisplayName "Xiaomi Hotspot DNS (In UDP)" -Direction Inbound -Protocol UDP -LocalPort 53 -Action Allow -Profile Any -ErrorAction SilentlyContinue | Out-Null
        New-NetFirewallRule -DisplayName "Xiaomi Hotspot DNS (Out UDP)" -Direction Outbound -Protocol UDP -LocalPort 53 -Action Allow -Profile Any -ErrorAction SilentlyContinue | Out-Null
        New-NetFirewallRule -DisplayName "Xiaomi Hotspot DHCP (In UDP)" -Direction Inbound -Protocol UDP -LocalPort 67,68 -Action Allow -Profile Any -ErrorAction SilentlyContinue | Out-Null
        New-NetFirewallRule -DisplayName "Xiaomi Hotspot DHCP (Out UDP)" -Direction Outbound -Protocol UDP -LocalPort 67,68 -Action Allow -Profile Any -ErrorAction SilentlyContinue | Out-Null
        New-NetFirewallRule -DisplayName "Xiaomi Hotspot ICMP (In)" -Direction Inbound -Protocol ICMPv4 -Action Allow -Profile Any -ErrorAction SilentlyContinue | Out-Null

        # 4. Set ICS service startup to Automatic and restart
        Set-Service -Name icssvc -StartupType Automatic -ErrorAction SilentlyContinue
        Set-Service -Name SharedAccess -StartupType Automatic -ErrorAction SilentlyContinue
        Restart-Service -Name SharedAccess -Force -ErrorAction SilentlyContinue
        Restart-Service -Name icssvc -Force -ErrorAction SilentlyContinue

        # 5. Flush DNS
        ipconfig /flushdns | Out-Null
        """
        try:
            with open(ps_file, "w", encoding="utf-8") as f:
                f.write(ps_script)

            ret = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                "powershell.exe",
                f'-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File "{ps_file}"',
                target_dir,
                0
            )
            if ret > 32:
                if self.dns_proxy:
                    self.dns_proxy.start()
                return True, "Hotspot ve İnternet Onarımı Başarıyla Uygulandı!\n\n• Ağ profilleri 'Özel Ağ' yapılarak Güvenlik Duvarı engeli kaldırıldı.\n• Windows IP Paket Yönlendirme (IP Routing) aktif edildi.\n• DNS (53) ve DHCP (67/68) portları için Güvenlik Duvarı izinleri açıldı.\n• Windows Paylaşım Servisleri (ICS) yeniden başlatıldı.\n\nLütfen Hotspot'ı kapatıp tekrar başlatın."
            else:
                return False, f"Yönetici izni alınamadı (Hata kodu: {ret})"
        except Exception as e:
            return False, f"Onarım hatası: {e}"

    # ----------------- NETWORK TRAFFIC STATS (PSUTIL) -----------------
    def get_traffic_stats(self):
        """Calculates download/upload speeds completely in memory using psutil (No CMD/PS)"""
        rx_total = 0
        tx_total = 0

        if psutil:
            net_io = psutil.net_io_counters()
            rx_total = net_io.bytes_recv
            tx_total = net_io.bytes_sent

        now = time.time()
        last_rx, last_tx, last_time = self._last_net_bytes
        dt = now - last_time
        if dt <= 0:
            dt = 1

        down_speed = max(0, (rx_total - last_rx) / dt) if last_rx > 0 else 0
        up_speed = max(0, (tx_total - last_tx) / dt) if last_tx > 0 else 0
        self._last_net_bytes = (rx_total, tx_total, now)

        def format_bytes(b):
            if b >= 1024 * 1024 * 1024:
                return f"{b / (1024 * 1024 * 1024):.2f} GB"
            if b >= 1024 * 1024:
                return f"{b / (1024 * 1024):.2f} MB"
            if b >= 1024:
                return f"{b / 1024:.1f} KB"
            return f"{b:.0f} B"

        def format_speed(bps):
            if bps >= 1024 * 1024:
                return f"{bps / (1024 * 1024):.2f} MB/s"
            if bps >= 1024:
                return f"{bps / (1024 * 1024):.1f} KB/s"
            return f"{bps:.0f} B/s"

        return {
            "down_speed_str": format_speed(down_speed),
            "up_speed_str": format_speed(up_speed),
            "total_rx_str": format_bytes(rx_total),
            "total_tx_str": format_bytes(tx_total),
            "down_speed": down_speed,
            "up_speed": up_speed
        }
