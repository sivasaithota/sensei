"""Durable paper-only trading kernel."""

from .admission import KernelAdmissionAuthorization, KernelAdmissionAuthority
from .broker_authority import BrokerSnapshotAuthority, BrokerSnapshotEvidence
from .commands import (
    BrokerCommand,
    CancelEntryCommand,
    CommandKind,
    EntryCommand,
    ProtectionCommand,
)
from .gateway import GatewayReceipt, PaperGateway, RecordingPaperGateway
from .kernel import (
    ENTRY_DISPATCH_AUTHORIZATION_FACT_TYPE,
    EntryAuthorizationInvalid,
    EntryDispatchAuthorization,
    TradingKernel,
    entry_dispatch_authorization_fact,
)
from .reconciliation import (
    BrokerPosition,
    BrokerProtection,
    BrokerSnapshot,
    BrokerWorkingOrder,
    ReconciliationReport,
)

__all__ = [
    "BrokerCommand",
    "BrokerPosition",
    "BrokerProtection",
    "BrokerSnapshot",
    "BrokerSnapshotAuthority",
    "BrokerSnapshotEvidence",
    "BrokerWorkingOrder",
    "CancelEntryCommand",
    "CommandKind",
    "EntryCommand",
    "EntryAuthorizationInvalid",
    "ENTRY_DISPATCH_AUTHORIZATION_FACT_TYPE",
    "EntryDispatchAuthorization",
    "entry_dispatch_authorization_fact",
    "GatewayReceipt",
    "KernelAdmissionAuthorization",
    "KernelAdmissionAuthority",
    "PaperGateway",
    "ProtectionCommand",
    "RecordingPaperGateway",
    "ReconciliationReport",
    "TradingKernel",
]
