"""Research snapshot failures that must stop materialization."""


class SnapshotIntegrityError(ValueError):
    """A snapshot artifact or manifest cannot satisfy its declared contract."""
