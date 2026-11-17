@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not defined PYPI_INDEX set "PYPI_INDEX=https://mirrors.aliyun.com/pypi/simple/"

python -c "import PySide6, PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo 正在安装构建依赖...
    python -m pip install -r requirements-build.txt -i "%PYPI_INDEX%"
    if errorlevel 1 goto :fail
)

python build_exe.py %*
if errorlevel 1 goto :fail

echo.
echo 分发时请复制整个 VideoPosterWall 目录。
goto :eof

:fail
echo 打包失败，请查看上方输出。
exit /b 1
