"""Shared fixtures for EEP unit tests.

Adds the EEP service and the mlops directory to sys.path so imports resolve
without a pip install of either package.
"""
import sys
import os

# EEP service root — makes `from app.core.shadow import ...` work.
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..", "..",
                 "services", "eep"),
)

# mlops root — makes `import compare_shadow` work.
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..", "..",
                 "mlops"),
)
