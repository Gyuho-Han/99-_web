"""Calculate Q-values; DQN controls learning.

Paper configuration: 301 inputs -> 256 -> 256 -> 3 raw Q-values (ReLU).
Source: su08035-ops/auto_trading backend/agents/network.py (unchanged logic).
"""

import torch
from torch import nn


class QNetwork(nn.Module):
    """Map market and portfolio observations to one raw Q-value per action."""

    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        hidden_dim: int = 128,
    ) -> None:
        super().__init__()
        sizes = (state_dim, action_dim, hidden_dim)
        if any(type(size) is not int or size <= 0 for size in sizes):
            raise ValueError("Network dimensions must be positive integers.")
        self.hidden1 = nn.Linear(state_dim, hidden_dim)
        self.hidden2 = nn.Linear(hidden_dim, hidden_dim)
        self.output = nn.Linear(hidden_dim, action_dim)
        self.relu = nn.ReLU()

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        """Return raw Q-values, preserving any leading batch dimension.

        Input (state_dim,) returns (action_dim,).
        Input (batch_size, state_dim) returns (batch_size, action_dim).
        """
        hidden = self.relu(self.hidden1(state))
        hidden = self.relu(self.hidden2(hidden))
        # Q-values are not probabilities: negative values must remain possible.
        q_values = self.output(hidden)
        return q_values
