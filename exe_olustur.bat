@echo off
chcp 65001 > nul
echo =======================================================
echo Xiaomi Mi WiFi Turkce - Standalone EXE Olusturucu
echo =======================================================
echo.
echo PyInstaller ile EXE derleniyor, lutfen bekleyin...
echo.

python -m PyInstaller --noconsole --onefile --clean --name "Xiaomi_MiWiFi_Turkce" --add-data "wifi_service.py;." app_main.py

echo.
echo =======================================================
echo Derleme tamamlandi!
echo EXE dosyaniz 'dist' klasoru icine kaydedildi:
echo %~dp0dist\Xiaomi_MiWiFi_Turkce.exe
echo =======================================================
pause
