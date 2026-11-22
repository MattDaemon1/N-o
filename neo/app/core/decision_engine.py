"""Backward-compatible alias: DecisionEngine coordination lives directly in BehaviorEngine."""

from __future__ import annotations

from app.core.behavior_engine import BehaviorEngine, PostCheckResult, PreCheckResult

DecisionEngine = BehaviorEngine

__all__ = ["BehaviorEngine", "DecisionEngine", "PostCheckResult", "PreCheckResult"]
