나는 약사, pharmacist이다. 내가 운영하는 약국 상가 건물이 법원 경매 진행중이다. 
내가 있는 상가의 주소가 주어지면, 주위 상가 중에서 최근에 경매가 진행 중이거나, 경매 진행이 완료된 사례를 살펴보고 싶다.
주소 기반으로 경매 기록을 볼 수 있도록 프로그램을 만들려고 한다.
가능한지 알아봐줘.

'Do you want to proceed?" 질문에는 Yes로 자동으로 답하고 싶다.

/btw 카카오맵 대신 네이버 맵으로 하자.

https://api.ncloud-docs.com/docs/ai-naver-mapsgeocoding-geocode
여기까지 찾았는데 어떻게 신청하는지 모르겠다.



  네이버 API 키 발급:
  1. https://console.ncloud.com 접속
  2. AI·NAVER API → Maps → Geocoding 신청
  3. Application 등록 → Client ID 와 Client Secret 복사
  4. .env 파일에 두 값 모두 입력

● 네이버 클라우드 플랫폼 Maps API 신청 방법을 안내해드립니다.                                                                                                   

  ---                                                                                                                                                           
  네이버 Maps Geocoding API 키 발급 순서                                                                                                                                                                                                                                                                                        
  1단계 — 회원가입                                                                                                                                                                                                                                                                                                              
  - https://www.ncloud.com 접속 → 회원가입                                                                                                                        - 결제 수단 등록 필요 (신용카드) — 무료 한도 내 사용 시 과금 없음                                                                                                                                                                                                                                                             
  2단계 — Maps 서비스 신청

  - https://console.ncloud.com 로그인
  - 상단 메뉴: Services → Application Services → Maps
  - "이용 신청하기" 클릭

  3단계 — 애플리케이션 등록

  - Application 이름 입력 (예: auction-search)
  - 서비스 선택에서 체크:
    - Geocoding ← 필수
    - Reverse Geocoding ← 선택 (나중에 유용)
  - Web Service URL: http://localhost (로컬 테스트용)
  - 등록 완료

  4단계 — 키 확인

  - Maps → Application 목록에서 등록한 앱 클릭
  - Client ID 와 Client Secret 복사

  5단계 — .env 파일에 입력

  NAVER_CLIENT_ID=복사한_Client_ID
  NAVER_CLIENT_SECRET=복사한_Client_Secret

  ---

  ▎ 주의: API 엔드포인트가 문서에 따라 두 가지가 있습니다.
  ▎ - maps.apigw.ntruss.com/map-geocode/v2/geocode (신규)
  ▎ - naveropenapi.apigw.ntruss.com/map-geocode/v2/geocode (구)
  ▎
  ▎ 현재 코드는 구 엔드포인트를 쓰고 있는데, 신규 발급 키는 신규 엔드포인트를 써야 할 수 있습니다. 키 발급 후 오류 나면 알려주세요 — 바로 수정하겠습니다. 

.env 파일 완성했다.
그 다음 과정 알려줘.

 다음 단계                                                                                                                                                     
                                                                                                                                                                
  1단계 — 패키지 설치

  터미널(cmd)에서:
  cd C:\coding_auction\thesharpcharm
  pip install -r requirements.txt

  2단계 — Playwright 브라우저 설치

  playwright install chromium

  3단계 — 앱 실행

  streamlit run src/app.py
  또는 run.bat 더블클릭

  브라우저에서 http://localhost:8501 자동으로 열립니다.

  ---
  터미널에서 직접 실행하려면 아래 세 줄을 순서대로 붙여넣으세요:

  cd C:\coding_auction\thesharpcharm && pip install -r requirements.txt && playwright install chromium && streamlit run src/app.py

  설치 완료 후 오류가 나면 메시지 그대로 알려주세요.


브라우저가 열렸다.


경기도 수원시 영통구 광교호수공원로 20
이 주소로 검색하면,
주소 변환 실패: 401 Client Error: Unauthorized for url: https://naveropenapi.apigw.ntruss.com/map-geocode/v2/geocode?query=%EA%B2%BD%EA%B8%B0%EB%8F%84+%EC%88%98%EC%9B%90%EC%8B%9C+%EC%98%81%ED%86%B5%EA%B5%AC+%EA%B4%91%EA%B5%90%ED%98%B8%EC%88%98%EA%B3%B5%EC%9B%90%EB%A1%9C+20

이렇게 실패 메시지가 나온다.

경매 정보 검색 실패:
courtauction.go.kr 접근에 문제가 생겼습니다. 잠시 후 다시 시도하거나, '브라우저 보이기' 옵션을 켜서 확인해 보세요.

● 이제 Streamlit을 재시작해 주세요 (터미널에서 Ctrl+C 후
  run 다시 실행).
                                                           원인: Streamlit은 내부적으로 asyncio 이벤트 루프를
  돌리는데, Windows에서 Playwright의 sync API가 같은 루프
   안에서 subprocess를 만들려 하면 NotImplementedError가
  발생합니다.

  해결: ThreadPoolExecutor로 별도 스레드에서 실행하면, 그
   스레드는 독립적인 이벤트 루프를 가지므로 Playwright가 
  정상 동작합니다.

  단, scraper.py 자체도 WebSquare 사이트를 제대로 긁지   
  못하고 있어서 (잘못된 셀렉터 등) 검색 결과가 빈 채로 올
   수 있습니다. test_scraper.py 실행으로 POST 바디와 응답
   구조를 확인한 뒤 scraper.py를 직접 HTTP 방식으로      
  교체하는 게 최종 목표입니다 — test_scraper.py를 다시   
  실행하면 됩니다:

  python test_scraper.py


log 폴더를 만들고, http://localhost:8501/에서 검색시작 버튼 눌렀을 때 결과를 기록하자.

어떻게 하면 될지 다시 알려줘.

 해야 할 순서

  1단계 — POST 바디 캡처 (scraper.py 수정 전 필수)       

  cd C:\coding_auction\thesharpcharm
  python test_scraper.py

  브라우저가 열리면:
  - 자동으로 경기도 / 수원시 영통구 선택
  - 새 탭(물건상세검색)이 열림
  - 터미널에 "✅ 요청 캡처!" 메시지가 뜰 때까지 기다림   
  (최대 60초)

  성공하면 터미널에 POST 바디 전체와 응답 JSON 구조가    
  출력되고
  captured_post_body.txt, captured_response.json 파일이  
  생깁니다.

  ---
  2단계 — 출력 결과 붙여넣기

  터미널 출력을 여기에 붙여넣으면, scraper.py를 브라우저 
  없이 직접 HTTP 요청 방식으로 교체합니다.

  ---
  3단계 — 앱 실행

  run

  주소 입력 → 검색 시작 → 결과 + 로그 저장 확인


(.venv) C:\coding_auction\thesharpcharm>python test_scraper.py
이것의 결과도 logs 폴더에 기록하자.

  python test_scraper.py                                    
  성공하면 logs/ 폴더에 2개 파일이 생깁니다:             
  - 20250415_153022_post_body.txt — POST 바디 전체
  (1243자)
  - 20250415_153022_response.json — 응답 JSON 전체      


● 이제 앱을 실행해 주세요:                               

  run                                                      
  브라우저에서 http://localhost:8501 → 주소 입력 → 검색  
  시작.

  새 scraper.py 동작 방식:
  1. Playwright로 사이트 접속 → 시도/시군구 선택 → 검색  
  클릭
  2. 새 탭이 열리면 닫아서 POST 발동 유도 (이전 실험에서 
  이 시점에 POST가 발동됨)
  3. POST 바디 + 세션 쿠키 캡처
  4. 이후 페이지네이션은 Python requests로 직접 호출     
  (빠름)

  파싱 필드 매핑 (실제 응답 기준):
  - srnSaNo → 사건번호
  - hjguSido/Sigu/Dong + daepyoLotno + buldNm/List →     
  소재지
  - gamevalAmt → 감정가, minmaePrice → 최저매각가        
  - yuchalCnt → 유찰횟수, maeGiil → 매각기일

"  run                                                      
  브라우저에서 http://localhost:8501 → 주소 입력 → 검색  
  시작."
결과는 경매정보검색실패

  이번 방식의 핵심 변경:                                 
  - Playwright 불필요 — requests.Session()으로 메인
  페이지 GET → JSESSIONID/WMONID 쿠키 자동 획득
  - WMONID가 없을 때만 Playwright를 잠깐(~4초) 사용      
  - POST 바디는 캡처된 실제 데이터 기반 템플릿으로 직접  
  구성
  - 시도/시군구 이름 → 행정구역 코드 변환은 정적 테이블로
   처리 (전국 모든 시군구 포함)

    개선 방법:                       
    - 검색 반경을 2~3km로 늘려보기                       
    - 주소에서 동호수 부분을 제거하고 "경기도 수원시 
    영통구 원천동 548" 까지만 지오코딩하면 성공률이      
    높아집니다 — scraper.py의 _row_to_item에서
    buldList(동호수)를 address 조합에서 빼면 됩니다 


내가 검색한 주소는 "광교호수공원로 20"이다.

(.venv) C:\coding_auction\thesharpcharm>run
Starting auction search app...

  You can now view your Streamlit app in your browser.

  Local URL: http://localhost:8501
  Network URL: http://192.168.219.100:8501

📍 코드: 시도=41, 시군구=117
🌐 세션 초기화 중...
   쿠키: ['WMONID', 'SID', 'cortAuctnLgnMbr', 'JSESSIONID']
   📄 페이지 1 요청 중...
   ✅ 페이지 1: 10건
   총 48건
   📄 페이지 2 요청 중...
   ✅ 페이지 2: 10건
   📄 페이지 3 요청 중...
   ✅ 페이지 3: 10건
   📄 페이지 4 요청 중...
   ✅ 페이지 4: 10건
   📄 페이지 5 요청 중...
   ✅ 페이지 5: 8건
2026-04-15 23:10:22.488 Please replace `use_container_width` with `width`.

`use_container_width` will be removed after 2025-12-31.  

For `use_container_width=True`, use `width='stretch'`. For `use_container_width=False`, use `width='content'`.    

20260415_231022_광교호수공원로_20.csv
20260415_231022_광교호수공원로_20.json


상세보기 클릭하면 표시되는 정보가 없다.

"광교호수공원로 20"에서 반경 1km 거리에 상가 경매도 있어야 한다.
더 찾아볼 수 있는지 확인 부탁해.


20260415_233508_광교호수공원로_20.csv
20260415_233508_광교호수공원로_20.json

개선이 없다

결과 변화가 없다. 상세보기 클릭하면 아무 것도 표시하지 못한다.

20260416_000523_광교호수공원로_20.csv
20260416_000523_광교호수공원로_20.json
검색 결과가 동일하다.
상가는 전혀 표시하지 못하고 있다.

역지오코딩 API를 사용할 수 있는 방법 알려줘.

상가 발견은 전혀 없고, 아파트 1건만 검색된다.


https://github.com/sochun98/thesharpauction.git
여기에 백업하자.

진단: 반경 외 근접 물건 (15건, 반경 1000m~3000m)
이것도 볼수 있어?

여전히 아파트 1개만 검색된다.


2025타경1345
이것이 검색 목록에 표시되어야 한다.

https://www.courtauction.go.kr/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ159M00.xml
경매사건검색, 수원지방법원, 2025, 타경, 1345
검색하면 
소재지: 경기도 수원시 영통구 원천동 605 더샵광교레이크시티, 근린생활시설동-1동 지2층비2-25호
최근입찰결과: 2026.04.14 유찰
내가 운영하는 약국 상가의 현재 상황이다.

이 상가와 인접한 곳의 상가에서 경매 진행중인 상가가 있는지, 과거에 낙찰된 기록을 가진 상가가 있는지 확인하고 싶다.

현재 진행중인 또는 과거 낙찰 완료된 경매 물건을 확인할 수 있는 방법 찾아보자.
공공 api가 있는지도 확인하자.
낙찰 가격, 낙찰되기까지 유찰 횟수, 시작 가격 등등 관련된 정보를 알고 싶다.

인근 상가 경매는 결과에서 볼 수 없다.
확인 부탁해.

상세보기 클릭했을 때, 볼 수 있도록 해보자.
예를 들어, 2025타경1345, 
https://www.courtauction.go.kr/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ159M00.xml
경매사건검색에서 자동으로 사건 번호 입력하고 볼 수 있도록 하고 싶다.

가능한가?

여전히 상세보기가 작동하지 않고 있다.

상세보기가 안되고 있다.
https://www.courtauction.go.kr/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ159M00.xml
경매사건검색에서 자동으로 사건 번호 입력하고 볼 수는 없을까?


사건 번호는 정해졌는데, 아직 경매 시작하지 않는 상가도 포함하고 싶다.


"Playwright로 사건 상세 페이지에서 직접 파싱하는 방식으로 확장할 수 있습니다."
이 방법도 가능하도록 기능에 추가하자.


