import click
import asyncio
import os
from .jsonl_loader import ingest_data, init_db
import structlog

logger = structlog.get_logger()

@click.group()
def cli():
    pass

async def run_ingestion(data_dir: str, ddl_path: str, init: bool):
    if init:
        await init_db(ddl_path)
    await ingest_data(data_dir)

@cli.command()
@click.option("--data-dir", required=True, help="Path to the SAP O2C JSONL data directory")
@click.option("--ddl-path", default="../data modelling/ddl.sql", help="Path to the DDL SQL file")
@click.option("--init", is_flag=True, help="Initialize database with DDL before ingestion")
def ingest(data_dir: str, ddl_path: str, init: bool):
    """Run the data ingestion process."""
    asyncio.run(run_ingestion(data_dir, ddl_path, init))

if __name__ == "__main__":
    cli()
