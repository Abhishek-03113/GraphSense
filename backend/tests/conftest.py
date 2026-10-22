import os

# Importing the app builds the database engine, which needs a DSN.  Nothing
# here connects (engines are lazy), so a placeholder is enough.
os.environ.setdefault("DATABASE_DSN", "postgresql+asyncpg://user:pass@localhost:5432/unused")
