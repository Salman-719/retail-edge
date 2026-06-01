# Vision Event Contracts v1

These JSON schemas define the event boundary around live vision ingestion.
Marji's production path consumes `vision.frame_ref.v1` in IAIP2, writes local
track state to the Domain 9 database tables, and lets IEP3 perform global ReID
from synchronized batch-complete events. The local/global observation schemas
remain available for external subscribers or future Redpanda-first persistence.

Topics:

- `vision.frame_ref.v1`: IAIP1 publishes timestamped frame or segment references.
- `vision.local_track_observed.v1`: optional per-camera local-track observation event.
- `vision.global_identity_observed.v1`: optional global identity observation event.

Partitioning:

- `vision.frame_ref.v1` and `vision.local_track_observed.v1` should be keyed by
  `camera_id`.
- `vision.global_identity_observed.v1` should be keyed by `section_id` when used,
  because v1 uses one global identity space per EEP section.
