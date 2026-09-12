@echo off
setlocal

py -m pip install --upgrade pip
if errorlevel 1 exit /b 1
py -m pip install -e ".[dev]"
if errorlevel 1 exit /b 1
py -m PyInstaller --noconfirm --clean photo-fit-picker.spec
if errorlevel 1 exit /b 1

echo Build complete: dist\PhotoFitPicker.exe
