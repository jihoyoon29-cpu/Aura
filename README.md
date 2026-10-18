# AI Music Board

프롬프트를 입력하면 AI(Stable Audio 3, Hugging Face Inference Providers 경유)가 음악을 생성해주는
커뮤니티 게시판입니다. 로그인한 사용자만 게시글을 작성할 수 있고, 게시글 안에서 생성된 음원을 재생하며
다른 사용자가 댓글을 남길 수 있습니다.

## 스택

- 백엔드: Python / Flask
- 프론트: HTML / CSS / Vanilla JS (Firebase JS SDK, ES Module)
- 인증: Firebase Authentication (이메일/비밀번호)
- 데이터: Firestore (`posts` 컬렉션 + `posts/{id}/comments` 서브컬렉션)
- 음원 생성: Hugging Face Inference Providers → Stable Audio 3
- 오디오 파일: 로컬 `static/generated/` 폴더에 저장, URL만 Firestore에 기록

## 화면 구성

| 경로 | 설명 |
|---|---|
| `/` | 메인 (게시글 리스트) |
| `/signup` | 회원가입 |
| `/login` | 로그인 |
| `/write` | 게시글 작성 (로그인 필요, AI 음원 생성 버튼 포함) |
| `/orchestra` | 오케스트라 악보 생성 (로그인 필요, GPT→MusicXML→악보) |
| `/post/<id>` | 게시글 상세 (음원 재생 + 댓글 + 오케스트라 악보) |

## 오케스트라 악보 생성 (/orchestra)

분위기 한 줄 + 박자·템포·조표·마디 수·난이도(초/중/고급)를 고르고, 악기를 체크박스로
선택하면 (악기 이름 옆 ▶ 로 1초 소리 미리듣기) OpenAI GPT 가 조건에 맞는 MusicXML 을
생성합니다. 프론트에서 [OpenSheetMusicDisplay](https://opensheetmusicdisplay.org/) 로
총보 + 악기별 악보를 그리고, MusicXML 을 직접 파싱해 soundfont-player 로 합주를
미리듣습니다. 분위기 프롬프트가 있으면 GPT 가 어울리는 악기를 추천해 **굵게** 표시합니다.
생성한 악보는 게시글로 등록할 수 있습니다 (Firestore `posts.musicXml`). 완성된 악보는
MusicXML 또는 **PDF**로 내려받을 수 있습니다 (jsPDF + svg2pdf.js 로 OSMD가 그린 SVG를
총보 1페이지 + 악기별 1페이지씩 변환, 브라우저에서 클라이언트 사이드로 처리 — 서버 왕복 없음).

악보는 **GPT가 MusicXML을 직접 쓰지 않습니다.** GPT는 `C4q D4q E4h | A4w~ | R | %` 같은 압축 텍스트
표기(마디당 몇 토큰)만 쓰고, 서버(`_parse_notation` → `_build_musicxml`)가 이를 MusicXML 로 결정적으로
변환합니다. 그래서 응답 토큰이 XML 대비 수십 배 줄어 생성이 빠르고 긴 곡(최대 100마디)이 가능하며, XML 은
항상 형식이 맞고 모든 마디 길이가 박자표와 정확히 일치합니다 (잘못된 토큰은 버리고 모자란 길이는 쉼표로
채움). 악기 이름·음자리표·MIDI 프로그램·템포 표기도 서버가 직접 넣습니다. 분위기 프롬프트가
베토벤/바흐 등 특정 스타일과 맞으면 `music21` 에 내장된 퍼블릭 도메인 코퍼스(베토벤 현악4중주, 바흐 코랄 등
실제 작곡가 원곡)에서 같은 표기 형식으로 짧은 발췌를 뽑아 작곡 시 참고자료로 함께 넘깁니다.

**분위기(장·단조) 반영**
- 작곡 전에 설명문을 해석하는 호출 1번이 분위기(부정 표현 포함), 장조/단조, 언급한 곡·작곡가의 음악적 특징,
  "이렇게 들리면 안 됨", 어울리는 템포를 뽑아 작곡 프롬프트에 최우선 지시로 넣습니다. 어두운 설명이면 단조로
  작곡합니다. (예전에는 조성이 장조로 고정되고 참고곡도 단어 포함 여부로 골라져 어두운 설명도 밝게 나왔음)
- `Mode` 선택(설명에 맞춤 / 장조 / 단조): 직접 고르면 그 값이 우선입니다. 조표는 장조와 그 관계단조를 모두 포함합니다.
- 참고곡은 카탈로그의 `character`(조성·성격)와 설명을 대조해서 고르고, 맞는 곡이 없으면 붙이지 않습니다
  (단조 곡: 베토벤 Op.18 No.1 2악장·Op.132, 바흐 BWV 102.7).
- 설명이 가리키는 템포가 설정과 25% 이상 다르면 결과 화면에 안내합니다.

**반복/변화 조절 (긴 곡이 같은 마디를 복사하는 문제 대응)**
- 입력칸은 여러 줄(최대 1500자)이라 분위기·구조·악기 역할·시작/끝 방식을 자세히 쓸 수 있습니다.
- `Variation & dynamics` 카드: 반복↔변화 정도(Faithful / Balanced / Highly varied), 셈여림 폭(None~Dramatic),
  구간 형식 선행 설계(Plan), 템포 변경 허용, 박자 변경 허용.
- 표기에 `!mf` `!cresc` (셈여림), `!t96` (템포 변경, 첫 악기 블록에만), `(3/4)` (박자 변경, 모든 악기 블록) 이
  추가돼 서버가 MusicXML(`<dynamics>`, `<sound tempo>`, `<time>`)로 변환합니다. 재생은 셈여림을 실제 음량에,
  템포 변경을 템포 지도에 반영합니다.
- 12마디 이상이면 먼저 짧은 호출로 구간 계획(A–B–A′… 구간별 성격·셈여림·편성)을 세우고 그대로 작곡합니다.
- 생성 후 서버가 "앞에서 이미 나온 마디와 똑같은 마디의 비율"(`repeatedMeasureShare`)을 계산하고, 선택한
  변화 정도보다 반복이 심하면(Balanced 45%, Highly varied 25% 초과, 16마디 이상) 한 번 다시 쓰게 합니다.
- API: `POST /api/orchestra/recommend` (분위기→추천 악기), `POST /api/orchestra/generate` (→MusicXML)
- 환경변수: `.env` 에 `OPENAI_API_KEY`, `OPENAI_MODEL`(기본 `gpt-4o`) 필요
- 마디 수는 최대 100까지 선택 가능 (서버 클램프 120). `_chat_completion()`
  이 모델별 `max_tokens`/`max_completion_tokens`/`temperature` 파라미터 차이와 completion 토큰
  상한(모델이 400 에러로 알려주는 값)을 자동으로 감지해서 재시도하므로, `OPENAI_MODEL` 을 다른
  모델로 바꿔도 코드 수정 없이 동작한다.
- OSMD / soundfont-player 는 CDN(jsDelivr, gleitz soundfonts)에서 로드하므로 인터넷 연결 필요
- `music21` 코퍼스 참고는 현악4중주/코랄 등 실내악 위주라 "실제 오케스트라 전곡"은 아님 (`app.py` 의 `REFERENCE_WORKS`)

## 1. Firebase 프로젝트 준비

1. [Firebase Console](https://console.firebase.google.com/) 에서 새 프로젝트를 만듭니다.
2. **Authentication → Sign-in method** 에서 "이메일/비밀번호" 제공업체를 사용 설정합니다.
3. **Firestore Database** 를 생성합니다 (모드는 자유, 이 프로젝트는 서버(Admin SDK)에서만 Firestore에
   접근하므로 클라이언트 보안 규칙 설정은 필수가 아닙니다).
4. **프로젝트 설정 → 일반 → 내 앱**에서 웹 앱을 추가하고 나오는 설정 값을
   `static/js/firebase-config.js` 의 `firebaseConfig` 에 채워 넣습니다.
5. **프로젝트 설정 → 서비스 계정 → 새 비공개 키 생성**으로 JSON 키 파일을 내려받아
   프로젝트 루트에 `serviceAccountKey.json` 이름으로 저장합니다. (`.gitignore` 에 이미 포함되어
   있으니 커밋되지 않습니다.)

## 2. Hugging Face 설정

1. https://huggingface.co/settings/tokens 에서 토큰을 발급받습니다.
2. Stable Audio 3 모델이 Inference Providers 에서 어떤 모델 슬러그로 제공되는지
   Hugging Face 모델 허브에서 확인한 뒤 `.env` 의 `HF_STABLE_AUDIO_MODEL` 값을 그 슬러그로 맞춰줍니다.
   (모델/제공자 목록은 계속 바뀌므로 배포 전에 반드시 최신 문서를 확인하세요.)

## 3. 환경변수

```bash
cp .env.example .env
# .env 파일을 열어 HF_TOKEN, HF_STABLE_AUDIO_MODEL, FIREBASE_SERVICE_ACCOUNT_PATH 를 채워넣기
```

## 4. 설치 및 실행

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt
python app.py
```

브라우저에서 http://localhost:5000 접속.

## 폴더 구조

```
ai-music-app/
├── app.py                     # Flask 앱 (라우트 + API)
├── requirements.txt
├── .env.example
├── static/
│   ├── css/style.css
│   ├── js/
│   │   ├── firebase-config.js # Firebase 초기화 (직접 값 채우기)
│   │   ├── auth.js            # 로그인 상태 / 로그아웃 / 인증 fetch 래퍼
│   │   ├── main.js            # 메인 게시글 리스트
│   │   ├── login.js / signup.js
│   │   ├── write.js           # 게시글 작성 + AI 음원 생성
│   │   └── detail.js          # 게시글 상세 + 댓글
│   └── generated/             # 생성된 음원 파일이 저장되는 폴더 (로컬 저장)
└── templates/
    ├── base.html, index.html, login.html, signup.html, write.html, detail.html
```

## 동작 흐름

1. 사용자가 이메일/비밀번호로 회원가입·로그인 (Firebase Auth, 클라이언트에서 직접 처리)
2. `/write` 페이지에서 프롬프트 입력 후 "AI로 음원 생성" 클릭
   → 프론트가 Firebase ID 토큰과 함께 `POST /api/generate-audio` 호출
   → 백엔드가 토큰을 검증하고 Hugging Face Inference Providers(Stable Audio 3)로 음원 생성 요청
   → 생성된 오디오를 `static/generated/`에 저장하고 URL 반환
3. 제목/설명과 함께 `POST /api/posts` 호출 → Firestore `posts` 컬렉션에 저장
4. 상세 페이지(`/post/<id>`)에서 오디오 재생 및 댓글 작성 (`POST /api/posts/<id>/comments`, 로그인 필요)

## 참고 / 주의사항

- 이 저장소는 로컬 개발/데모 기준으로 구성되어 있습니다. 실서비스 배포 시에는 로컬 파일 저장 대신
  Cloud Storage 등으로 전환하는 것을 권장합니다.
- Stable Audio 3 의 실제 Inference Providers 라우팅 방식(모델 슬러그, 파라미터 이름)은 Hugging Face
  쪽 변경 가능성이 있으니 `app.py` 의 `generate_audio()` 함수와 `.env` 값을 최신 문서에 맞춰 조정하세요.
