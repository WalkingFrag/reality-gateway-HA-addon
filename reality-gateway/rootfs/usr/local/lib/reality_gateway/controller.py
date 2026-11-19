"""Health state and priority selection for AWG3/VLESS egress."""

from dataclasses import dataclass, field

from .config import ExitSpec


@dataclass
class GatewayState:
    exits: tuple[ExitSpec, ...]
    current: str | None = None
    switched_at: float = 0.0
    healthy: dict[str, bool] = field(default_factory=dict)
    successes: dict[str, int] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)

    def record(self, exit_id: str, success: bool) -> None:
        if success:
            self.successes[exit_id] = self.successes.get(exit_id, 0) + 1
            self.failures[exit_id] = 0
            if self.successes[exit_id] >= 3:
                self.healthy[exit_id] = True
        else:
            self.failures[exit_id] = self.failures.get(exit_id, 0) + 1
            self.successes[exit_id] = 0
            if self.failures[exit_id] >= 3:
                self.healthy[exit_id] = False


def choose_exit(state: GatewayState, now: float) -> str | None:
    healthy = [exit for exit in state.exits if state.healthy.get(exit.id, False)]
    if not healthy:
        return None
    preferred = min(healthy, key=lambda exit: exit.priority).id
    if state.current and state.healthy.get(state.current, False):
        if state.current != preferred and now - state.switched_at < 120:
            return state.current
    return preferred
