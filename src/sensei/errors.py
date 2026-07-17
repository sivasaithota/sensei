"""Cross-cutting, fail-closed exception contracts."""


class ActionableSchedulerError(RuntimeError):
    """A trusted failure whose reason code may be persisted by the scheduler."""

    reason_code = "TASK_HANDLER_FAILED"


__all__ = ["ActionableSchedulerError"]
