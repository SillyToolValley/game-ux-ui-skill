# EXPORT/VERIFY — 엔진 바인딩을 실제 런타임에 묶기

> 구조화 계약의 데이터 바인딩을 **선택 엔진에서 무GC·이벤트 기반**으로 구현하는
> 핸드오프 가이드. UX 계약과 런타임을 잇는 다리이며, 최종 구현은 TDD와 프로파일링이 결정.
> 엔진이 GDD/브리프에 명시돼 있으면 해당 절만, 아니면 일반 원칙만.

CLI exporter는 검증된 공통 Design IR에서 다음을 생성한다.

```bash
ui-ref export unity-uitoolkit [--screen <id>] [--release]
ui-ref export unity-ugui      [--screen <id>] [--release]
ui-ref export godot           [--screen <id>] [--release]
ui-ref export cocos           [--screen <id>] [--release]
```

UI Toolkit은 UXML/USS/바인딩 JSON, Godot은 Control 기반 `.tscn`/바인딩 JSON을 만든다.
uGUI와 Cocos는 안전하게 생성할 수 있는 구조화 핸드오프를 만든다. 어느 출력도 완성 런타임을
뜻하지 않는다. `capability-report.json`의 `manual_or_lossy` 항목과 `export-manifest.json`의
입출력 해시를 반드시 검토한다. `--release`는 현재 사람 승인이 유효한 화면만 허용한다.

## 공통 원칙 (모든 엔진)
- **단일 출처**: 런타임 상태(타이머/HP/자원/보스…)는 시뮬이 보유, UI는 읽기만.
- **변화 시에만 갱신**: 매 프레임 텍스트/레이아웃 리빌드 금지. dirty-flag/변경 감지로 바뀐 값만.
- **무할당 업데이트 루프**: LINQ/박싱/임시객체 금지(특히 고밀도 전투).
- **고빈도 표시 분리**: 타이머는 표시 단위(1초)로만 갱신. 데미지 수치 등 **대량 월드 텍스트는 UI 프레임워크가 아니라 전용 대량 렌더 경로**로.
- **월드 vs 스크린**: 고정 HUD=스크린 오버레이, 플레이어/적 추종=월드 앵커(소수만 UI로).
- **모달=시뮬 정지 동기**, **포커스 내비게이션**으로 패드 패리티, **로컬라이즈** 길이/숫자 포맷.

## Unity — UI Toolkit (+ DOTS/ECS면)
- 상태=`IComponentData` 싱글톤. 메인 스레드 **브리지 `SystemBase`** 가 ECS `ChangeVersion`로 변경만 감지→UI 푸시. 이게 "UI 제안 이벤트"의 실제 구현.
- `VisualElement` 참조 캐시(매 프레임 `Q<>()` 금지). Unity 6 런타임 data binding(`SetBinding`) 또는 dirty-flag 푸시(프로파일로 선택).
- `PanelSettings` scale mode로 멀티 해상도+세이프. Input System + UI Toolkit 포커스. Unity Localization 스트링 테이블.

## Unreal — UMG (+ Mass/ECS면)
- `ViewModel`(MVVM 플러그인) 또는 이벤트 디스패처로 변경 푸시(틱 바인딩 지양). 대량 표시는 UMG 밖(Niagara/인스턴싱).

현재 CLI는 Unreal `.uasset`을 생성한다고 약속하지 않는다. Unreal 대상은 이 원칙과 공통
engine IR을 근거로 별도 UMG/MVVM 어댑터를 설계해야 한다.

## 체크리스트
- [ ] 고밀도 상황에서 HUD 갱신 프레임당 할당 0 / 리플로 최소.
- [ ] 값 변경 시에만 갱신(프로파일 확인).
- [ ] 대량 월드 텍스트가 UI 프레임워크 밖.
- [ ] 모달/보상 동안 시뮬 정지 동기.
- [ ] 패드 포커스 내비게이션 전 화면 동작.
- [ ] capability report의 `manual_or_lossy` 항목이 담당자와 이슈에 연결됨.
- [ ] export manifest의 계약 해시가 리뷰한 revision과 일치.
- [ ] 실제 엔진 빌드에서 현지화, 세이프 영역, 접근성 모드, 고밀도 가독성을 재검증.
