"""Unit tests for Stage 2 spatial voting."""
import uuid

from app.spatial_voter import vote_camera_pair

A1 = uuid.UUID(int=1)
A2 = uuid.UUID(int=2)
B1 = uuid.UUID(int=101)
B2 = uuid.UUID(int=102)

PARAMS = dict(
    vote_distance_threshold_m=1.0,
    min_vote_rate=0.6,
    min_votes=10,
    temporal_tolerance_ms=150,
    ambiguity_margin=0.15,
)


def _track(local_id, x, y, n=12, t0=1000, step=200):
    """n co-located detections for one local id."""
    return {local_id: [(t0 + i * step, x, y) for i in range(n)]}


def test_colocated_person_confirmed():
    obs_a = _track(A1, 5.0, 5.0)
    obs_b = _track(B1, 5.05, 5.0)  # within 1 m every frame
    confirmed, ambiguous = vote_camera_pair(obs_a, obs_b, **PARAMS)
    assert (A1, B1, 1.0) in confirmed
    assert ambiguous == set()


def test_far_apart_not_confirmed():
    obs_a = _track(A1, 0.0, 0.0)
    obs_b = _track(B1, 50.0, 50.0)  # co-visible but always > 1 m → zero votes
    confirmed, ambiguous = vote_camera_pair(obs_a, obs_b, **PARAMS)
    assert confirmed == set()
    assert ambiguous == set()  # vote_rate 0 → neither


def test_too_few_votes_not_confirmed():
    # Only 5 co-located frames < MIN_VOTES (10).
    obs_a = _track(A1, 1.0, 1.0, n=5)
    obs_b = _track(B1, 1.0, 1.0, n=5)
    confirmed, ambiguous = vote_camera_pair(obs_a, obs_b, **PARAMS)
    assert confirmed == set()


def test_temporal_offset_within_tolerance_still_votes():
    obs_a = {A1: [(1000 + i * 200, 2.0, 2.0) for i in range(12)]}
    obs_b = {B1: [(1100 + i * 200, 2.0, 2.0) for i in range(12)]}  # +100 ms < 150
    confirmed, _ = vote_camera_pair(obs_a, obs_b, **PARAMS)
    assert any(a == A1 and b == B1 for a, b, _ in confirmed)


def test_temporal_offset_beyond_tolerance_no_votes():
    obs_a = {A1: [(1000 + i * 1000, 2.0, 2.0) for i in range(12)]}
    obs_b = {B1: [(1500 + i * 1000, 2.0, 2.0) for i in range(12)]}  # +500 ms > 150
    confirmed, ambiguous = vote_camera_pair(obs_a, obs_b, **PARAMS)
    assert confirmed == set() and ambiguous == set()


def test_ambiguous_when_two_candidates_close():
    # A1 is ~equally close to B1 and B2 across frames → within-margin top two.
    ts = [1000 + i * 200 for i in range(12)]
    obs_a = {A1: [(t, 0.0, 0.0) for t in ts]}
    # B1 and B2 both within 1 m of A1 on alternating frames so vote_rates are close.
    obs_b = {
        B1: [(t, 0.1 if i % 2 == 0 else 5.0, 0.0) for i, t in enumerate(ts)],
        B2: [(t, 0.1 if i % 2 == 1 else 5.0, 0.0) for i, t in enumerate(ts)],
    }
    confirmed, ambiguous = vote_camera_pair(obs_a, obs_b, **PARAMS)
    # The assigned A1 pair should be flagged ambiguous, not auto-confirmed.
    assert any(a == A1 for a, _, _ in ambiguous)
    assert not any(a == A1 for a, _, _ in confirmed)


def test_empty_observations():
    assert vote_camera_pair({}, {A1: [(1, 0, 0)]}, **PARAMS) == (set(), set())
    assert vote_camera_pair({A1: [(1, 0, 0)]}, {}, **PARAMS) == (set(), set())
