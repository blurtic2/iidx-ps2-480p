# beatmania IIDX PS2 — 네이티브 480p 패치

[English](README.md) | **한국어**

PlayStation 2용 beatmania IIDX(9th style ~ 16 EMPRESS + PREMIUM BEST)가 실기에서 **24bit 색상의 네이티브 480p**로
출력되도록 하는 비공식 패치입니다.

원래 게임은 매 프레임을 640×480으로 그린 뒤, 필드마다 224줄로 줄여서 480i로 출력합니다.
이 패치는 그 과정을 없애고 그린 화면을 1:1로 복사해 480p로 내보내므로, 게임이 실제로 그리는 선명도 그대로 보입니다.
GSM으로 480p를 강제할 때처럼 줄을 복제하지 않습니다.

## 지원 게임

| 게임 | 시리얼 | PCSX2 CRC | Redump ISO CRC32 | Redump ISO MD5 |
|---|---|---|---|---|
| beatmania IIDX 9th style | SLPM-65946 | 519805E0 | e3003130 | 48edf92aed297c7a6aad706f6aa9a948 |
| beatmania IIDX 10th style | SLPM-66180 | B308CA2F | aa317dab | d50af88cbcd5b07ed5bf5edc93084bc8 |
| beatmania IIDX 11 IIDX RED | SLPM-66426 | 98CEF49B | 594ca1ee | f329f883de48bca27b00c6bccf651be6 |
| beatmania IIDX 12 HAPPY SKY | SLPM-66621 | 6D8DB060 | 4cdcc2ed | d9b429bcc120cea14a5282112acd75f7 |
| beatmania IIDX 13 DistorteD | SLPM-66828 | 26BC121E | 3c0f9550 | 4357320bcb0933334496b2101c4ec49f |
| beatmania IIDX 14 GOLD | SLPM-66995 | 40EB926F | 1d96f650 | 5c3b5f3e31424f8ddb07d2cbaca66185 |
| beatmania IIDX 15 DJ TROOPERS | SLPM-55117 | 1393B807 | 4fa612be | 6cc843d439b8b55fee7962dd6caaae0f |
| beatmania IIDX 16 EMPRESS (Disc 1) | SLPM-55221 | 44111A43 | c4895ba7 | 30c14ab6e2de3331977fa248438dc294 |
| beatmania IIDX 16 PREMIUM BEST (Disc 2) | SLPM-55222 | 57E9E985 | cb9ad964 | b33b813bee010edbd3aa1676e03aad6c |

3rd~8th style은 240p 출력이라 대상이 아닙니다.

<details>
<summary>Redump ISO SHA-1</summary>

| 게임 | SHA-1 |
|---|---|
| 9th style | 6d42643fb992c19737b22813166a12b5d60bd69e |
| 10th style | 680edcac40ed72ed318bc1bb8d6e89224b80a330 |
| 11 IIDX RED | 8e52f963a33c9fe95022861ef39966bde715ed1a |
| 12 HAPPY SKY | b82e7939b720b8a1c0875e88a328493f336a758f |
| 13 DistorteD | 706da91072b75262729c96b16aa91181231184d2 |
| 14 GOLD | 7cc3625f57f4d77d67ac3fb3675d3ee5de18e726 |
| 15 DJ TROOPERS | 6a35e096900dc6e7842f7aa86366ba0f5fe78dfd |
| 16 EMPRESS (Disc 1) | 92d95574a6a35a908cc3255a997a15f126993ada |
| 16 PREMIUM BEST (Disc 2) | b23f9799b2cb6106b45c992928c97d6f2e4d3a8b |

</details>

## 두 가지 판

| 판 | 표시하는 줄 | 추천 환경 |
|---|---|---|
| **480p** (기본) | 448줄 (원래 게임과 같은 영역) | CRT, 오버스캔이 있는 TV. 게임 내 화면 위치 조정이 그대로 동작 |
| **480p 480 lines** | 그린 480줄 전체 (위아래 16줄씩 더 보임) | 업스케일러, 캡처 장비, 오버스캔이 없는 디스플레이 |

480줄판에서는 게임 옵션의 **세로** 화면 위치 조정이 동작하지 않습니다(옮길 여유 영역이 없어서). 가로 조정은 그대로 동작합니다.

## 적용 방법

본인 디스크에서 뜬 ISO를 사용하세요. xdelta 패치는 위 표의 Redump 검증본과 **정확히 같은 ISO**에만 적용됩니다.
스크립트는 ISO 안의 실행 파일만 수정되지 않았으면 적용됩니다.

### xdelta (가장 간단)

1. [Releases](../../releases) 페이지에서 게임과 판에 맞는 `.xdelta` 파일을 받습니다.
2. Delta Patcher, xdelta UI 같은 xdelta 패처로 ISO에 적용합니다.

### Python 스크립트

Python 3.8 이상이 필요합니다. ISO를 직접 수정하므로 사본에 사용하세요.

```
python patch480p.py iso "beatmania IIDX 13 DistorteD.iso"
python patch480p.py iso "beatmania IIDX 13 DistorteD.iso" --480
```

- 게임은 자동으로 판별합니다. 실행 파일의 4바이트 값 수십 개만 바뀌고, ISO 크기와 다른 파일은 그대로입니다.
- 이미 패치한 ISO에 다시 실행하면 두 판 사이를 전환합니다.
- 지원하는 실행 파일이 아니거나 다른 도구로 수정된 경우에는 아무것도 쓰지 않습니다.

### PCSX2 (부가 자료: 미리보기와 테스트용)

이 패치는 실기를 위한 것입니다. PCSX2용 `.pnach` 파일은 ISO를 수정하지 않고 결과를 미리 보거나 문제를 재현해 볼 수 있도록
릴리스에 부가 자료로 첨부합니다(패치한 ISO도 PCSX2에서 그대로 동작합니다).
PCSX2는 실기와 완전히 똑같이 그리지는 않으므로, 화질은 실기에서 판단해 주세요.

파일을 PCSX2의 `patches` 폴더에 넣고, 게임 속성에서 480p 그룹 **하나만** 켠 뒤 게임을 처음부터 부팅하세요.
시작 코드를 고치는 패치라서 세이브스테이트를 불러오는 것만으로는 적용되지 않습니다.
`python patch480p.py pnach <폴더>`로 같은 파일을 만들 수 있습니다.

## 실기에서 사용할 때

- **컴포넌트(YPbPr) 케이블**과 480p를 받는 디스플레이, 업스케일러 또는 변환기가 필요합니다. 컴포지트와 S-Video로는 480p가 나오지 않습니다.
- **GSM으로 해상도를 강제하지 마세요.** 게임이 직접 480p로 설정합니다.
- 판정과 타이밍은 건드리지 않습니다. 화면 출력 경로만 바뀝니다.

## 참고

- **13, 14, 15:** 전체 화면 영상(오프닝, 엔딩)이 나오는 동안은 VRAM이 부족해서 24bit 화면을 둘 수 없습니다.
  그래서 영상이 나오는 동안만 디더링이 들어간 16bit로 출력하고, 끝나면 24bit로 돌아옵니다. 메뉴와 플레이는 항상 24bit입니다.
- PCSX2는 실기 GS의 동작을 모두 재현하지 않습니다. 그래서 최종 확인은 실기에서 했습니다.

## 동작 원리 (요약)

- 출력 모드를 480i에서 480p로 바꾸고(`sceGsResetGraph`), 출력 버퍼를 640×224 대신 640×448(또는 640×480) 24bit 버퍼로 바꿉니다.
- 640×480 그리기 버퍼에서 출력 버퍼로 매 프레임 복사하는 방식을, 필드마다 반 줄씩 어긋나게 2:1로 줄이던 것에서 포인트 샘플링 1:1 복사로 바꿉니다.
- 커진 출력 버퍼를 4MB VRAM에 넣기 위해 그리기 버퍼를 352페이지로 옮기고, (10th 이후는) Z버퍼를 그리기 버퍼가 비운 자리로 옮깁니다.
  텍스처 영역과, 이 버퍼들을 직접 가리키는 연출들도 그에 맞게 고칩니다.
- 13~15는 전체 화면 영상용 VRAM 모드가 따로 있어서, 게임의 모드 전환 함수에 작은 루틴을 연결해 출력 형식도 함께 바꿉니다.

바뀌는 값은 모두 [`patch480p.py`](patch480p.py)에 주석과 함께 정리되어 있습니다.

## 면책

이 프로젝트는 비공식 팬 프로젝트이며 KONAMI 및 Sony Interactive Entertainment와 관련이 없고 승인받지 않았습니다.
게임 데이터는 포함하거나 배포하지 않으며, 게임을 직접 소유하고 있어야 합니다. 사용에 따른 책임은 사용자에게 있습니다.

## 크레딧

분석과 패치는 Claude(Anthropic)의 도움을 받아 만들었습니다.

## 라이선스

[MIT](LICENSE)
