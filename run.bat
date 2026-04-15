@echo off
chcp 65001 > nul
echo Starting auction search app...
cd /d "%~dp0"
streamlit run src/app.py --server.port 8501
pause
