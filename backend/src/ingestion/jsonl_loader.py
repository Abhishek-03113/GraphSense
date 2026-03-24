import json
import os
import asyncio
from typing import List, Type, Any
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
import structlog

from ..db.session import engine, async_session, Base
from ..db import models
from . import schemas

logger = structlog.get_logger()

# Map directory names (entities) to (SQLAlchemy Model, Pydantic Schema)
ENTITY_MAP = {
    "billing_document_headers": (models.BillingDocumentHeader, schemas.BillingDocumentHeaderSchema),
    "billing_document_cancellations": (models.BillingDocumentCancellation, schemas.BillingDocumentCancellationSchema),
    "billing_document_items": (models.BillingDocumentItem, schemas.BillingDocumentItemSchema),
    "business_partner_addresses": (models.BusinessPartnerAddress, schemas.BusinessPartnerAddressSchema),
    "business_partners": (models.BusinessPartner, schemas.BusinessPartnerSchema),
    "customer_company_assignments": (models.CustomerCompanyAssignment, schemas.CustomerCompanyAssignmentSchema),
    "customer_sales_area_assignments": (models.CustomerSalesAreaAssignment, schemas.CustomerSalesAreaAssignmentSchema),
    "journal_entry_items_accounts_receivable": (models.JournalEntryItemAccountsReceivable, schemas.JournalEntryItemAccountsReceivableSchema),
    "outbound_delivery_headers": (models.OutboundDeliveryHeader, schemas.OutboundDeliveryHeaderSchema),
    "outbound_delivery_items": (models.OutboundDeliveryItem, schemas.OutboundDeliveryItemSchema),
    "payments_accounts_receivable": (models.PaymentAccountsReceivable, schemas.PaymentAccountsReceivableSchema),
    "plants": (models.Plant, schemas.PlantSchema),
    "product_descriptions": (models.ProductDescription, schemas.ProductDescriptionSchema),
    "product_plants": (models.ProductPlant, schemas.ProductPlantSchema),
    "product_storage_locations": (models.ProductStorageLocation, schemas.ProductStorageLocationSchema),
    "products": (models.Product, schemas.ProductSchema),
    "sales_order_headers": (models.SalesOrderHeader, schemas.SalesOrderHeaderSchema),
    "sales_order_items": (models.SalesOrderItem, schemas.SalesOrderItemSchema),
    "sales_order_schedule_lines": (models.SalesOrderScheduleLine, schemas.SalesOrderScheduleLineSchema),
}

async def init_db(ddl_path: str):
    """Initialize database using the provided DDL file."""
    logger.info("Initializing database with DDL", path=ddl_path)
    async with engine.begin() as conn:
        with open(ddl_path, "r") as f:
            ddl_sql = f.read()
            # Remove single-line comments
            lines = [line for line in ddl_sql.splitlines() if not line.strip().startswith("--")]
            clean_sql = "\n".join(lines)
            
            # Split by semicolon and execute non-empty statements
            statements = clean_sql.split(";")
            for stmt in statements:
                stmt = stmt.strip()
                if stmt:
                    await conn.execute(text(stmt))

async def load_jsonl_file(file_path: str, schema_cls: Type[BaseModel]) -> List[dict]:
    """Read and validate JSONL file."""
    records = []
    with open(file_path, "r") as f:
        for line in f:
            data = json.loads(line)
            validated = schema_cls(**data)
            records.append(validated.model_dump())
    return records

async def upsert_records(session: AsyncSession, model: Type[Base], records: List[dict], batch_size: int = 1000):
    """Perform bulk UPSERT into PostgreSQL with batching."""
    if not records:
        return

    # Get primary key columns
    pk_cols = [c.name for c in model.__table__.primary_key.columns]
    # Build update dict (all columns except PKs)
    update_dict = {
        c.name: insert(model).excluded[c.name]
        for c in model.__table__.columns
        if c.name not in pk_cols
    }

    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        stmt = insert(model).values(batch)
        
        if update_dict:
            stmt = stmt.on_conflict_do_update(
                index_elements=pk_cols,
                set_=update_dict
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=pk_cols)
            
        await session.execute(stmt)

async def ingest_data(data_dir: str):
    """Core ingestion loop."""
    logger.info("Starting data ingestion", data_dir=data_dir)
    
    for entity_dir, (model, schema) in ENTITY_MAP.items():
        dir_path = os.path.join(data_dir, entity_dir)
        if not os.path.exists(dir_path):
            logger.warning("Entity directory missing", entity=entity_dir, path=dir_path)
            continue
            
        for file_name in os.listdir(dir_path):
            if file_name.endswith(".jsonl"):
                file_path = os.path.join(dir_path, file_name)
                logger.info("Processing file", entity=entity_dir, file=file_name)
                
                records = await load_jsonl_file(file_path, schema)
                
                async with async_session() as session:
                    async with session.begin():
                        await upsert_records(session, model, records)
                        
    logger.info("Data ingestion completed successfully")
