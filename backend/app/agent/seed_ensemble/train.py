"""Train on one date range, choose a checkpoint using validation only."""

from dataclasses import dataclass
from pathlib import Path
import json
import math

import numpy as np
import pandas as pd
import torch

from .dqn import DQNAgent
from .backtester import run_backtest
from .trading_env import TradingEnv


def build_agent(state_dim, action_dim, config):
    # 논문은 DQN[1]만 사용한다. 원본 저장소의 Double DQN(실험29)은 가져오지 않았다.
    name = config["agent"]["algorithm"]
    if name != "dqn":
        raise ValueError("agent.algorithm must be dqn (the paper uses DQN only).")
    return DQNAgent.from_config(state_dim, action_dim, config)


def save_checkpoint(agent, config, path, *, episode, validation_metrics):
    """Inference checkpoint, not exact training-resume state (replay is not saved)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "format_version": 1,
            "purpose": "inference",
            "config": json.loads(json.dumps(config, default=str)),
            "state_dim": agent.state_dim,
            "action_dim": agent.action_dim,
            "policy_state_dict": agent.policy_network.state_dict(),
            "episode": episode,
            "learning_steps": agent.learning_steps,
            "total_steps": agent.total_steps,
            "epsilon": agent.epsilon,
            "validation_metrics": validation_metrics,
        },
        path,
    )


def load_checkpoint(path):
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if (
        checkpoint.get("format_version") != 1
        or checkpoint.get("purpose") != "inference"
    ):
        raise ValueError("Unsupported model checkpoint.")
    config = checkpoint["config"]
    agent = build_agent(checkpoint["state_dim"], checkpoint["action_dim"], config)
    agent.policy_network.load_state_dict(checkpoint["policy_state_dict"])
    agent.update_target_network()
    agent.policy_network.eval()
    return agent, config, checkpoint


@dataclass
class TrainingResult:
    agent: DQNAgent
    history: pd.DataFrame
    best_episode: int
    checkpoint_path: Path
    total_steps: int
    learning_steps: int


def train(train_df, validation_df, config, run_dir, *, progress=print):
    """Agent is created once outside the episode loop; env.reset keeps learned state."""
    settings = config["training"]
    for name in ("episodes", "train_frequency", "gradient_steps", "torch_threads"):
        if type(settings[name]) is not int or settings[name] <= 0:
            raise ValueError(f"training.{name} must be a positive integer.")
    metric = settings["selection_metric"]
    direction = {
        "cumulative_return": 1,
        "sharpe_ratio": 1,
        "sortino_ratio": 1,
        "mdd": -1,
    }
    if metric not in direction:
        raise ValueError(f"Unsupported checkpoint selection metric: {metric}")
    window = config["state"]["window"]
    if train_df.index[-1] >= validation_df.index[window]:
        raise ValueError("Training and validation execution dates must not overlap.")
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    model_relative = Path(config["paths"]["model_file"])
    if model_relative.is_absolute() or ".." in model_relative.parts:
        raise ValueError(
            "paths.model_file must be a relative path inside the run directory."
        )
    best_path = run_dir / model_relative
    last_path = best_path.with_name("last_model.pth")
    if best_path.exists() or last_path.exists():
        raise FileExistsError(
            "Choose a new run directory to avoid replacing an experiment."
        )
    env = TradingEnv.from_config(train_df, config)
    if env.episode_steps * settings["episodes"] < settings["learning_starts"]:
        raise ValueError(
            "This run ends before learning_starts; add episodes or training dates."
        )
    agent = build_agent(env.state_dim, env.action_size, config)
    best_episode = 0
    best_score = -math.inf
    records = []
    old_threads = torch.get_num_threads()
    torch.set_num_threads(settings["torch_threads"])
    try:
        for episode in range(1, settings["episodes"] + 1):
            state = env.reset()
            done = False
            losses = []
            while not done:
                action = agent.select_action(state)
                next_state, reward, done, _ = env.step(action)
                agent.remember(state, action, reward, next_state, done)
                if agent.total_steps % settings["train_frequency"] == 0:
                    for _ in range(settings["gradient_steps"]):
                        learning = agent.learn()
                        if learning is not None:
                            losses.append(learning["loss"])
                state = next_state

            validation = run_backtest(validation_df, config, agent=agent)
            value = validation.metrics[metric]
            score = direction[metric] * value if value is not None else -math.inf
            if agent.learning_steps > 0 and (best_episode == 0 or score > best_score):
                best_score = score
                best_episode = episode
                save_checkpoint(
                    agent,
                    config,
                    best_path,
                    episode=episode,
                    validation_metrics=validation.metrics,
                )
            record = {
                "episode": episode,
                "environment_steps": agent.total_steps,
                "learning_steps": agent.learning_steps,
                "epsilon": agent.epsilon,
                "mean_loss": float(np.mean(losses)) if losses else None,
                "train_return": env.asset_value / env.initial_balance - 1,
                "selection_value": value,
                "best_episode": best_episode,
            }
            for name, metric_value in validation.metrics.items():
                record[f"validation_{name}"] = metric_value
            records.append(record)
            pd.DataFrame(records).to_csv(run_dir / "training_history.csv", index=False)
            if progress:
                progress(
                    f"Episode {episode}/{settings['episodes']} | updates={agent.learning_steps} "
                    f"epsilon={agent.epsilon:.3f} | validation return="
                    f"{validation.metrics['cumulative_return']:.2%} | best={best_episode}",
                )
        if best_episode == 0:
            raise ValueError(
                "No Policy update occurred; check warm-up and training frequency."
            )
        save_checkpoint(
            agent,
            config,
            last_path,
            episode=episode,
            validation_metrics=validation.metrics,
        )
    finally:
        torch.set_num_threads(old_threads)
    # Evaluation uses the validation-selected policy, not necessarily the last episode.
    selected, _, _ = load_checkpoint(best_path)
    return TrainingResult(
        selected,
        pd.DataFrame(records),
        best_episode,
        best_path,
        agent.total_steps,
        agent.learning_steps,
    )
