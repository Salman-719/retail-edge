# Import all domain model modules so SQLAlchemy mapper sees every table
# when Base.metadata.create_all() is called.
from app.models import store, zone, camera, employee  # noqa: F401
