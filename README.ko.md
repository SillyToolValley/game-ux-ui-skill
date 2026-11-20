# game-ux-ui-skill

![Version](https://img.shields.io/badge/version-0.5.0-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Core deps](https://img.shields.io/badge/core%20dependencies-0-brightgreen)

[English](README.md) · [中文](README.zh.md) · **한국어** · [日本語](README.ja.md)

AI 코딩 에이전트(Claude Code 등 SKILL.md 호환 에이전트)용 게임 UX/UI 디자인 스킬과, 그 루프를 정직하게 유지해 주는 작은 CLI입니다. 이전 이름은 *Game-UI-Reference-Cli* 입니다.

출시된 게임의 화면 **한 장**을 앵커로 고르고, 꼼꼼히 해부한 뒤, 실제 화면을 고해상도로 바로 만들고, 결과 스크린샷을 앵커 옆에 놓고 차이를 줄입니다. 최대 세 번 반복합니다.

## 왜 앵커 우선인가

이전 버전은 레퍼런스를 여러 장 모아 JSON 화면 계약서와 승인 게이트로 컴파일하고 회색 와이어프레임을 그렸습니다. 결과물은 그럴듯했지만, 실제로는 잘 만든 출시작 스크린샷 한 장을 프론티어 모델에 그대로 주는 쪽이 더 좋은 화면을 냈습니다.

- 출시된 화면은 서로 맞물려 조율된 수백 개의 결정입니다. 여러 레퍼런스를 섞거나 그리기 전에 계약서로 추상화하면 그 조율이 사라지고 장르 평균으로 회귀합니다.
- 모델은 눈에 보이는 것을 따라갑니다. 구체적인 이미지 한 장은 품질 기준이 되지만, 열두 장에 대한 설명은 그렇지 못합니다.
- 첫 렌더 이전의 명세는 효과가 가장 작은 곳에 노력을 씁니다. 잘 작동하는 범용 UI 스킬들은 첫 렌더 이후, 즉 결과를 보고 비교하고 고치는 데 무게를 둡니다.

그래서 v0.5는 단일 앵커를 기본 경로로 삼고, 계약 파이프라인은 선택적인 인계 단계로 내렸습니다.

## 앵커 루프

```bash
# 1. 이 화면의 앵커가 될 출시작 화면 한 장을 등록
ui-ref anchor add captures/reward-screen.png --screen level-up \
  --game "<게임 제목>" --source-url "<출처>"

# 2. ui_anchor/level-up/ANATOMY.md 를 이미지에서 직접 채움:
#    측정한 비율, 글자 크기, 색 역할, 잘 작동하는 이유, 유지/변경/제외

# 3. 실제 화면을 만들고(HTML 또는 엔진) 스크린샷을 라운드로 저장
ui-ref shot build/level-up.html --screen level-up
#    엔진 빌드라면 직접 캡처한 이미지를 사용
ui-ref compare captures/unity-level-up.png --screen level-up

# 4. ui_anchor/level-up/rounds/01/compare.html 을 열고 critique.md 를 채운 뒤 상위 3개 차이를 수정

# 5. 하한선 점검: 글자 크기, 대비, 세이프 에어리어, 잘림, 초기 포커스
ui-ref audit build/level-up.html --platform tv
```

| 명령 | 하는 일 | 필요 조건 |
| --- | --- | --- |
| `ui-ref anchor add` | 화면당 히어로 앵커 한 장을 출처·해시·크기·추출 팔레트와 함께 저장하고 `ANATOMY.md` 템플릿을 생성. 두 번째 히어로는 거부. 서포트는 최대 2장, 각각 `--borrow` 로 가져올 것을 명시. | 표준 라이브러리 (팔레트는 브라우저 extra) |
| `ui-ref anchor show` | 앵커, 해부 문서 작성 진행도, 라운드 수를 표시. | 표준 라이브러리 |
| `ui-ref shot` | HTML 파일이나 URL을 앵커 크기로 캡처하고 비교 라운드를 시작. | 브라우저 extra |
| `ui-ref compare` | 나란히 보기, 스퀸트(블러), 명도(그레이스케일), 세이프 에어리어·삼분할 가이드, 오버레이, 플리커가 있는 비교 시트와 9개 관점의 크리틱 템플릿 생성. 엔진 캡처 등 어떤 스크린샷이든 사용 가능. | 표준 라이브러리 |
| `ui-ref audit` | 플랫폼 프리셋(`tv`, `desktop`, `handheld`, `mobile`)별 결정론적 하한선 검사. 평가하지 못한 항목을 명시하고, 실패 시 0이 아닌 코드로 종료. | 브라우저 extra |

`audit` 은 하한선만 지킵니다. 화면이 좋은지는 `compare` 와 눈으로 판단합니다.

## 스킬

[`.claude/skills/game-ux-ui-design/`](.claude/skills/game-ux-ui-design/) 가 에이전트용 절반입니다. 프로젝트의 스킬 디렉터리에 복사해 쓰세요. `SKILL.md` 는 짧은 라우터이고 세부 내용은 필요할 때 로드됩니다(스킬 본문은 영어).

| 파일 | 내용 |
| --- | --- |
| `references/anchor-workflow.md` | 히어로 선정, 해부, 번역(구조는 유지, 정체성은 변경), 작업 예시 |
| `references/finding-anchors.md` | 앵커를 어디서 구하고 어떻게 캡처하는지, 갤러리 사이트의 이용 조건 |
| `references/game-ui-tells.md` | 모델이 만든 게임 UI가 수렴하는 패턴과 출시작의 대안 |
| `references/platform-numbers.md` | 글자 크기·대비·세이프 에어리어·터치·현지화 하한선과 출처, 검증 상태 |
| `references/feel-and-states.md` | 타이밍 시작값, 포커스/내비게이션 규칙, 레이아웃을 깨는 상태들 |
| `references/spec-pipeline.md` | 선택 사항: 계약서·와이어프레임·프로토타입·엔진 인계 워크플로 |

### 레퍼런스 사이트에 대해

갤러리 사이트는 어떤 게임이 그 화면을 가장 잘 만들었는지 **찾는 용도**로 쓰고, 화면은 직접 캡처하세요. Game UI Database의 robots.txt(2026년 11월 확인)는 AI 에이전트와 AI 학습 크롤러를 전면 차단하고 콘텐츠를 `ai-train=no, use=reference` 로 표시합니다. 그래서 `ui-ref collect` 는 해당 사이트 URL을 거부하며 기존 사이트 프리셋도 제거했습니다. 어떤 사이트든 수집 전에 현재 약관과 robots 규칙을 확인하세요.

## 다른 스킬에서 배운 것

널리 쓰이는 범용 UI 스킬과 게임 전용 스킬을 검토한 뒤 재설계했습니다.

- **구체적인 레퍼런스 하나를 기준으로 삼기** — DESIGN.md 관례 (Google `design.md`, `VoltAgent/awesome-design-md`)
- **수렴 기본값에 이름 붙이기, 짧은 사전 계획, 과감함은 한 곳에만, 렌더 결과를 직접 보기** — Anthropic `frontend-design`
- **좁은 명령, 디자인 판단과 분리된 결정론적 검사, 라운드 상한, 작성자가 아닌 리뷰어의 크리틱** — `pbakaus/impeccable`, `Leonxlnx/taste-skill`
- **얇은 라우터와 온디맨드 레퍼런스, "평가 안 함"을 솔직히 밝히는 판정** — `Donchitos/Claude-Code-Game-Studios`, `gamedev-skills/awesome-gamedev-agent-skills`
- **행마다 출처와 검증 상태가 붙은 수치** — `fcsouza/agent-skills`

검토한 스킬 중 첫 렌더 이전에 계약서·와이어프레임 컴파일 단계를 두는 것은 없었습니다.

## 선택 사항: 스펙·인계 파이프라인

팀에 문서화된 사양, 승인 이력, 클릭 가능한 플로 프로토타입, 엔진 스캐폴드가 필요하면 v0.4 파이프라인을 그대로 쓸 수 있습니다. 화면이 만들어진 **뒤에** 실행하세요. 아래 내용은 이 파이프라인에 대한 설명입니다.

## GRENADE! — 실제 프로젝트 쇼케이스

아래 콘셉트 세트는 개발 중인 Unity 게임 **GRENADE!**의 UX/UI 사양서를 만들면서 `ui-ref`의 정본 계약 파이프라인과 동반 워크플로로 확정한 최종본입니다. 같은 작업에서 핵심 화면 10개, 재사용 컴포넌트 8개, 사용자 흐름 24개를 구조화·검증하고, 결정론적 와이어프레임과 클릭 가능한 상태 프로토타입, Unity uGUI 인계 데이터를 생성했습니다.

| 아트 디렉션 키프레임 | 클럽 룸 허브 |
| :---: | :---: |
| [![밝은 옥상 캐치 경기장과 따뜻한 부실을 담은 GRENADE 아트 디렉션 키프레임](docs/showcase/grenade/01-art-direction-keyframe.png)](docs/showcase/grenade/01-art-direction-keyframe.png) | [![가장 가까운 미션 마커 하나만 확장한 GRENADE 클럽 룸 허브 콘셉트](docs/showcase/grenade/02-club-room-hub.png)](docs/showcase/grenade/02-club-room-hub.png) |
| **4인 경기 HUD** | **결과·재경기 화면** |
| [![4인 상태와 경기 페이즈를 보여 주는 GRENADE 경기 HUD 콘셉트](docs/showcase/grenade/03-match-hud.png)](docs/showcase/grenade/03-match-hud.png) | [![리플레이와 재경기 및 방 복귀 행동을 담은 GRENADE 결과 화면](docs/showcase/grenade/04-result-rewards.png)](docs/showcase/grenade/04-result-rewards.png) |

> 이 이미지는 아트 방향, 정보 위계, 구도를 전달하기 위한 것입니다. 이미지 속 문구·수치·재화 값은 예시이며, 구현의 정본은 검토된 `ui_design` 계약입니다.

근거 기반 게임 UX/UI 리서치 및 사양 컴파일러입니다. `ui-ref`는 레퍼런스 근거를 수집·인덱싱하고, 검토된 결정을 버전 관리 가능한 화면/컴포넌트 계약으로 만들며, 추적성과 생명주기를 검증합니다. 같은 원본에서 결정론적 와이어프레임, 읽기 쉬운 사양서, 클릭 가능한 프로토타입, 엔진 인계용 스캐폴드를 생성합니다.

핵심 워크플로는 외부 의존성이 없습니다. JavaScript 렌더링 레퍼런스 사이트에는 Playwright를 선택적으로 사용하고, 영상에서 프레임을 추출할 때만 FFmpeg가 필요합니다.

> 이 도구는 AI의 추측을 승인된 디자인으로 바꾸지 않습니다. 역설계 결과는 항상 `draft`로 가져오며, 최종 승인은 이름이 기록된 사람 검토자가 명시적으로 확인해야 합니다.

## v0.4.0 한눈에 보기

- **레퍼런스 근거:** 로컬 스크린샷을 인덱싱하거나 명시적으로 나열한 공개 페이지만 예의 있게 수집합니다. 각 항목은 출처 경로/URL과 해시 가능한 이력을 유지합니다.
- **정본 계약:** 프로젝트, 토큰, 흐름, 레퍼런스, 결정, 승인, 화면, 재사용 컴포넌트를 버전이 있는 JSON으로 관리합니다.
- **품질 게이트:** ID, 레퍼런스, 바인딩, 인터랙션, 상태, 접근성, 입력 동등성, 수용 기준, 흐름, 승인 최신성을 검증합니다.
- **AI 친화적 와이어프레임:** 작은 `.uiwire` DSL을 작성하고 그래픽 의존성 없이 결정론적 주석 SVG를 렌더링합니다.
- **단일 원본 빌드:** 계약을 엔진 중립 Design IR, Markdown, HTML, 렌더링된 와이어프레임으로 컴파일합니다.
- **클릭 검토:** 화면 이동, 시나리오, 키보드 포커스, 게임패드 폴링이 있는 정적 프로토타입을 생성합니다.
- **엔진 인계:** Unity UI Toolkit, Unity uGUI, Godot, Cocos용 명시적 스캐폴드와 기능·해시 manifest를 내보냅니다.
- **근거 한정 역설계:** 어떤 멀티모달 모델에도 전달할 수 있는 스크린샷/영상 패킷을 만들고, 그 주장을 검증해 초안으로만 가져옵니다.

## 5분 워크플로

게임 프로젝트 루트에서 다음 명령을 실행합니다. `--project-root`, `--design-root` 같은 전역 옵션은 명령 앞에 둡니다.

```bash
# 1. 가벼운 리서치 작업공간을 만든다.
ui-ref init --project-name "My Game"

# 2. references/ui/<collection>/<category>/ 아래에 스크린샷을 넣고 인덱싱한다.
ui-ref scan-local

# 3. ui_design/을 만든다. 현재 로컬 manifest는 자동으로 가져온다.
ui-ref spec init --project-name "My Game" --platform pc --locale ko

# 4. 화면 초안과 시작용 와이어프레임을 만든다.
ui-ref spec add-screen "Main Menu" --id main-menu --wireframe

# ui_design/screens/main-menu.json과 ui_design/wireframes/main-menu.uiwire를 편집한다.
ui-ref spec validate --strict

# 5. IR + Markdown/HTML + SVG 와이어프레임을 컴파일한다.
ui-ref spec build

# 6. 클릭 가능한 정적 프로토타입을 만든다.
ui-ref prototype build

# 7. 엔진 인계용 스캐폴드를 생성한다.
ui-ref export unity-uitoolkit
```

브라우저에서 `ui_design/build/design-spec.html`과 `ui_design/build/prototype/index.html`을 엽니다. 생성 명령은 비어 있지 않은 사용자 지정 출력 폴더를 `--force` 없이 교체하지 않습니다. 의도적으로 새로 만들 때만 `--force`를 사용하세요.

나중에 레퍼런스가 바뀌면 다음을 실행합니다.

```bash
ui-ref scan-local
ui-ref spec import-references
ui-ref spec check
```

기존 레퍼런스 ID와 사람이 남긴 메모는 보존되고, 사라진 원본 파일은 조용히 삭제되지 않고 누락 상태로 표시됩니다.

## 정본 원본과 생성 결과물

`ui_design/`을 디자인의 소스 코드로 취급하세요.

| 경로 | 역할 | 커밋? |
| --- | --- | --- |
| `ui_design/project.json` | 프로젝트 메타데이터, 경로, 품질 게이트 | 예 |
| `ui_design/tokens.json`, `flows.json` | 공용 디자인 토큰과 내비게이션 흐름 | 예 |
| `ui_design/references.json` | 근거 카탈로그와 출처 권리/메모 | 예 |
| `ui_design/decisions.json`, `approvals.json` | 결정 및 해시 결속 검토 원장 | 예 |
| `ui_design/screens/*.json` | 정본 화면 계약 | 예 |
| `ui_design/components/*.json` | 정본 재사용 컴포넌트 계약 | 예 |
| `ui_design/wireframes/*.uiwire` | 정본 텍스트 와이어프레임 | 예 |
| `ui_design/schemas/` | 작업공간의 계약 스키마 | 예 |
| `ui_design/build/` | 생성된 IR, 리포트, 문서, SVG, 프로토타입, export | 아니요, 다시 빌드 |
| `ui_design/analysis/` | 임시 프레임, 패킷, 프롬프트, contact sheet | 아니요, 검토한 결과만 정본 계약으로 가져오기 |

저장소의 `.gitignore`는 `ui_design/build/`와 `ui_design/analysis/`만 무시합니다. 정본 디자인 파일은 **무시하지 않습니다**.

`ui-ref spec check`는 계약 검증, 승인 검사, 와이어프레임 lint, 생성 결과물 drift 탐지를 함께 수행합니다. 생성된 HTML, SVG, 엔진 파일, Design IR이 아니라 정본 JSON/`.uiwire`를 편집하세요.

## 생명주기와 승인 안전장치

화면과 컴포넌트에는 명시적 생명주기가 있습니다.

```text
draft → reviewed → approved → deprecated
  ↑        │          │          │
  └────────┴──────────┴──────────┘  (수정이 필요하면 draft로 복귀)
```

승격은 단순 문자열 변경이 아니라 품질 게이트를 통과해야 합니다.

```bash
ui-ref spec promote screen main-menu \
  --to reviewed --by "UX reviewer" --note "상태, 입력, 수용 기준 검토 완료"

ui-ref spec promote screen main-menu \
  --to approved --by "Design lead" --note "구현용으로 승인" \
  --human-confirmed
```

- `reviewed`와 `approved`는 검토 등급의 완전성 검사를 통과해야 합니다.
- 최종 `approved`에는 `--human-confirmed`가 필요합니다. AI나 import가 최종 승인을 부여할 수 없습니다.
- 승인 원장은 산출물과 의존성의 해시를 모두 저장합니다. 토큰, 흐름, 레퍼런스, 컴포넌트를 바꾸면 승인이 오래된 상태가 되고, 다시 검토할 때까지 검증이 실패합니다.
- 검증은 로컬 근거의 존재 여부와 SHA-256, 컴포넌트 참조, `project.json`에서 켠 모든 품질 게이트를 다시 확인합니다. 생성/import의 `--force`는 한 번도 검토되지 않은 초안만 교체할 수 있습니다.
- `ui-ref spec trace screen main-menu`은 근거, 바인딩, 인터랙션, 승인, 의존성 추적성을 보여줍니다.
- `ui-ref prototype build --release`와 `ui-ref export <engine> --release`는 미승인 또는 유효하지 않은 릴리스 입력을 거부합니다.

승인 플래그는 실제 검토를 대신하지 않습니다. 이름이 기록된 사람이 그 정확한 리비전을 확인한 뒤에만 `--human-confirmed`를 사용하세요.

## 스크린샷과 영상 역설계

분석 워크플로는 provider 중립이며, 자체적으로 미디어를 업로드하거나 모델을 호출하지 **않습니다**.

```bash
# 스크린샷, 폴더 또는 혼합 입력
ui-ref analyze media ./captures/menu.png ./captures/hud/

# 영상 프레임 추출에는 PATH의 ffmpeg가 필요하다.
ui-ref analyze media ./captures/gameplay.mp4 --interval 2 --frame-limit 120
```

`ui_design/analysis/<timestamp>/` 실행 폴더에는 다음이 생깁니다.

- `analysis-packet.json` — 근거 ID, 경로, SHA-256 해시, 크기, 타임스탬프
- `analysis-prompt.md` — 근거 규칙과 필수 결과 형태
- `analysis-result.schema.json` — 결과 계약
- `contact-sheet.html` — 로컬 검토 시트
- 영상을 입력했다면 추출된 프레임

정확히 같은 파일/프레임은 SHA-256으로 제거합니다. 선택한 멀티모달 provider에 패킷, 프롬프트, 인용 이미지를 전달하고 JSON 응답을 저장한 다음 가져옵니다.

```bash
ui-ref analyze import result.json \
  --packet ui_design/analysis/<timestamp>/analysis-packet.json
```

import는 근거 ID, `observed` / `inferred` / `unknown` 분류, 신뢰도 값을 검증합니다. provider/model/prompt 이력을 기록하고 **초안 전용** 화면 계약을 생성하거나 갱신합니다. 정확한 패킷과 근거 해시는 충돌 방지 레퍼런스 ID에 결속되며, 레퍼런스·계약·와이어프레임은 모두 함께 반영되거나 전혀 반영되지 않습니다. `--force`를 써도 검토·승인·폐기 상태이거나 검토 이력이 있는 초안은 그대로 보존합니다. 일시 정지 규칙, 최초 포커스, 정식 이벤트, 실패 처리처럼 보이지 않는 런타임 동작은 다른 근거가 입증하지 않는 한 `unknown`으로 남겨야 합니다.

## 와이어프레임과 빌드 결과물

한 줄 기반 `.uiwire` 원본을 만들고, 검사하고, 렌더링합니다.

```bash
ui-ref wireframe new main-menu
ui-ref wireframe lint ui_design/wireframes/main-menu.uiwire
ui-ref wireframe render ui_design/wireframes/main-menu.uiwire
```

원본은 버전과 canvas로 시작하고 안정적인 요소 ID와 key/value 기하 정보를 이어서 적습니다. SVG 출력 전에 label과 callout을 이스케이프합니다.

```text
uiwire 1
canvas 1920 1080
button A1 x=720 y=420 w=480 h=96 label="Start"
callout A1 side=right text="Primary action"
```

`ui-ref spec compile`은 엔진 중립 `design.ir.json`만 작성합니다. `ui-ref spec build`는 여기에 `design-spec.md`, 읽기 쉬운 `design-spec.html`, 주석 SVG 와이어프레임, 원본/출력 해시가 담긴 `build-manifest.json`을 추가합니다.

## 프로토타입과 엔진 인계

```bash
ui-ref prototype build
ui-ref export unity-uitoolkit
ui-ref export unity-ugui
ui-ref export godot
ui-ref export cocos
```

`--screen <id>`로 화면 하나만 내보내고, `--release`로 현재 사람 승인을 필수화할 수 있습니다. 작성된 `flows.json` 단계는 프로토타입 시작 화면과 이동을 구동하며, 같은 동작의 충돌하는 목적지는 검증 오류가 됩니다. 각 엔진 폴더에는 `engine-ir.json`, `capability-report.json`, `export-manifest.json`이 들어가며, 내보내기 때마다 이전 생성 세트를 원자적으로 교체하므로 제거한 화면이 남지 않습니다.

이 결과물은 **구현 인계용 스캐폴드이지, 프로덕션 준비가 끝난 엔진 프로젝트가 아닙니다**.

| 대상 | 생성되는 것 | 수동/프로젝트별 작업 |
| --- | --- | --- |
| Unity UI Toolkit | 화면별 UXML, `tokens.uss`, 바인딩/이벤트 JSON | 런타임 바인딩, 프로젝트 에셋, 반응형 보정, 오디오/햅틱 |
| Unity uGUI | RectTransform/컴포넌트 인계 JSON | Unity 측 importer와 실제 prefab 직렬화 |
| Godot | 화면별 `Control` `.tscn`, 바인딩/이벤트 JSON | Theme 리소스, 에셋, signal, GDScript |
| Cocos | 노드/컴포넌트/UITransform 인계 JSON | 버전별 prefab 직렬화와 에디터 adapter |

항상 `capability-report.json`을 읽으세요. 계약 데이터가 보존되는 범위와 수동/손실 작업의 경계를 명시합니다.

## 설치와 테스트

```bash
git clone https://github.com/SillyToolValley/game-ux-ui-skill
cd game-ux-ui-skill
python -m pip install -e .
ui-ref --version
```

핵심 명령은 Python 3.10+ 표준 라이브러리만 사용합니다. JavaScript 렌더링 레퍼런스 사이트를 사용하려면 다음을 설치합니다.

```bash
python -m pip install -e ".[browser]"
playwright install chromium
```

영상 분석에는 FFmpeg를 별도로 설치하고 `ffmpeg`가 `PATH`에 있어야 합니다. 스크린샷 분석에는 필요하지 않습니다.

표준 라이브러리로 회귀 테스트를 실행합니다.

```bash
python -m unittest discover -s tests -v
```

## 레퍼런스 수집(기존 워크플로, 계속 지원)

기존 `init`, `scan-local`, `collect` 워크플로는 그대로 호환됩니다. 수집은 의도적으로 보수적입니다.

- 로컬 레퍼런스를 먼저 인덱싱합니다.
- 사용자가 **명시적으로 나열한** 외부 URL만 가져오며 크롤링하지 않습니다.
- 요청하지 않으면 에셋을 다운로드하지 않습니다.
- 요청 간 지연, 실행당 페이지 제한, `robots.txt` 검사, 공개 네트워크 URL 검사, 응답 크기 제한을 내장합니다.

로그인이 필요한 갤러리는 범위 밖입니다. 이 도구는 개인 리서치 보조 도구이지 범용 스크래퍼나 타인의 에셋을 재배포하는 수단이 아닙니다. 각 사이트의 약관, 저작권, `robots.txt`를 지키세요.

### 로컬 레퍼런스 인덱싱

파일을 `references/ui/<collection>/<category>/` 아래에 놓고 실행합니다.

```bash
ui-ref scan-local
```

PNG/GIF/JPEG/WebP 바이트에서 이미지 크기를 읽고, 폴더 경로에서 거친 태그를 추론한 뒤 다음을 작성합니다.

```text
ui_research/manifests/local_ui_refs_manifest.json
ui_research/manifests/local_ui_refs_manifest.md
```

### 명시적으로 나열한 페이지 수집

`ui_research/urls.txt`에 한 줄에 URL 하나를 넣거나 `--url`을 반복합니다.

```bash
# JS 렌더링 사이트는 선택적 브라우저 경로를 사용한다.
ui-ref collect --browser

# 소수의 이미지를 다운로드하고 지연 로딩 콘텐츠를 위해 스크롤한다.
ui-ref collect --browser --scroll 6 \
  --download-gallery-assets --download-asset-limit 2

# 알 수 없는 사이트의 추출 방식을 강제한다.
ui-ref collect --browser --mode images
ui-ref collect --browser --gallery-class "thumb-card"
```

실행할 때마다 `ui_research/manifests/` 아래에 `collected_pages_<run_id>.json`과 브라우저로 볼 수 있는 `contact_sheet_<run_id>.html`을 작성합니다. 주요 옵션은 `--site`, `--mode`, `--gallery-class`, `--scroll`, `--max-pages`, `--delay`, `--timeout`, `--keep-*`, `--download-full-images`, `--no-headless`입니다.

### 지원 사이트와 모드

- `gallery`: 구조화된 gallery anchor와 메타데이터를 읽습니다.
- `images`: 렌더링된 `<img>`/`srcset` 후보를 수집하면서 명백한 페이지 장식을 거릅니다.

| 사이트 키 | 도메인 | 모드 | 설명 |
| --- | --- | --- | --- |
| `interfaceingame` | interfaceingame.com | images | 게임 UI 스크린샷. |
| `screenlane` | screenlane.com | images | 모바일 UI/UX 흐름. |
| `collectui` | collectui.com | images | 일일 UI 영감 자료. |
| `landbook` | land-book.com | images | 랜딩 페이지 갤러리. |
| `lapaninja` | lapa.ninja | images | 랜딩 페이지 사례. |
| `refero` | refero.design | images | Web/iOS UI 영감 자료. |
| `dribbble` | dribbble.com | images | 공개 디자인 shot. |
| `behance` | behance.net | images | 공개 크리에이티브 쇼케이스. |

알 수 없는 공개 사이트는 기본적으로 `images` 모드를 사용합니다. 사이트를 추가하려면 `ui_ref_cli.py`의 `SITE_PRESETS`에 `match`, `mode`, 선택적 `gallery_class`, `notes`를 추가하세요. 구조화 메타데이터의 속성이 다를 때만 `LinkExtractor`를 확장합니다.

### 설정 탐색과 에티켓

`--config`가 없으면 다음 순서로 탐색합니다.

```text
ui_ref_config.json
ui_research/ui_ref_config.json
docs/ui_research/ui_ref_config.json
```

전역 `--project-root`로 다른 프로젝트를 지정하고 `--design-root`로 `ui_design`을 바꿀 수 있습니다. 수집은 작고 느리게 유지하세요. 기본값은 요청 간 8초, 실행당 20페이지입니다. 수집 자료를 인용된 리서치 문맥으로 취급하고 에셋 팩이나 학습 말뭉치로 취급하지 마세요.

## DOCX/PDF와 심층 디자인 문서를 위한 동반 스킬

v0.4.0 핵심 빌드는 의도적으로 JSON Design IR, Markdown, HTML, SVG, 정적 프로토타입 파일을 생성합니다. DOCX나 PDF를 직접 만들지는 **않습니다**.

저장소를 checkout할 때 포함되는 [`game-ux-ui-design` 동반 스킬](.claude/skills/game-ux-ui-design/)은 GDD 바인딩, 화면별 근거 설명, 밀도 높은 범례/상태 표, 디자인 토큰, 결정 추적, 아트 콘셉트 brief, 문서 렌더링을 포함한 장문 디자인 문서 워크플로를 추가합니다. 템플릿에는 [`build_docx.py`](.claude/skills/game-ux-ui-design/templates/build_docx.py)와 [`build_pdf.py`](.claude/skills/game-ux-ui-design/templates/build_pdf.py)가 있습니다. 이해관계자용 DOCX/PDF가 필요할 때 이 동반 스킬을 사용하되, 기계 판독 가능한 원본은 정본 `ui_design` 계약으로 유지하세요.

Python wheel은 `ui-ref` CLI만 설치하며 이 동반 스킬을 설치하거나 등록하지 않습니다. 동반 워크플로가 필요하면 저장소를 clone/download하거나 `.claude/skills/game-ux-ui-design/`을 사용 중인 어시스턴트가 지원하는 스킬 위치로 복사하세요.

## 저장소에 포함된 재현 가능 예제

전체 공개 동반 스킬 예제는 [`examples/lucid-dawn/`](examples/lucid-dawn/)에 있습니다. 문서화된 화면 12개, 주석 와이어프레임 13개, 토큰, 결정, 인용, 영어/중국어/한국어/일본어 디자인 문서를 포함합니다.

전체 예제: [영어](examples/lucid-dawn/lucid_dawn_ui_ux_design.en.md) · [중국어](examples/lucid-dawn/lucid_dawn_ui_ux_design.zh.md) · [한국어](examples/lucid-dawn/lucid_dawn_ui_ux_design.ko.md) · [일본어](examples/lucid-dawn/lucid_dawn_ui_ux_design.ja.md) · [PDF](examples/lucid-dawn/lucid_dawn_ui_ux_design.en.pdf).

## 명령어 레퍼런스

| 명령 | 용도 |
| --- | --- |
| `ui-ref init` | 레퍼런스 리서치와 설정 초기화 |
| `ui-ref scan-local` | 로컬 레퍼런스 미디어 인덱싱 |
| `ui-ref collect` | 명시적으로 나열한 공개 레퍼런스 페이지 수집 |
| `ui-ref spec init` | 정본 계약 작업공간 초기화. `design`은 `spec`의 별칭 |
| `ui-ref spec add-screen` / `add-component` | 계약 초안 생성 |
| `ui-ref spec import-references` | 최신 로컬 manifest를 근거 카탈로그와 동기화 |
| `ui-ref spec validate [--strict]` | 구조, 의미, 생명주기 게이트, 승인 검증 |
| `ui-ref spec check [--strict]` | 검증 + 와이어프레임 lint + 생성 결과물 drift 탐지 |
| `ui-ref spec compile` | 엔진 중립 Design IR 빌드 |
| `ui-ref spec build` | IR, Markdown, HTML, 주석 SVG, 해시 manifest 빌드 |
| `ui-ref spec promote` | 게이트가 있는 생명주기 전환과 원장 기록 |
| `ui-ref spec trace` | 근거 및 의존성 추적 리포트 |
| `ui-ref wireframe new/lint/render` | `.uiwire` 생성, 검증, 렌더링 |
| `ui-ref prototype build [--release]` | 클릭 가능한 정적 프로토타입 빌드 |
| `ui-ref analyze media/import` | 근거 패킷 준비 및 검증된 AI 결과를 초안으로 import |
| `ui-ref export <engine> [--screen ID] [--release]` | 엔진 인계용 스캐폴드 생성 |

모든 옵션은 `ui-ref <command> --help`에서 확인할 수 있습니다.

## 라이선스

MIT — [LICENSE](LICENSE)를 참고하세요.

프로젝트 문서: [변경 기록](CHANGELOG.md) · [기여 안내](CONTRIBUTING.md) · [보안 정책](SECURITY.md)
