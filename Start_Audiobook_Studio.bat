@echo off
title Audiobook Studio
cd /d D:\Audiobook_Pipeline\app
echo Starting Audiobook Studio at http://localhost:8765
start "" http://localhost:8765
C:\Users\paulm\miniconda3\python.exe server.py
pause
