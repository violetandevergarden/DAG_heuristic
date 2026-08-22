"""Legality and stable-state helpers for integrated policies."""

from __future__ import annotations

import hashlib

from core.execution.multi_resource import (
    MultiResourceAction,
    MultiResourceState,
    PreemptiveMultiResourceModel,
)
from core.execution.preemptive import ScheduleState
from muti_channel.preemptive.packing import validate_maximal_action


def state_fingerprint(state: ScheduleState | MultiResourceState) -> str:
    payload = repr(tuple((item.status, item.remaining) for item in state.tasks)).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def require_maximal(
    model: PreemptiveMultiResourceModel,
    state: MultiResourceState,
    action: MultiResourceAction,
) -> None:
    validate_maximal_action(model, state, action)
