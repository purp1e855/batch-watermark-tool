@echo off
chcp 65001 >nul
cd /d "%~dp0"

python -m pip install -r requirements.txt
if errorlevel 1 goto fail

python -m pip install "pyinstaller==6.22.3"
if errorlevel 1 goto fail

python -m PyInstaller --noconfirm --clean --windowed --name "批量水印工具" --distpath "发布" --workpath "build" app.py
if errorlevel 1 goto fail

echo.
echo 打包完成：%~dp0发布\批量水印工具\
pause
exit /b 0

:fail
echo.
echo 执行失败，请检查 Python / 网络 / 依赖安装。
pause
exit /b 1
