from prometheus_client import Counter, Gauge

EEP_ACTIVE_CAMERAS = Gauge(
    "eep_active_cameras",
    "Number of camera configs currently marked running by EEP",
)

EEP_SCHEDULER_TICKS = Counter(
    "eep_scheduler_ticks_total",
    "Completed camera scheduler evaluations",
)

EEP_GRPC_CONNECTIONS = Gauge(
    "eep_grpc_connections_active",
    "Number of Edge Agent gRPC streams currently connected to EEP",
)
