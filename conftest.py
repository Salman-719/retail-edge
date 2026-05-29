"""Root conftest. Its presence makes pytest add the repo root to sys.path, so
tests can import the shared package (`from common...`) and the service packages
(`from services.iep2_vision.app...`)."""
