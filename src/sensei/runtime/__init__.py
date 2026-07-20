"""Production composition adapters for the governed paper runtime."""

from .account import PaperAccountProjectionError, PaperAccountProjector
from .adoption import (
    LegacyPositionAdoptionRegistry,
    LegacyPositionDrift,
    ReconciledLegacyPositionTruth,
)
from .session_inputs import (
    ComponentCheck,
    ComponentCheckResult,
    MarkPriceSource,
    PaperCycleBuilder,
    PaperSessionInputs,
    PaperSessionTruthError,
    PreparedPaperSession,
)
from .activation import (
    NseSurveillanceRefresher,
    RuntimeSecretStore,
    RuntimeTrustError,
    SurveillanceSourceUnavailable,
    VerifiedSurveillanceSource,
)
from .production import ProductionPaperSession

__all__ = [
    "ComponentCheck",
    "ComponentCheckResult",
    "MarkPriceSource",
    "LegacyPositionAdoptionRegistry",
    "LegacyPositionDrift",
    "PaperAccountProjectionError",
    "PaperAccountProjector",
    "PaperCycleBuilder",
    "PaperSessionInputs",
    "ProductionPaperSession",
    "NseSurveillanceRefresher",
    "RuntimeSecretStore",
    "RuntimeTrustError",
    "SurveillanceSourceUnavailable",
    "VerifiedSurveillanceSource",
    "PaperSessionTruthError",
    "PreparedPaperSession",
    "ReconciledLegacyPositionTruth",
]
