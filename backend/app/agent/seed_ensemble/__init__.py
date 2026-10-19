"""시드 앙상블 DQN 주식 비중 조절 (논문 구현).

「시드 앙상블을 통한 DQN 주식 비중 조절의 성과 및 안정성 개선」에서 쓴 알고리즘만 담는다.
su08035-ops/auto_trading/backend 에서 가져온 부분과 새로 쓴 부분은 다음과 같다.

  원본에서 그대로 가져옴 (import 경로만 바꿈)
    network.py       Q-네트워크 MLP (301 → 256 → 256 → 3, ReLU)
    dqn.py           DQN: ε-greedy, 경험 리플레이, Huber 손실, Adam, 타깃망 하드 복사
    features.py      시장 특성 15개 (가격 4 · 추세 7 · 모멘텀 1 · 변동성 1 · 거래량 2)
    preprocessing.py OHLCV 정리, 학습/검증/시험 분할 (clean_ohlcv, prepare_splits)
    paper_broker.py  정수 주식 · long-only 체결, 수수료 0.015% · 매도세 0.25%
    trading_env.py   목표 비중 {0, 0.5, 1}, t 종가 관찰 → t+1 시가 체결, 로그수익률 보상
    train.py         에피소드 학습 + 검증 누적수익률 최고 에피소드 선택 (Double DQN 제외)
    backtester.py    동결 정책 평가 (+ 앙상블용 decide 인자 추가)
    metrics.py       누적수익률, MDD, 샤프 (+ 논문 표 2의 평균 비중 추가)
    kis_loader.py    KIS 수정주가 일봉 수집 (합성 데이터 생성기 제외)

  논문 3장에 따라 새로 작성 (원본 저장소에 없음)
    ensemble.py      다수결(식 2, 동점 시 작은 비중) · Q값 평균(식 3) 결합
    evaluate.py      표 2 (단일 평균/MV/QA/B&H) · 표 3 (결합 시드 수 k별 조합) 평가

  가져오지 않음: Double DQN, 하이퍼파라미터 탐색용 walk-forward 도구, 실험 결과 폴더,
  실주문 브로커(real_broker — KAIRO의 KIS 어댑터가 대신한다), 합성 데이터, 프론트엔드.
"""

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PAPER_CONFIG = PACKAGE_DIR / "paper_config.yaml"
