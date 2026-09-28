"""The packing numbers of a research plan: how many tasks one sub-agent does in one run.

Code computes the numbers, and the skill `method_planner` renders them for the planner. The
planner then applies three integer steps (`sections_for`). A sub-agent runs until its
context reaches `PACKING_FRACTION` of the model's stated window. Its fixed cost is
`FIXED_TOKENS`, and each task of the request class costs the class value of
`CLASS_LEAF_TOKENS`. The class values are the packed cost of one leaf task at the median,
measured on stored runs.

`MAX_SECTIONS` is mirrored in the worker, as `MAX_PLAN_SECTIONS` in
`tasks/P_agent/run_budgets.py` and `MAX_SECTIONS` in `database/agent_plans.py`. The images
share no module, so the three change in one patch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Tuple

#: The share of the window that one sub-agent run fills.
PACKING_FRACTION = 0.60
#: The fixed cost of one sub-agent run: its system text, skills and opening message.
FIXED_TOKENS = 16_000
#: The most tasks of one sub-agent. It gives way when the plan has more tasks than 4 full
#: sub-agents hold.
LEAF_CAP = 10
#: The most sections of a plan, one sub-agent each.
MAX_SECTIONS = 4
#: The most correction sub-agents of a plan.
#: The window that packing uses when the catalogue states none.
DEFAULT_WINDOW = 262_144
#: Packed cost of one leaf task at the median, at 60 percent of the window, by request class.
#: A class with no value here counts at ALL_LEAF_TOKENS.
CLASS_LEAF_TOKENS = {"topic": 14_296, "review": 22_807, "person": 20_548}
ALL_LEAF_TOKENS = 20_520


@dataclass(frozen=True)
class Packing:
    classes: Tuple[str, ...]  # the kept request classes, at most 2
    leaf_tokens: int  # the cost of one task
    target_tokens: int  # PACKING_FRACTION of the window
    leaves_per_subagent: int  # 1 to LEAF_CAP


def leaf_tokens(classes: Iterable[str]) -> int:
    """The cost of one task: the largest cost of the classes, or ALL_LEAF_TOKENS."""
    return max((CLASS_LEAF_TOKENS.get(c, ALL_LEAF_TOKENS) for c in classes),
               default=ALL_LEAF_TOKENS)


def packing_for(classes: Iterable[str], window: int) -> Packing:
    """The packing of a plan for its request classes and the stated window of its model.

    A window of 0 or less uses DEFAULT_WINDOW.
    """
    kept = tuple(str(c) for c in classes)[:2]
    target = int((window if window > 0 else DEFAULT_WINDOW) * PACKING_FRACTION)
    m = leaf_tokens(kept)
    k = max(1, min(LEAF_CAP, (target - FIXED_TOKENS) // m))
    return Packing(kept, m, target, k)


def sections_for(leaves: int, k: int) -> List[int]:
    """The task count of each section, in order. The rule of the planner skill."""
    if leaves <= 0:
        return []
    n = min(MAX_SECTIONS, -(-leaves // max(1, k)))
    return [leaves // n + (1 if i < leaves % n else 0) for i in range(n)]


__all__ = [
    "ALL_LEAF_TOKENS", "CLASS_LEAF_TOKENS", "DEFAULT_WINDOW", "FIXED_TOKENS", "LEAF_CAP",
    "MAX_SECTIONS", "PACKING_FRACTION", "Packing", "leaf_tokens",
    "packing_for", "sections_for",
]
