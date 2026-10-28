from app.analytics.projections import ALL, NOT_PROJECTED
from app.platform.replay import not_projected, register


def wire() -> None:
    for projector in ALL:
        register(projector)
    for event_type, reason in NOT_PROJECTED.items():
        not_projected(event_type, reason)
