from typing import Dict, List, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from src.domain.graph_models import Node, Edge, GraphSummaryResponse, GraphSubgraphResponse, GraphEntityResponse

class GraphRepository:
    """Repository to handle graph-based queries from the relational SAP O2C data."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _get_edges_union_query(self) -> str:
        """Constructs a UNION ALL query that derived graph edges from FK relationships."""
        return """
        -- Customer --> PLACED_ORDER --> SalesOrder
        SELECT 
            sold_to_party::text as source_id, 'Customer' as source_type,
            sales_order::text as target_id, 'SalesOrder' as target_type,
            'PLACED_ORDER' as type
        FROM sales_order_headers
        UNION ALL
        -- SalesOrder --> HAS_ITEM --> SalesOrderItem
        SELECT 
            sales_order::text as source_id, 'SalesOrder' as source_type,
            (sales_order || '-' || sales_order_item)::text as target_id, 'SalesOrderItem' as target_type,
            'HAS_ITEM' as type
        FROM sales_order_items
        UNION ALL
        -- SalesOrderItem --> CONTAINS_PRODUCT --> Product
        SELECT 
            (sales_order || '-' || sales_order_item)::text as source_id, 'SalesOrderItem' as source_type,
            material::text as target_id, 'Product' as target_type,
            'CONTAINS_PRODUCT' as type
        FROM sales_order_items
        UNION ALL
        -- SalesOrderItem --> PRODUCED_AT --> Plant
        SELECT 
            (sales_order || '-' || sales_order_item)::text as source_id, 'SalesOrderItem' as source_type,
            production_plant::text as target_id, 'Plant' as target_type,
            'PRODUCED_AT' as type
        FROM sales_order_items
        UNION ALL
        -- Delivery --> HAS_ITEM --> DeliveryItem
        SELECT 
            delivery_document::text as source_id, 'Delivery' as source_type,
            (delivery_document || '-' || delivery_document_item)::text as target_id, 'DeliveryItem' as target_type,
            'HAS_ITEM' as type
        FROM outbound_delivery_items
        UNION ALL
        -- DeliveryItem --> FULFILLS --> SalesOrderItem
        SELECT 
            (delivery_document || '-' || delivery_document_item)::text as source_id, 'DeliveryItem' as source_type,
            (reference_sd_document || '-' || reference_sd_document_item)::text as target_id, 'SalesOrderItem' as target_type,
            'FULFILLS' as type
        FROM outbound_delivery_items
        WHERE reference_sd_document IS NOT NULL
        UNION ALL
        -- BillingDocument --> HAS_ITEM --> BillingItem
        SELECT 
            billing_document::text as source_id, 'BillingDocument' as source_type,
            (billing_document || '-' || billing_document_item)::text as target_id, 'BillingItem' as target_type,
            'HAS_ITEM' as type
        FROM billing_document_items
        UNION ALL
        -- BillingItem --> BILLS_FOR --> DeliveryItem
        SELECT 
            (billing_document || '-' || billing_document_item)::text as source_id, 'BillingItem' as source_type,
            (reference_sd_document || '-' || reference_sd_document_item)::text as target_id, 'DeliveryItem' as target_type,
            'BILLS_FOR' as type
        FROM billing_document_items
        WHERE reference_sd_document IS NOT NULL
        UNION ALL
        -- BillingDocument --> SOLD_TO --> Customer
        SELECT 
            billing_document::text as source_id, 'BillingDocument' as source_type,
            sold_to_party::text as target_id, 'Customer' as target_type,
            'SOLD_TO' as type
        FROM billing_document_headers
        UNION ALL
        -- BillingDocument --> GENERATES_ENTRY --> JournalEntry
        SELECT 
            billing_document::text as source_id, 'BillingDocument' as source_type,
            accounting_document::text as target_id, 'JournalEntry' as target_type,
            'GENERATES_ENTRY' as type
        FROM billing_document_headers
        WHERE accounting_document IS NOT NULL
        UNION ALL
        -- JournalEntry --> RECEIVABLE_FROM --> Customer
        SELECT 
            accounting_document::text as source_id, 'JournalEntry' as source_type,
            customer::text as target_id, 'Customer' as target_type,
            'RECEIVABLE_FROM' as type
        FROM journal_entry_items_accounts_receivable
        UNION ALL
        -- Payment --> PAID_BY --> Customer
        SELECT 
            accounting_document::text as source_id, 'Payment' as source_type,
            customer::text as target_id, 'Customer' as target_type,
            'PAID_BY' as type
        FROM payments_accounts_receivable
        UNION ALL
        -- Payment --> CLEARED_BY --> JournalEntry
        SELECT 
            accounting_document::text as source_id, 'Payment' as source_type,
            clearing_accounting_document::text as target_id, 'JournalEntry' as target_type,
            'CLEARED_BY' as type
        FROM payments_accounts_receivable
        WHERE clearing_accounting_document IS NOT NULL
        """

    async def get_summary(self) -> GraphSummaryResponse:
        """Fetches counts for all node and edge types."""
        node_counts = {}
        tables = [
            ("sales_order_headers", "SalesOrder"),
            ("sales_order_items", "SalesOrderItem"),
            ("outbound_delivery_headers", "Delivery"),
            ("outbound_delivery_items", "DeliveryItem"),
            ("billing_document_headers", "BillingDocument"),
            ("billing_document_items", "BillingItem"),
            ("journal_entry_items_accounts_receivable", "JournalEntry"),
            ("payments_accounts_receivable", "Payment"),
            ("business_partners", "Customer"),
            ("products", "Product"),
            ("plants", "Plant")
        ]
        
        for table, node_type in tables:
            query = f"SELECT COUNT(*) FROM {table}"
            result = await self.db.execute(text(query))
            node_counts[node_type] = result.scalar()

        edge_counts = {}
        edges_union = self._get_edges_union_query()
        query = f"SELECT type, COUNT(*) FROM ({edges_union}) as all_edges GROUP BY type"
        result = await self.db.execute(text(query))
        for row in result:
            edge_counts[row[0]] = row[1]

        return GraphSummaryResponse(nodes=node_counts, edges=edge_counts)

    async def get_subgraph(self, root_type: str, root_id: str, depth: int) -> GraphSubgraphResponse:
        """Fetch nodes and edges reachable from a root ID within a certain depth."""
        edges_union = self._get_edges_union_query()
        
        # We'll create a bidirectional edge set first to simplify traversal
        # Then we use a single recursive step.
        subgraph_query = f"""
        WITH RECURSIVE graph_edges AS (
            {edges_union}
        ),
        bidirectional_edges AS (
            SELECT source_id, source_type, target_id, target_type, type FROM graph_edges
            UNION ALL
            SELECT target_id, target_type, source_id, source_type, type FROM graph_edges
        ),
        traversal(id, type, depth, path) AS (
            -- Seed
            SELECT :root_id, :root_type, 0, ARRAY[:root_id || ':' || :root_type]
            UNION ALL
            -- Single recursive step
            SELECT 
                be.target_id, be.target_type, t.depth + 1, t.path || (be.target_id || ':' || be.target_type)
            FROM bidirectional_edges be
            JOIN traversal t ON be.source_id = t.id AND be.source_type = t.type
            WHERE t.depth < :depth 
              AND NOT (be.target_id || ':' || be.target_type = ANY(t.path))
        )
        -- Finally, get all edges where both source and target are in the traversal set
        SELECT DISTINCT ge.source_id, ge.source_type, ge.target_id, ge.target_type, ge.type
        FROM graph_edges ge
        JOIN (SELECT DISTINCT id, type FROM traversal) t1 ON ge.source_id = t1.id AND ge.source_type = t1.type
        JOIN (SELECT DISTINCT id, type FROM traversal) t2 ON ge.target_id = t2.id AND ge.target_type = t2.type;
        """
        
        params = {"root_id": root_id, "root_type": root_type, "depth": depth}
        result = await self.db.execute(text(subgraph_query), params)
        
        nodes_map = {}
        final_edges = []
        
        # Initial root node (in case it has no edges)
        nodes_map[(root_type, root_id)] = Node(id=root_id, type=root_type, label=f"{root_type} {root_id}")
        
        for row in result:
            s_id, s_type, t_id, t_type, e_type = row
            
            # Populate Nodes
            if (s_type, s_id) not in nodes_map:
                nodes_map[(s_type, s_id)] = Node(id=s_id, type=s_type, label=f"{s_type} {s_id}")
            if (t_type, t_id) not in nodes_map:
                nodes_map[(t_type, t_id)] = Node(id=t_id, type=t_type, label=f"{t_type} {t_id}")
            
            final_edges.append(Edge(
                id=f"{s_id}-{t_id}-{e_type}",
                source=s_id,
                target=t_id,
                type=e_type
            ))
        
        return GraphSubgraphResponse(nodes=list(nodes_map.values()), edges=final_edges)

    async def get_entities(self, node_type: str, limit: int = 50) -> GraphEntityResponse:
        """Fetches a sample of entity IDs and labels for a given type."""
        type_to_table = {
            "SalesOrder": ("sales_order_headers", "sales_order"),
            "SalesOrderItem": ("sales_order_items", "sales_order || '-' || sales_order_item"),
            "Delivery": ("outbound_delivery_headers", "delivery_document"),
            "DeliveryItem": ("outbound_delivery_items", "delivery_document || '-' || delivery_document_item"),
            "BillingDocument": ("billing_document_headers", "billing_document"),
            "BillingItem": ("billing_document_items", "billing_document || '-' || billing_document_item"),
            "JournalEntry": ("journal_entry_items_accounts_receivable", "accounting_document"),
            "Payment": ("payments_accounts_receivable", "accounting_document"),
            "Customer": ("business_partners", "business_partner"),
            "Product": ("products", "product"),
            "Plant": ("plants", "plant")
        }
        
        if node_type not in type_to_table:
            return GraphEntityResponse(type=node_type, entities=[])
            
        table, id_col = type_to_table[node_type]
        query = f"SELECT DISTINCT {id_col}::text FROM {table} LIMIT :limit"
        result = await self.db.execute(text(query), {"limit": limit})
        
        entities = []
        for row in result:
            id_val = row[0]
            entities.append({"id": id_val, "label": f"{node_type} {id_val}"})
            
        return GraphEntityResponse(type=node_type, entities=entities)
