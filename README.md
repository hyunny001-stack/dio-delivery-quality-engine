# DIO 국내 배송품질 분석 엔진

국내배송트레킹의 ERP/택배 조회 결과 파일을 입력받아 배송 품질을 빠르게 산출하는 분석 전용 엔진입니다.

데이터 수집은 의도적으로 자동화하지 않습니다. 월 단위, 주 단위, 특정일, 특정 기간 등 분석 목적에 따라 사용자가 준비한 원천 파일을 넣고, 이 엔진은 동일한 기준으로 빠르게 재계산하는 역할만 담당합니다.

## 설계 방향

이 저장소는 특정 기준을 코드에 박아놓고 돌리는 도구가 아니라, **분석 기준을 JSON 설정으로 바꿔 끼우는 틀**입니다.

- 분석 기간: `analysis_window_days`로 조정
- 택배사별 Cut-off: `carriers.*.cutoff`로 조정
- 제외 기준: `exclude` 블록에서 on/off
- 공휴일: `holidays` 목록으로 관리
- 도서산간 키워드: `island_mountain_keywords`로 관리
- 품질오류 정의: `quality_error_rules`에서 선택

현재 기본 프로파일은 최근 회의 기준입니다.

- 우체국 Cut-off: 익일 15:00 이후 도착 = 시간초과
- CJ대한통운 Cut-off: 익일 17:00 이후 도착 = 시간초과
- 제외 기준: 금요일 발송, 공휴일 전일 발송, 도서산간/격오지
- 품질오류: 도서산간 제외 익일 미배송 + Cut-off 이후 도착

## 사용 예시

ERP 40일 원천 JSON이 있을 때:

```bash
python3 -m dio_delivery_quality_engine.cli analyze \
  --erp-json /tmp/domestic_erp_40d_raw.json \
  --cache /tmp/domestic_tracking_cache.jsonl \
  --out /tmp/domestic_quality_result.json
```

테스트/샘플 실행:

```bash
python3 -m unittest
python3 -m dio_delivery_quality_engine.cli analyze \
  --erp-json examples/sample_erp.json \
  --cache /tmp/sample_tracking_cache.jsonl \
  --out /tmp/sample_result.json \
  --track-mode fixture
```

## 출력물

- `summary`: 택배사별 익일배송률, Cut-off 초과율, 품질오류율
- `regionDelay`: 도서산간 제외 익일 미배송 지역 순위
- `cutoffFailRegion`: Cut-off 이후 도착 지역 순위
- `samples`: 클레임/개선요청용 대표 송장 리스트

## 운영 메모

- 실제 운영 시 국내배송트레킹 API 또는 캐시 파일을 연동하면, 이미 조회한 송장은 재조회하지 않아 속도가 빠릅니다.
- 주소가 `NA`인 건은 `지역미상`으로 분류되므로, 택배사 클레임 전 ERP 주소 보완이 필요합니다.
- 공휴일 목록은 `--holidays YYYY-MM-DD,YYYY-MM-DD`로 지정합니다.
