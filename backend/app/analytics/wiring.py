from app.analytics.projections import ALL
from app.platform.replay import register


def wire() -> None:
    for projector in ALL:
        register(projector)
