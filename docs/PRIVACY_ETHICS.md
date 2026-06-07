<!--
  Rubric: P4 (value/publishability) — ethics dimension, also useful for Q&A defense
-->

# Privacy and ethics — RetailVision

## 1. Data collected

| Data type | Stored? | Retention | Access |
|---|---|---|---|
| Raw video frames | TODO (thumbnails only via presigned URLs?) | TODO | Store staff only |
| ReID embeddings (OSNet vectors) | Yes (local_centroids, global_embeddings) | TODO | Internal only |
| Floor trajectories | Yes (tracking_history, global_tracking_history) | TODO | Store staff only |
| Personal identity (name, face) | **No** | N/A | N/A |

## 2. Privacy by design decisions

- Raw frames are NOT streamed to the cloud continuously — only metadata crosses the network
- No facial recognition is used — ReID uses body appearance, not face identity
- No personally identifiable information (PII) is stored — global_id is an anonymous token
- TODO: Is there a data retention policy? When are trajectories deleted?

## 3. GDPR / regulatory considerations

<!-- TODO: Does this system need to comply with GDPR?
     - Is the store in the EU?
     - Do trajectory embeddings count as biometric data under GDPR?
     - Is there a right-to-erasure mechanism?
     - Is there a privacy notice for store visitors? -->

## 4. Bias and fairness

<!-- TODO: Could the OSNet ReID model perform differently across demographic groups?
     - Is the OSNet model trained on diverse datasets?
     - Could poor lighting (affecting certain skin tones more) cause ReID failures?
     - How would you detect this in production? -->

## 5. Human oversight

<!-- TODO: Are there decisions made by the system that a human should review?
     - Occupancy alerts: human confirms before acting
     - Identity merges: are they ever reviewed? -->
