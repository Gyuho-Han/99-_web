"""시드별 DQN 학습 → 검증 기반 모델 선택 → 시험 구간 앙상블 평가.

backend 폴더에서 실행한다.

    # 1) 이미 받아 둔 OHLCV CSV로 (date, open, high, low, close, volume)
    python -m scripts.train_seed_ensemble --symbol 005930 --csv path/to/ohlcv.csv

    # 2) KIS에서 수정주가 일봉을 직접 받아서 (실전 앱키 권장, 주문은 내지 않는다)
    export KIS_APP_KEY=... KIS_APP_SECRET=...
    python -m scripts.train_seed_ensemble --symbol 000660

    # 학습은 건너뛰고 저장된 모델로 표 2·표 3만 다시 계산
    python -m scripts.train_seed_ensemble --symbol 005930 --evaluate-only

결과는 models/seed_ensemble/<종목코드>/ 아래에 쌓인다.

    seed-<k>/dqn_model.pth        검증 누적수익률 최고 에피소드의 모델 (서버가 이 파일을 읽는다)
    seed-<k>/training_history.csv
    ohlcv.csv                     학습·평가에 쓴 원본 일봉
    report.json / report.md       논문 표 2 · 표 3 형식의 시험 구간 결과

시드 하나에 CPU로 10~20분쯤 걸린다. --jobs 로 여러 시드를 동시에 학습할 수 있다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from app.agent.seed_ensemble import PAPER_CONFIG  # noqa: E402
from app.agent.seed_ensemble.ensemble import CHECKPOINT_NAME, SeedEnsemble  # noqa: E402
from app.agent.seed_ensemble.evaluate import (  # noqa: E402
    evaluate_table2,
    evaluate_table3,
    format_report,
)
from app.agent.seed_ensemble.features import (  # noqa: E402
    get_market_feature_names,
    make_features,
)
from app.agent.seed_ensemble.preprocessing import clean_ohlcv, prepare_splits  # noqa: E402

MODELS_ROOT = BACKEND / "models" / "seed_ensemble"


def load_config(path: Path, args) -> dict:
    with Path(path).open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    data = config["data"]
    for key, value in (
        ("start_date", args.start),
        ("validation_start", args.validation_start),
        ("split_date", args.test_start),
        ("end_date", args.end),
    ):
        if value:
            data[key] = value
    if args.episodes:
        config["training"]["episodes"] = args.episodes
    return config


def load_ohlcv(args, config) -> pd.DataFrame:
    data = config["data"]
    if args.csv:
        frame = clean_ohlcv(pd.read_csv(args.csv))
    else:
        from app.agent.seed_ensemble.kis_loader import KISCredentials, KISDailyPriceLoader

        credentials = KISCredentials.from_env(environment=args.kis_env)
        loader = KISDailyPriceLoader(
            credentials,
            market=data["market"],
            period=data["period"],
            adjusted_price_code=str(data["adjusted_price_code"]),
        )
        frame = clean_ohlcv(
            loader.fetch_daily_ohlcv(args.symbol, data["start_date"], data["end_date"])
        )
    return frame.loc[pd.Timestamp(data["start_date"]) : pd.Timestamp(data["end_date"])]


def train_one(seed: int, config: dict, splits_path: str, out_dir: str) -> dict:
    """한 시드 학습. 별도 프로세스에서도 돌 수 있게 입력은 파일 경로로 받는다."""
    from app.agent.seed_ensemble.train import train

    splits = pd.read_pickle(splits_path)
    config = deepcopy(config)
    config["training"]["seed"] = int(seed)
    run_dir = Path(out_dir) / f"seed-{seed}"
    result = train(
        splits["train"],
        splits["validation"],
        config,
        run_dir,
        progress=lambda line: print(f"[seed {seed}] {line}", flush=True),
    )
    # last_model.pth 는 학습 재개용이 아니라(리플레이 버퍼 미저장) 서버에서도 쓰지 않는다.
    (run_dir / "last_model.pth").unlink(missing_ok=True)
    return {"seed": int(seed), "best_episode": int(result.best_episode)}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--symbol", required=True, help="종목코드 (예: 005930)")
    parser.add_argument("--csv", type=Path, help="OHLCV CSV. 없으면 KIS에서 받는다")
    parser.add_argument("--kis-env", default="real", choices=["real", "paper"])
    parser.add_argument("--config", type=Path, default=PAPER_CONFIG)
    parser.add_argument("--seeds", type=int, nargs="+")
    parser.add_argument("--episodes", type=int)
    parser.add_argument("--start")
    parser.add_argument("--validation-start")
    parser.add_argument("--test-start")
    parser.add_argument("--end")
    parser.add_argument("--out", type=Path, help="기본: models/seed_ensemble/<symbol>")
    parser.add_argument("--jobs", type=int, default=1, help="동시에 학습할 시드 수")
    parser.add_argument("--evaluate-only", action="store_true")
    args = parser.parse_args(argv)

    config = load_config(args.config, args)
    seeds = args.seeds or config["training"]["seeds"]
    out_dir = (args.out or MODELS_ROOT / args.symbol).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_copy = out_dir / "ohlcv.csv"
    if args.evaluate_only and not args.csv and csv_copy.exists():
        args.csv = csv_copy
    ohlcv = load_ohlcv(args, config)
    if not (args.csv and Path(args.csv).resolve() == csv_copy):
        ohlcv.to_csv(csv_copy, index_label="date")
    features = make_features(ohlcv, selected_features=get_market_feature_names(config))
    splits = prepare_splits(features, config)
    window = config["state"]["window"]
    for name, frame in splits.items():
        print(
            f"{name:10s} {frame.index[window].date()} ~ {frame.index[-1].date()} "
            f"({len(frame) - window} steps)"
        )

    if not args.evaluate_only:
        existing = [s for s in seeds if (out_dir / f"seed-{s}" / CHECKPOINT_NAME).exists()]
        if existing:
            raise SystemExit(
                f"{out_dir} 에 이미 seed {existing} 모델이 있습니다. "
                "덮어쓰지 않으니 --out 으로 새 폴더를 지정하거나 --evaluate-only 를 쓰세요."
            )
        splits_path = out_dir / ".splits.pkl"
        pd.to_pickle(splits, splits_path)
        try:
            if args.jobs > 1:
                with ProcessPoolExecutor(max_workers=args.jobs) as pool:
                    jobs = [
                        pool.submit(train_one, s, config, str(splits_path), str(out_dir))
                        for s in seeds
                    ]
                    trained = [job.result() for job in jobs]
            else:
                trained = [train_one(s, config, str(splits_path), str(out_dir)) for s in seeds]
        finally:
            splits_path.unlink(missing_ok=True)
        print("best episodes:", {t["seed"]: t["best_episode"] for t in trained})

    ensemble = SeedEnsemble.load(out_dir, seeds)
    table2 = evaluate_table2(ensemble, splits["test"])
    table3 = evaluate_table3(ensemble, splits["test"])
    report = {
        "symbol": args.symbol,
        "seeds": ensemble.seeds,
        "data": {k: str(v) for k, v in config["data"].items()},
        "table2": table2,
        "table3": table3,
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    text = format_report(args.symbol, table2, table3)
    (out_dir / "report.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    main()
