"""Basic, one-step DQN: action selection, replay and Policy/Target learning.

Call select_action -> env.step -> remember -> learn once per training step.
The agent survives episode resets. No market data or broker API is loaded here.
Source: su08035-ops/auto_trading backend/agents/dqn.py (unchanged logic).
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from numbers import Integral
import random
from typing import Any, NamedTuple

import numpy as np
import torch
from torch import nn

from .network import QNetwork


class Experience(NamedTuple):
    """Observed facts only. Old Q-values are deliberately not stored."""

    state: np.ndarray
    action: int
    reward: float
    next_state: np.ndarray
    done: bool


class DQNAgent:
    """Own two networks and train Policy with the configured optimizer and loss."""

    algorithm = "dqn"

    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        *,
        hidden_dim: int = 128,
        optimizer_name: str = "adam",
        loss_name: str = "mse",
        gamma: float = 0.99,
        learning_rate: float = 0.001,
        batch_size: int = 64,
        replay_buffer_size: int = 20_000,
        learning_starts: int = 256,
        target_update_interval: int = 500,
        epsilon_start: float = 1.0,
        epsilon_min: float = 0.05,
        epsilon_decay: float = 0.999,
        seed: int = 42,
    ) -> None:
        self._validate_settings(
            gamma,
            learning_rate,
            batch_size,
            replay_buffer_size,
            learning_starts,
            target_update_interval,
            epsilon_start,
            epsilon_min,
            epsilon_decay,
        )
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.gamma = gamma
        self.batch_size = batch_size
        self.learning_starts = learning_starts
        self.target_update_interval = target_update_interval
        self.epsilon = epsilon_start
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.total_steps = 0
        self.learning_steps = 0
        self.rng = random.Random(seed)
        self.replay_rng = random.Random(seed + 1)

        # Initialize reproducibly without changing the caller's CPU random stream.
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            self.policy_network = QNetwork(state_dim, action_dim, hidden_dim)
        self.target_network = deepcopy(self.policy_network)
        self.target_network.requires_grad_(False)
        self.target_network.eval()
        optimizers = {"adam": torch.optim.Adam, "sgd": torch.optim.SGD}
        losses = {"mse": nn.MSELoss, "huber": nn.SmoothL1Loss, "mae": nn.L1Loss}
        if optimizer_name not in optimizers or loss_name not in losses:
            raise ValueError("optimizer must be adam/sgd and loss must be mse/huber/mae.")
        self.optimizer = optimizers[optimizer_name](
            self.policy_network.parameters(), lr=learning_rate
        )
        self.loss_function = losses[loss_name](reduction="mean")
        self.replay_buffer: deque[Experience] = deque(maxlen=replay_buffer_size)

    @classmethod
    def from_config(
        cls, state_dim: int, action_dim: int, config: dict[str, Any]
    ) -> "DQNAgent":
        """Map YAML agent/training settings to the constructor explicitly."""
        agent = config["agent"]
        training = config["training"]
        if agent["algorithm"] != cls.algorithm:
            raise ValueError(f"{cls.__name__} requires algorithm={cls.algorithm}.")
        return cls(
            state_dim,
            action_dim,
            hidden_dim=agent["hidden_dim"],
            optimizer_name=agent["optimizer"],
            loss_name=agent["loss"],
            gamma=agent["gamma"],
            learning_rate=agent["learning_rate"],
            batch_size=agent["batch_size"],
            replay_buffer_size=agent["replay_buffer_size"],
            learning_starts=training["learning_starts"],
            target_update_interval=agent["target_update_interval"],
            epsilon_start=agent["epsilon_start"],
            epsilon_min=agent["epsilon_min"],
            epsilon_decay=agent["epsilon_decay"],
            seed=training["seed"],
        )

    def select_action(self, state: np.ndarray, *, explore: bool = True) -> int:
        """Return an action index. explore=False is greedy and changes no counters."""
        state = self._check_state(state)
        if explore:
            warming_up = self.total_steps < self.learning_starts
            if warming_up or self.rng.random() < self.epsilon:
                return self.rng.randrange(self.action_dim)

        with torch.no_grad():
            q_values = self.policy_network(torch.from_numpy(state))
        return int(q_values.argmax().item())

    def remember(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool,
    ) -> None:
        """Store one transition and increment the lifetime environment-step count."""
        state = self._check_state(state)
        next_state = self._check_state(next_state)
        if isinstance(action, (bool, np.bool_)) or not isinstance(action, Integral):
            raise ValueError("action must be an integer index.")
        if not 0 <= action < self.action_dim:
            raise ValueError("action index is outside the network output range.")
        if not np.isfinite(reward):
            raise ValueError("reward must be finite.")
        if not isinstance(done, (bool, np.bool_)):
            raise ValueError("done must be boolean.")
        # Copies protect historical observations from later changes by the caller.
        self.replay_buffer.append(
            Experience(
                state.copy(), int(action), float(reward), next_state.copy(), bool(done)
            )
        )
        self.total_steps += 1

    def learn(self) -> dict[str, float | int | bool] | None:
        """Run one minibatch update, or return None while experience is insufficient."""
        if (
            self.total_steps < self.learning_starts
            or len(self.replay_buffer) < self.batch_size
        ):
            return None

        # 7-1. Sample B experiences and keep every (s, a, r, s', done) row aligned.
        batch = self.replay_rng.sample(list(self.replay_buffer), self.batch_size)
        states = torch.from_numpy(np.stack([item.state for item in batch]))
        actions = torch.tensor([item.action for item in batch], dtype=torch.long)
        rewards = torch.tensor([item.reward for item in batch], dtype=torch.float32)
        next_states = torch.from_numpy(np.stack([item.next_state for item in batch]))
        dones = torch.tensor([item.done for item in batch], dtype=torch.bool)

        # 7-2. (B, actions) -> (B,): select each experience's RECORDED action.
        all_q_values = self.policy_network(states)
        predicted_q = all_q_values.gather(1, actions.unsqueeze(1)).squeeze(1)

        # 7-3. Target network supplies a frozen estimate, not a known true answer.
        target_q = self._calculate_td_targets(rewards, next_states, dones)

        # 7-4 and 7-5. There are B TD errors, but one mean loss for the batch.
        td_errors = target_q - predicted_q
        loss = self.loss_function(predicted_q, target_q)
        if not torch.isfinite(loss).item():
            raise FloatingPointError(
                "Non-finite loss; check features, rewards and learning rate."
            )

        # 7-6. Loss first, gradients second, actual Policy weight changes last.
        self.optimizer.zero_grad()
        loss.backward()
        for parameter in self.policy_network.parameters():
            if (
                parameter.grad is not None
                and not torch.isfinite(parameter.grad).all().item()
            ):
                raise FloatingPointError(
                    "Non-finite Policy gradient; update was not applied."
                )
        self.optimizer.step()
        self.learning_steps += 1

        # 8. Count successful Policy updates across episodes, never calendar days.
        target_updated = self.learning_steps % self.target_update_interval == 0
        if target_updated:
            self.update_target_network()
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

        return {
            "loss": float(loss.detach().item()),
            "mean_td_error": float(td_errors.detach().mean().item()),
            "epsilon": self.epsilon,
            "learning_steps": self.learning_steps,
            "target_updated": target_updated,
        }

    def _calculate_td_targets(
        self, rewards: torch.Tensor, next_states: torch.Tensor, dones: torch.Tensor
    ) -> torch.Tensor:
        """One-step DQN: y = r + gamma * max Q_target(s', a'); terminal y = r."""
        with torch.no_grad():
            next_values = torch.zeros_like(rewards)
            nonterminal = ~dones
            if nonterminal.any().item():
                next_q_values = self.target_network(next_states[nonterminal])
                next_values[nonterminal] = next_q_values.max(dim=1).values
            return rewards + self.gamma * next_values

    def update_target_network(self) -> None:
        """Hard-copy Policy parameters without sharing their storage or gradients."""
        self.target_network.load_state_dict(self.policy_network.state_dict())

    def _check_state(self, state: np.ndarray) -> np.ndarray:
        state = np.asarray(state, dtype=np.float32)
        if state.shape != (self.state_dim,) or not np.isfinite(state).all():
            raise ValueError(
                f"state must be a finite vector with shape ({self.state_dim},)."
            )
        return state

    @staticmethod
    def _validate_settings(
        gamma: float,
        learning_rate: float,
        batch_size: int,
        replay_buffer_size: int,
        learning_starts: int,
        target_update_interval: int,
        epsilon_start: float,
        epsilon_min: float,
        epsilon_decay: float,
    ) -> None:
        counts = (
            batch_size,
            replay_buffer_size,
            learning_starts,
            target_update_interval,
        )
        if any(type(value) is not int or value <= 0 for value in counts):
            raise ValueError(
                "Batch, buffer, warm-up and target interval must be positive integers."
            )
        if batch_size > replay_buffer_size or learning_starts < batch_size:
            raise ValueError(
                "Require batch_size <= buffer size and batch_size <= learning_starts."
            )
        if not np.isfinite(gamma) or not 0 <= gamma <= 1:
            raise ValueError("gamma must be finite and within [0, 1].")
        if not np.isfinite(learning_rate) or learning_rate <= 0:
            raise ValueError("learning_rate must be finite and positive.")
        if not 0 <= epsilon_min <= epsilon_start <= 1:
            raise ValueError("Require 0 <= epsilon_min <= epsilon_start <= 1.")
        if not 0 < epsilon_decay <= 1:
            raise ValueError("epsilon_decay must be in (0, 1].")
