from prometheus_client import Counter, Gauge

EEP_ACTIVE_CAMERAS = Gauge(
    "eep_active_cameras",
    "Number of (store_id, camera_config_id) pairs currently in the running state",
)

EEP_SCHEDULER_TICKS = Counter(
    "eep_scheduler_ticks_total",
    "Total number of evaluate_schedules() invocations completed by APScheduler",
)

EEP_GRPC_CONNECTIONS = Gauge(
    "eep_grpc_connections_active",
    "Number of Edge Agent gRPC streams currently connected to EEP",
)
