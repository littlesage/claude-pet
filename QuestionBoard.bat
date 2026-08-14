@echo off
rem 세션 질문 보드 서버 실행 + 브라우저 열기
cd /d "%~dp0"
start "" http://127.0.0.1:8620
python question_board.py
