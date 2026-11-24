"""Independent known-answer tests for standalone calculators in the Overview window."""

from __future__ import annotations

import pytest

from saengine import features

# ── Overview Dashboard (overview_dashboard.py: 4) ─────────────────────────────────────────────────


def test_overview_dashboard_create_alert() -> None:
    res = features.run(
        "overviewDashboard.createAlert",
        None,
        {"metric": "Open RFIs", "threshold": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["metric"] == "Open RFIs"
    assert res["summary"]["threshold"] == pytest.approx(5.0, rel=0.01)
    assert res["tables"][0]["rows"][0]["threshold"] == pytest.approx(5.0, rel=0.01)


def test_overview_dashboard_performance_score() -> None:
    # Equal-weight mean of (90, 75, 81) = 246 / 3 = 82.0%.
    res = features.run(
        "overviewDashboard.performanceScore",
        None,
        {"quality": 90.0, "schedule": 75.0, "safety": 81.0},
    )
    assert res["problems"] == []
    assert res["summary"]["score"] == pytest.approx(82.0, rel=0.01)


def test_overview_dashboard_set_threshold() -> None:
    res = features.run(
        "overviewDashboard.setThreshold",
        None,
        {"metric": "Drift ratio", "threshold": 0.02},
    )
    assert res["problems"] == []
    assert res["summary"]["metric"] == "Drift ratio"
    assert res["summary"]["threshold"] == pytest.approx(0.02, rel=0.01)


def test_overview_dashboard_variance_analysis() -> None:
    # actual = 120, target = 80 -> variance = +40, variancePercent = 40 / 80 * 100 = +50%.
    res = features.run(
        "overviewDashboard.varianceAnalysis",
        None,
        {"actual": 120.0, "target": 80.0},
    )
    assert res["problems"] == []
    assert res["summary"]["variance"] == pytest.approx(40.0, rel=0.01)
    assert res["summary"]["variancePercent"] == pytest.approx(50.0, rel=0.01)


# ── Overview Learning (overview_learning.py: 2) ───────────────────────────────────────────────────


def test_overview_learning_benchmarking_suite() -> None:
    res = features.run(
        "overviewLearning.benchmarkingSuite",
        None,
        {"warmupRuns": 3, "measuredRuns": 10},
    )
    assert res["problems"] == []
    assert res["summary"]["warmupRuns"] == pytest.approx(3.0, rel=0.01)
    assert res["summary"]["measuredRuns"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["networkAccess"] is False


def test_overview_learning_tip_of_day() -> None:
    # 4 tips in cyclic list; dayIndex = 5 -> 5 % 4 = 1 ("Save versions before major changes.").
    res = features.run("overviewLearning.tipOfDay", None, {"dayIndex": 5})
    assert res["problems"] == []
    assert res["summary"]["tipIndex"] == 1
    assert res["summary"]["tip"] == "Save versions before major changes."


# ── Overview Tasks (overview_tasks.py: 6) ─────────────────────────────────────────────────────────


def test_overview_tasks_alert_rules() -> None:
    res = features.run(
        "overviewTasks.alertRules",
        None,
        {"metric": "Overdue tasks", "threshold": 3.0},
    )
    assert res["problems"] == []
    assert res["summary"]["metric"] == "Overdue tasks"
    assert res["summary"]["threshold"] == pytest.approx(3.0, rel=0.01)
    assert res["tables"][0]["rows"][0]["threshold"] == pytest.approx(3.0, rel=0.01)


def test_overview_tasks_baseline_target() -> None:
    res = features.run("overviewTasks.baselineTarget", None, {"target": 92.5})
    assert res["problems"] == []
    assert res["summary"]["baselineTarget"] == pytest.approx(92.5, rel=0.01)
    assert res["tables"][0]["rows"][0]["target"] == pytest.approx(92.5, rel=0.01)


def test_overview_tasks_capacity_planner() -> None:
    # capacity = 200 h, required = 250 h -> utilisation = 250 / 200 = 1.25, shortfall = 50.0 h.
    res = features.run(
        "overviewTasks.capacityPlanner",
        None,
        {"capacity": 200.0, "required": 250.0},
    )
    assert res["problems"] == []
    assert res["summary"]["utilisation"] == pytest.approx(1.25, rel=0.01)
    assert res["summary"]["shortfallHours"] == pytest.approx(50.0, rel=0.01)


def test_overview_tasks_priority_matrix() -> None:
    # High impact (5 >= 4) and low effort (2 <= 2) -> P1; high impact (4) and high effort (4) -> P2.
    res_p1 = features.run("overviewTasks.priorityMatrix", None, {"impact": 5.0, "effort": 2.0})
    res_p2 = features.run("overviewTasks.priorityMatrix", None, {"impact": 4.0, "effort": 4.0})
    assert res_p1["problems"] == []
    assert res_p1["summary"]["priority"] == "P1"
    assert res_p2["summary"]["priority"] == "P2"


def test_overview_tasks_resource_allocator() -> None:
    res = features.run(
        "overviewTasks.resourceAllocator",
        None,
        {"resource": "Senior Structural Engineer", "hours": 32.0},
    )
    assert res["problems"] == []
    assert res["summary"]["resource"] == "Senior Structural Engineer"
    assert res["summary"]["hours"] == pytest.approx(32.0, rel=0.01)


def test_overview_tasks_task_reminders() -> None:
    res = features.run(
        "overviewTasks.taskReminders",
        None,
        {"task": "Submit foundation drawings", "leadDays": 7.0},
    )
    assert res["problems"] == []
    assert res["summary"]["task"] == "Submit foundation drawings"
    assert res["summary"]["leadDays"] == pytest.approx(7.0, rel=0.01)
