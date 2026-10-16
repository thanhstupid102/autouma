"""Game-calendar facts shared across scenarios, scoring and config defaults.

Dependency-free on purpose: `scenarios/base.py` imports `career_bot.events`, so a
calendar constant living in either of those would cycle. Everything here is an
immutable tuple; each consumer derives the shape it needs (set / frozenset /
JSON list) so there is exactly one place to edit when the game calendar changes.
"""

# Summer-camp turns (both years). Training/outing/bad-status rules key off these,
# and event scoring treats them as the high-energy-value window.
SUMMER_CAMP_TURNS: tuple[int, ...] = (37, 38, 39, 40, 61, 62, 63, 64)
