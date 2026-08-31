"""Thin adapters; all state transitions remain owned by public simulators."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.conversion import to_internal_dag, to_multi_resource_instance
from core.execution.nonpreemptive import Action, NonPreemptiveDAGModel
from core.trace.nonpreemptive import assert_nonpreemptive_trace
from muti_channel.nonpreemptive.solver import (
    NonPreemptiveMultiResourceDAG, ResourceAction, _replay,
)

from .contracts import ActionSignature, Mode


@dataclass(frozen=True)
class ReplaySummary:
    makespan: int
    trace_valid: bool
    voluntary_waits: int
    voluntary_wait_time: int
    forced_waits: int
    forced_wait_time: int


class SingleAdapter:
    resource_model = "single_channel"

    def __init__(self, benchmark):
        self.model = NonPreemptiveDAGModel(to_internal_dag(benchmark))

    def initial_state(self): return self.model.initial_state()
    def is_finished(self, state): return self.model.is_finished(state)
    def legal_actions(self, state, mode: Mode):
        actions = self.model.legal_actions(state)
        if mode == "work_conserving" and self.model.ready_flows(state):
            actions = tuple(a for a in actions if a.kind != "wait")
        return actions
    def step(self, state, action): return self.model.step(state, action)
    def signature(self, state, action):
        next_time = None
        if action.kind == "wait":
            active = self.model.active_computes(state)
            next_time = state.time + min(self.model.task_runtime(state, x).remaining for x in active)
        return ActionSignature(action.kind, (() if action.task_id is None else (action.task_id,)), next_time)
    def action_from_signature(self, signature):
        return Action.wait() if signature.kind == "wait" else Action.flow(signature.task_ids[0])
    def active_context(self, state): return (), (), ("channel:0",)
    def duration(self, state, action):
        if action.kind == "wait": return self.step(state, action).after.time - state.time
        return self.model.tasks[self.model.index[action.task_id]].duration
    def tail(self, state):
        children = [[] for _ in self.model.tasks]
        for child, parents in enumerate(self.model.deps):
            for parent in parents: children[parent].append(child)
        values = [0] * len(children)
        for i in reversed(range(len(children))):
            rt = state.tasks[i]
            duration = 0 if rt.status == "completed" else (rt.remaining if rt.status == "running" else self.model.tasks[i].duration)
            values[i] = duration + max((values[c] for c in children[i]), default=0)
        return {task.task_id: values[i] for i, task in enumerate(self.model.tasks)}
    def replay(self, actions):
        trace = self.model.run(actions)
        assert self.model.is_finished(trace.final_state)
        assert_nonpreemptive_trace(trace)
        vw = vwt = fw = fwt = 0
        for transition in trace.transitions:
            if transition.action.kind != "wait": continue
            delta = transition.after.time - transition.before.time
            if self.model.ready_flows(transition.before): vw += 1; vwt += delta
            else: fw += 1; fwt += delta
        return ReplaySummary(trace.makespan, True, vw, vwt, fw, fwt)


class MultiAdapter:
    resource_model = "fixed_multi_resource"

    def __init__(self, benchmark):
        self.model = NonPreemptiveMultiResourceDAG(to_multi_resource_instance(benchmark))

    def initial_state(self): return self.model.initial_state()
    def is_finished(self, state): return self.model.is_finished(state)
    def legal_actions(self, state, mode: Mode): return self.model.legal_actions(state, mode)
    def step(self, state, action): return self.model.step(state, action)
    def signature(self, state, action):
        next_time = state.time + min((r.remaining for r in state.tasks if r.status == "running"), default=0) if action.kind == "wait" else None
        return ActionSignature(action.kind, action.starts, next_time)
    def action_from_signature(self, signature):
        return ResourceAction.wait() if signature.kind == "wait" else ResourceAction.start(signature.task_ids)
    def active_context(self, state):
        occupied = tuple(sorted(map(str, self.model.occupied_resources(state))))
        all_resources = {str(x) for group in self.model.resources for x in group}
        return self.model.active_flows(state), occupied, tuple(sorted(all_resources - set(occupied)))
    def duration(self, state, action): return self.step(state, action).after.time - state.time
    def tail(self, state):
        _path, values = self.model.residual_features(state)
        return {task.task_id: values[i] for i, task in enumerate(self.model.tasks)}
    def replay(self, actions):
        result = _replay(self.model, actions, runtime_ms=0.0)
        return ReplaySummary(result.makespan, True, result.voluntary_waits, result.voluntary_wait_time, result.forced_waits, result.forced_wait_time)


def make_adapter(benchmark) -> Any:
    return SingleAdapter(benchmark) if benchmark.scenario == "single_channel" else MultiAdapter(benchmark)

