@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0data\server\wuhan-main-roads.json" (
  echo 未找到完整武汉路网文件：data\server\wuhan-main-roads.json
  echo 请先生成服务器路网数据，再启动网站。
  pause
  exit /b 1
)

where py >nul 2>&1
if %errorlevel%==0 goto start_server_py

where python >nul 2>&1
if %errorlevel%==0 goto start_server_python

echo 未检测到 Python，将直接打开网页。
start "" "%~dp0index.html"
pause
exit /b

:start_server_py
start "" "http://localhost:5173/"
py server.py
exit /b

:start_server_python
start "" "http://localhost:5173/"
python server.py
exit /b
