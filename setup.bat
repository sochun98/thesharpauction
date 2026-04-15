@echo off
echo ====================================
echo  법원경매 조회 프로그램 설치
echo ====================================

echo.
echo [1/3] Python 패키지 설치 중...
pip install -r requirements.txt

echo.
echo [2/3] Playwright 브라우저 설치 중...
playwright install chromium

echo.
echo [3/3] .env 파일 생성 중...
if not exist .env (
    copy .env.example .env
    echo .env 파일이 생성되었습니다. 카카오 API 키를 입력해주세요.
) else (
    echo .env 파일이 이미 존재합니다.
)

echo.
echo ====================================
echo  설치 완료!
echo  카카오 API 키를 .env 파일에 입력 후
echo  run.bat 을 실행하세요.
echo ====================================
pause
