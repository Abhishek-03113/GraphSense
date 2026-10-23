"""Storage: engines by role, the ``app`` schema tables, run records and dataset schema generations.

Dataset data lives in one PostgreSQL schema per dataset (``ds_<id>``) generated
from its package; application tables live in ``app``.  Nothing here knows what
a dataset contains.
"""
