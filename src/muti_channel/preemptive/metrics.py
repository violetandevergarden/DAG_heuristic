"""Trace metrics for the generic fixed-resource preemptive family."""

from __future__ import annotations

from statistics import mean

from core.execution.preemptive import MultiResourceTrace


def multi_resource_statistics(
    trace: MultiResourceTrace,
    resources: dict[str, frozenset[str]],
) -> dict[str, object]:
    busy: dict[str, int] = {}
    for interval in trace.resource_intervals:
        busy[interval.resource_id] = busy.get(interval.resource_id, 0) + interval.end - interval.start
    all_resources = sorted({resource for values in resources.values() for resource in values})
    utilization = {
        resource: (busy.get(resource, 0) / trace.makespan if trace.makespan else 0.0)
        for resource in all_resources
    }
    set_sizes = [len(decision.action.communications) for decision in trace.decisions]
    return {
        "resource_busy": {item: busy.get(item, 0) for item in all_resources},
        "resource_utilization": utilization,
        "hotspot_utilization": max(utilization.values(), default=0.0),
        "unused_resources": sum(value == 0 for value in busy.values()) + sum(item not in busy for item in all_resources),
        "mean_set_size": mean(set_sizes) if set_sizes else 0.0,
        "max_set_size": max(set_sizes, default=0),
        "forced_idle_time": sum(item.end - item.start for item in trace.forced_idle),
        "forced_idle_count": len(trace.forced_idle),
    }


__all__ = ["multi_resource_statistics"]
