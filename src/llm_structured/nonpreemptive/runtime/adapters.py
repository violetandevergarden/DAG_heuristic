"""Single- and fixed-multi-resource adapters over the public simulators."""

from __future__ import annotations

from core.conversion import to_internal_dag, to_multi_resource_instance
from core.execution.nonpreemptive import Action, NonPreemptiveDAGModel
from core.trace.nonpreemptive import assert_nonpreemptive_trace
from muti_channel.nonpreemptive.replay import replay_actions
from muti_channel.nonpreemptive.solver import NonPreemptiveMultiResourceDAG, ResourceAction

from .contracts import ActionSignature, Mode, ReplaySummary
from .features import single_residual_tail


class SingleAdapter:
    resource_model = "single_channel"

    def __init__(self, benchmark):
        self.model = NonPreemptiveDAGModel(to_internal_dag(benchmark))

    def initial_state(self):
        return self.model.initial_state()

    def is_finished(self, state):
        return self.model.is_finished(state)

    def legal_actions(self, state, mode: Mode):
        actions = self.model.legal_actions(state)
        return (
            tuple(a for a in actions if a.kind != "wait")
            if mode == "work_conserving" and self.model.ready_flows(state)
            else actions
        )

    def step(self, state, action):
        return self.model.step(state, action)

    def signature(self, state, action):
        next_time = None
        if action.kind == "wait":
            active = self.model.active_computes(state)
            next_time = state.time + min(
                self.model.task_runtime(state, item).remaining for item in active
            )
        return ActionSignature(
            action.kind, () if action.task_id is None else (action.task_id,), next_time
        )

    def action_from_signature(self, signature):
        return Action.wait() if signature.kind == "wait" else Action.flow(signature.task_ids[0])

    def active_context(self, state):
        return (), (), ("channel:0",)

    def duration(self, state, action):
        return (
            self.step(state, action).after.time - state.time
            if action.kind == "wait"
            else self.model.tasks[self.model.index[action.task_id]].duration
        )

    def next_event_distance(self, state):
        return min(
            (
                self.model.task_runtime(state, item).remaining
                for item in self.model.active_computes(state)
            ),
            default=10**18,
        )

    def resources(self, action):
        return frozenset({"channel:0"}) if action.kind != "wait" else frozenset()

    def resource_coverage(self, action):
        return len(self.resources(action))

    def ready_flow_ids(self, state):
        return frozenset(self.model.ready_flows(state))

    def tail(self, state):
        return single_residual_tail(self.model, state)

    def replay(self, actions):
        trace = self.model.run(actions)
        assert self.model.is_finished(trace.final_state)
        assert_nonpreemptive_trace(trace)
        vw = vwt = fw = fwt = 0
        for transition in trace.transitions:
            if transition.action.kind != "wait":
                continue
            delta = transition.after.time - transition.before.time
            if self.model.ready_flows(transition.before):
                vw += 1
                vwt += delta
            else:
                fw += 1
                fwt += delta
        return ReplaySummary(trace.makespan, True, vw, vwt, fw, fwt)


class MultiAdapter:
    resource_model = "fixed_multi_resource"

    def __init__(self, benchmark):
        self.model = NonPreemptiveMultiResourceDAG(to_multi_resource_instance(benchmark))

    def initial_state(self):
        return self.model.initial_state()

    def is_finished(self, state):
        return self.model.is_finished(state)

    def legal_actions(self, state, mode: Mode):
        return self.model.legal_actions(state, mode)

    def step(self, state, action):
        return self.model.step(state, action)

    def signature(self, state, action):
        next_time = (
            state.time
            + min(
                (runtime.remaining for runtime in state.tasks if runtime.status == "running"),
                default=0,
            )
            if action.kind == "wait"
            else None
        )
        return ActionSignature(action.kind, action.starts, next_time)

    def action_from_signature(self, signature):
        return (
            ResourceAction.wait()
            if signature.kind == "wait"
            else ResourceAction.start(signature.task_ids)
        )

    def active_context(self, state):
        occupied = tuple(sorted(map(str, self.model.occupied_resources(state))))
        all_resources = {str(item) for group in self.model.resources for item in group}
        return (
            self.model.active_flows(state),
            occupied,
            tuple(sorted(all_resources - set(occupied))),
        )

    def duration(self, state, action):
        return self.step(state, action).after.time - state.time

    def next_event_distance(self, state):
        return min(
            (runtime.remaining for runtime in state.tasks if runtime.status == "running"),
            default=10**18,
        )

    def resources(self, action):
        return (
            frozenset()
            if action.kind == "wait"
            else frozenset(
                resource
                for item in action.starts
                for resource in self.model.resources[self.model.index[item]]
            )
        )

    def resource_coverage(self, action):
        return len(self.resources(action))

    def ready_flow_ids(self, state):
        return frozenset(self.model.ready_flows(state))

    def tail(self, state):
        _path, values = self.model.residual_features(state)
        return {task.task_id: values[index] for index, task in enumerate(self.model.tasks)}

    def replay(self, actions):
        result = replay_actions(self.model, actions, runtime_ms=0.0)
        return ReplaySummary(
            result.makespan,
            True,
            result.voluntary_waits,
            result.voluntary_wait_time,
            result.forced_waits,
            result.forced_wait_time,
        )


def make_adapter(benchmark):
    return (
        SingleAdapter(benchmark)
        if benchmark.scenario == "single_channel"
        else MultiAdapter(benchmark)
    )
