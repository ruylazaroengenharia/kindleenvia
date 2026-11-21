@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Construindo KindleEnvia.exe ===
echo.

python -m pip install --upgrade pyinstaller -r requirements.txt
if errorlevel 1 ( echo Falha ao instalar as dependencias. & pause & exit /b 1 )

python -m PyInstaller --noconfirm --clean --onefile --windowed --name KindleEnvia ^
  --add-data "vendor\mermaid.min.js;." ^
  --add-data "kindle\servidor.py;." ^
  kindle_envia.py
if errorlevel 1 ( echo Falha ao gerar o executavel. & pause & exit /b 1 )

copy /y "dist\KindleEnvia.exe" "%~dp0KindleEnvia.exe" >nul
echo.
echo === Pronto! O arquivo KindleEnvia.exe esta nesta pasta. ===
pause
