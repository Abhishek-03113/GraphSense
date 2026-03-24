from typing import Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from src.domain.graph_models import Node, Edge, GraphSummaryResponse, GraphSubgraphResponse, GraphEntityResponse
from src.domain.flow_definitions import FLOW_DEFINITIONS


# ---------------------------------------------------------------------------
# O2C Graph Model
# ---------------------------------------------------------------------------
#
# NODE TYPES (11)
# ────────────────────────────────────────────────────────────────────────────
#  Core flow   : Customer, SalesOrder, SalesOrderItem,
#                Delivery, DeliveryItem,
#                Invoice, InvoiceItem,
#                JournalEntry, Payment
#  Supporting  : Product, Address
#
# EDGE TYPES (11)  — direction follows business causality
# ────────────────────────────────────────────────────────────────────────────
#  Customer       --[PLACED]---------> SalesOrder
#  SalesOrder     --[HAS_ITEM]-------> SalesOrderItem
#  SalesOrderItem --[INCLUDES]-------> Product
#
#  Delivery       --[HAS_ITEM]-------> DeliveryItem
#  DeliveryItem   --[FULFILLS]-------> SalesOrderItem    ← cross-doc link
#
#  Invoice        --[HAS_ITEM]-------> InvoiceItem
#  InvoiceItem    --[BILLS_FOR]------> DeliveryItem      ← cross-doc link
#  Invoice        --[BILLED_TO]------> Customer
#
#  Invoice        --[GENERATES]------> JournalEntry
#  Payment        --[CLEARS]---------> JournalEntry
#
#  Customer       --[HAS_ADDRESS]----> Address
#
# FULL TRACE (Sales Order → Delivery → Billing → Journal Entry)
# ────────────────────────────────────────────────────────────────────────────
#  Start at any Invoice node (depth ≥ 2):
#  Invoice → HAS_ITEM → InvoiceItem → BILLS_FOR → DeliveryItem
#          ← HAS_ITEM ← Delivery
#  DeliveryItem → FULFILLS → SalesOrderItem ← HAS_ITEM ← SalesOrder
#                                            ← PLACED ← Customer
#  Invoice → GENERATES → JournalEntry ← CLEARS ← Payment
# ---------------------------------------------------------------------------


class GraphRepository:
    """Repository for graph queries over the SAP O2C relational dataset."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Edge derivation
    # ------------------------------------------------------------------

    def _get_edges_union_query(self) -> str:
        """
        Derives all graph edges from foreign-key relationships in the schema.
        Each UNION ALL block represents one edge type in the O2C graph model.
        """
        return """
        -- ── Customer --[PLACED]--> SalesOrder ──────────────────────────────
        SELECT
            soh.sold_to_party::text   AS source_id,
            'Customer'::text          AS source_type,
            soh.sales_order::text     AS target_id,
            'SalesOrder'::text        AS target_type,
            'PLACED'::text            AS type
        FROM sales_order_headers soh
        WHERE soh.sold_to_party IS NOT NULL

        UNION ALL

        -- ── SalesOrder --[HAS_ITEM]--> SalesOrderItem ────────────────────
        SELECT
            soi.sales_order::text                                     AS source_id,
            'SalesOrder'::text                                        AS source_type,
            (soi.sales_order || '-' || soi.sales_order_item)::text    AS target_id,
            'SalesOrderItem'::text                                    AS target_type,
            'HAS_ITEM'::text                                          AS type
        FROM sales_order_items soi

        UNION ALL

        -- ── SalesOrderItem --[INCLUDES]--> Product ───────────────────────
        SELECT
            (soi.sales_order || '-' || soi.sales_order_item)::text    AS source_id,
            'SalesOrderItem'::text                                    AS source_type,
            soi.material::text                                        AS target_id,
            'Product'::text                                           AS target_type,
            'INCLUDES'::text                                          AS type
        FROM sales_order_items soi
        WHERE soi.material IS NOT NULL

        UNION ALL

        -- ── Delivery --[HAS_ITEM]--> DeliveryItem ────────────────────────
        SELECT
            odi.delivery_document::text                                             AS source_id,
            'Delivery'::text                                                        AS source_type,
            (odi.delivery_document || '-' || odi.delivery_document_item)::text      AS target_id,
            'DeliveryItem'::text                                                    AS target_type,
            'HAS_ITEM'::text                                                        AS type
        FROM outbound_delivery_items odi

        UNION ALL

        -- ── DeliveryItem --[FULFILLS]--> SalesOrderItem ──────────────────
        -- Cross-document link: ties delivery fulfilment back to the sales order item
        SELECT
            (odi.delivery_document || '-' || odi.delivery_document_item)::text      AS source_id,
            'DeliveryItem'::text                                                    AS source_type,
            (odi.reference_sd_document || '-' || odi.reference_sd_document_item)::text  AS target_id,
            'SalesOrderItem'::text                                                  AS target_type,
            'FULFILLS'::text                                                        AS type
        FROM outbound_delivery_items odi
        WHERE odi.reference_sd_document IS NOT NULL

        UNION ALL

        -- ── Invoice --[HAS_ITEM]--> InvoiceItem ──────────────────────────
        SELECT
            bdi.billing_document::text                                              AS source_id,
            'Invoice'::text                                                         AS source_type,
            (bdi.billing_document || '-' || bdi.billing_document_item)::text        AS target_id,
            'InvoiceItem'::text                                                     AS target_type,
            'HAS_ITEM'::text                                                        AS type
        FROM billing_document_items bdi

        UNION ALL

        -- ── InvoiceItem --[BILLS_FOR]--> DeliveryItem ────────────────────
        -- Cross-document link: ties billing line back to the delivery item it covers
        SELECT
            (bdi.billing_document || '-' || bdi.billing_document_item)::text        AS source_id,
            'InvoiceItem'::text                                                     AS source_type,
            (bdi.reference_sd_document || '-' || bdi.reference_sd_document_item)::text  AS target_id,
            'DeliveryItem'::text                                                    AS target_type,
            'BILLS_FOR'::text                                                       AS type
        FROM billing_document_items bdi
        WHERE bdi.reference_sd_document IS NOT NULL

        UNION ALL

        -- ── Invoice --[BILLED_TO]--> Customer ────────────────────────────
        SELECT
            bdh.billing_document::text  AS source_id,
            'Invoice'::text             AS source_type,
            bdh.sold_to_party::text     AS target_id,
            'Customer'::text            AS target_type,
            'BILLED_TO'::text           AS type
        FROM billing_document_headers bdh
        WHERE bdh.sold_to_party IS NOT NULL

        UNION ALL

        -- ── Invoice --[GENERATES]--> JournalEntry ────────────────────────
        -- The accounting document created when a billing document is posted
        SELECT
            bdh.billing_document::text      AS source_id,
            'Invoice'::text                 AS source_type,
            bdh.accounting_document::text   AS target_id,
            'JournalEntry'::text            AS target_type,
            'GENERATES'::text               AS type
        FROM billing_document_headers bdh
        WHERE bdh.accounting_document IS NOT NULL

        UNION ALL

        -- ── Payment --[CLEARS]--> JournalEntry ───────────────────────────
        -- A payment clears the open receivable journal entry
        SELECT DISTINCT
            par.accounting_document::text           AS source_id,
            'Payment'::text                         AS source_type,
            par.clearing_accounting_document::text  AS target_id,
            'JournalEntry'::text                    AS target_type,
            'CLEARS'::text                          AS type
        FROM payments_accounts_receivable par
        WHERE par.clearing_accounting_document IS NOT NULL

        UNION ALL

        -- ── Customer --[HAS_ADDRESS]--> Address ──────────────────────────
        SELECT
            bpa.business_partner::text                              AS source_id,
            'Customer'::text                                        AS source_type,
            (bpa.business_partner || '-' || bpa.address_id)::text   AS target_id,
            'Address'::text                                         AS target_type,
            'HAS_ADDRESS'::text                                     AS type
        FROM business_partner_addresses bpa
        """

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    async def get_summary(self) -> GraphSummaryResponse:
        """Returns node and edge counts for every type in the graph."""
        node_tables = [
            # Core flow
            ("sales_order_headers",                                         "SalesOrder"),
            ("sales_order_items",                                           "SalesOrderItem"),
            ("outbound_delivery_headers",                                   "Delivery"),
            ("outbound_delivery_items",                                     "DeliveryItem"),
            ("billing_document_headers",                                    "Invoice"),
            ("billing_document_items",                                      "InvoiceItem"),
            # JournalEntry and Payment are multi-row-per-document tables;
            # count distinct document IDs so the number reflects unique entities.
            ("(SELECT DISTINCT accounting_document FROM journal_entry_items_accounts_receivable)", "JournalEntry"),
            ("(SELECT DISTINCT accounting_document FROM payments_accounts_receivable)",            "Payment"),
            # Supporting
            ("products",                                                    "Product"),
            ("business_partners",                                           "Customer"),
            ("business_partner_addresses",                                  "Address"),
        ]

        node_counts: Dict[str, int] = {}
        for table, node_type in node_tables:
            result = await self.db.execute(text(f"SELECT COUNT(*) FROM {table} AS _t"))
            node_counts[node_type] = result.scalar()

        edges_union = self._get_edges_union_query()
        result = await self.db.execute(
            text(f"SELECT type, COUNT(*) FROM ({edges_union}) AS all_edges GROUP BY type ORDER BY type")
        )
        edge_counts: Dict[str, int] = {row[0]: row[1] for row in result}

        return GraphSummaryResponse(nodes=node_counts, edges=edge_counts)

    async def get_subgraph(self, root_type: str, root_id: str, depth: int) -> GraphSubgraphResponse:
        """
        Returns all nodes and edges reachable from root_id within the given depth.

        The traversal uses a bidirectional view of the edge set so the user can
        navigate in either direction (e.g. from an Invoice back to its SalesOrder).
        """
        edges_union = self._get_edges_union_query()
        subgraph_query = f"""
        WITH RECURSIVE graph_edges AS (
            {edges_union}
        ),
        -- Traverse in both directions so the user can expand from any node
        bidirectional_edges AS (
            SELECT source_id, source_type, target_id, target_type, type FROM graph_edges
            UNION ALL
            SELECT target_id, target_type, source_id, source_type, type FROM graph_edges
        ),
        traversal(id, type, depth, path) AS (
            -- Seed with the root node
            SELECT
                :root_id,
                :root_type,
                0,
                ARRAY[:root_id || ':' || :root_type]
            UNION ALL
            -- Expand one hop at a time; path array prevents cycles
            SELECT
                be.target_id,
                be.target_type,
                t.depth + 1,
                t.path || (be.target_id || ':' || be.target_type)
            FROM bidirectional_edges be
            JOIN traversal t ON be.source_id = t.id AND be.source_type = t.type
            WHERE t.depth < :depth
              AND NOT (be.target_id || ':' || be.target_type = ANY(t.path))
        )
        -- Return only edges where both endpoints were reached by the traversal
        SELECT DISTINCT
            ge.source_id, ge.source_type,
            ge.target_id, ge.target_type,
            ge.type
        FROM graph_edges ge
        JOIN (SELECT DISTINCT id, type FROM traversal) t1
            ON ge.source_id = t1.id AND ge.source_type = t1.type
        JOIN (SELECT DISTINCT id, type FROM traversal) t2
            ON ge.target_id = t2.id AND ge.target_type = t2.type
        """

        params = {"root_id": root_id, "root_type": root_type, "depth": depth}
        result = await self.db.execute(text(subgraph_query), params)

        nodes_map: Dict = {}
        edges: List[Edge] = []

        # Ensure root is always present even when it has no edges
        nodes_map[(root_type, root_id)] = Node(
            id=root_id, type=root_type, label=f"{root_type} {root_id}"
        )

        for s_id, s_type, t_id, t_type, e_type in result:
            if (s_type, s_id) not in nodes_map:
                nodes_map[(s_type, s_id)] = Node(
                    id=s_id, type=s_type, label=f"{s_type} {s_id}"
                )
            if (t_type, t_id) not in nodes_map:
                nodes_map[(t_type, t_id)] = Node(
                    id=t_id, type=t_type, label=f"{t_type} {t_id}"
                )
            edges.append(Edge(
                id=f"{s_id}-{t_id}-{e_type}",
                source=s_id,
                target=t_id,
                type=e_type,
            ))

        return GraphSubgraphResponse(nodes=list(nodes_map.values()), edges=edges)

    def _get_individual_edge_queries(self) -> Dict[str, str]:
        """Returns a mapping of edge_type -> SQL SELECT for that edge type."""
        return {
            "PLACED": """
                SELECT soh.sold_to_party::text AS source_id, 'Customer'::text AS source_type,
                       soh.sales_order::text AS target_id, 'SalesOrder'::text AS target_type, 'PLACED'::text AS type
                FROM sales_order_headers soh WHERE soh.sold_to_party IS NOT NULL
            """,
            "HAS_ITEM_SO": """
                SELECT soi.sales_order::text AS source_id, 'SalesOrder'::text AS source_type,
                       (soi.sales_order || '-' || soi.sales_order_item)::text AS target_id,
                       'SalesOrderItem'::text AS target_type, 'HAS_ITEM'::text AS type
                FROM sales_order_items soi
            """,
            "INCLUDES": """
                SELECT (soi.sales_order || '-' || soi.sales_order_item)::text AS source_id,
                       'SalesOrderItem'::text AS source_type, soi.material::text AS target_id,
                       'Product'::text AS target_type, 'INCLUDES'::text AS type
                FROM sales_order_items soi WHERE soi.material IS NOT NULL
            """,
            "HAS_ITEM_DEL": """
                SELECT odi.delivery_document::text AS source_id, 'Delivery'::text AS source_type,
                       (odi.delivery_document || '-' || odi.delivery_document_item)::text AS target_id,
                       'DeliveryItem'::text AS target_type, 'HAS_ITEM'::text AS type
                FROM outbound_delivery_items odi
            """,
            "FULFILLS": """
                SELECT (odi.delivery_document || '-' || odi.delivery_document_item)::text AS source_id,
                       'DeliveryItem'::text AS source_type,
                       (odi.reference_sd_document || '-' || odi.reference_sd_document_item)::text AS target_id,
                       'SalesOrderItem'::text AS target_type, 'FULFILLS'::text AS type
                FROM outbound_delivery_items odi WHERE odi.reference_sd_document IS NOT NULL
            """,
            "HAS_ITEM_INV": """
                SELECT bdi.billing_document::text AS source_id, 'Invoice'::text AS source_type,
                       (bdi.billing_document || '-' || bdi.billing_document_item)::text AS target_id,
                       'InvoiceItem'::text AS target_type, 'HAS_ITEM'::text AS type
                FROM billing_document_items bdi
            """,
            "BILLS_FOR": """
                SELECT (bdi.billing_document || '-' || bdi.billing_document_item)::text AS source_id,
                       'InvoiceItem'::text AS source_type,
                       (bdi.reference_sd_document || '-' || bdi.reference_sd_document_item)::text AS target_id,
                       'DeliveryItem'::text AS target_type, 'BILLS_FOR'::text AS type
                FROM billing_document_items bdi WHERE bdi.reference_sd_document IS NOT NULL
            """,
            "BILLED_TO": """
                SELECT bdh.billing_document::text AS source_id, 'Invoice'::text AS source_type,
                       bdh.sold_to_party::text AS target_id, 'Customer'::text AS target_type, 'BILLED_TO'::text AS type
                FROM billing_document_headers bdh WHERE bdh.sold_to_party IS NOT NULL
            """,
            "GENERATES": """
                SELECT bdh.billing_document::text AS source_id, 'Invoice'::text AS source_type,
                       bdh.accounting_document::text AS target_id, 'JournalEntry'::text AS target_type, 'GENERATES'::text AS type
                FROM billing_document_headers bdh WHERE bdh.accounting_document IS NOT NULL
            """,
            "CLEARS": """
                SELECT DISTINCT par.accounting_document::text AS source_id, 'Payment'::text AS source_type,
                       par.clearing_accounting_document::text AS target_id, 'JournalEntry'::text AS target_type, 'CLEARS'::text AS type
                FROM payments_accounts_receivable par WHERE par.clearing_accounting_document IS NOT NULL
            """,
            "HAS_ADDRESS": """
                SELECT bpa.business_partner::text AS source_id, 'Customer'::text AS source_type,
                       (bpa.business_partner || '-' || bpa.address_id)::text AS target_id,
                       'Address'::text AS target_type, 'HAS_ADDRESS'::text AS type
                FROM business_partner_addresses bpa
            """,
        }

    # HAS_ITEM is used for SO, Delivery, and Invoice — map the logical name to internal keys
    _EDGE_TYPE_TO_QUERY_KEYS: Dict[str, List[str]] = {
        "PLACED": ["PLACED"],
        "HAS_ITEM": ["HAS_ITEM_SO", "HAS_ITEM_DEL", "HAS_ITEM_INV"],
        "INCLUDES": ["INCLUDES"],
        "FULFILLS": ["FULFILLS"],
        "BILLS_FOR": ["BILLS_FOR"],
        "BILLED_TO": ["BILLED_TO"],
        "GENERATES": ["GENERATES"],
        "CLEARS": ["CLEARS"],
        "HAS_ADDRESS": ["HAS_ADDRESS"],
    }

    async def get_flow(self, flow_id: str, limit: int = 50) -> GraphSubgraphResponse:
        """Returns a sampled subgraph for a predefined O2C flow."""
        flow = FLOW_DEFINITIONS.get(flow_id)
        if not flow:
            return GraphSubgraphResponse(nodes=[], edges=[])

        edge_queries = self._get_individual_edge_queries()
        included_edge_types = set(flow["edge_types"])
        node_types = set(flow["node_types"])

        # Collect relevant query keys for this flow's edge types
        query_parts: List[str] = []
        for logical_edge_type in included_edge_types:
            keys = self._EDGE_TYPE_TO_QUERY_KEYS.get(logical_edge_type, [logical_edge_type])
            for key in keys:
                if key in edge_queries:
                    query_parts.append(edge_queries[key])

        if not query_parts:
            return GraphSubgraphResponse(nodes=[], edges=[])

        union_sql = " UNION ALL ".join(query_parts)
        # Filter to only include edges where both endpoints are in node_types for this flow,
        # then sample up to `limit` rows per source_type
        node_type_list = ", ".join(f"'{t}'" for t in node_types)
        query = f"""
        WITH flow_edges AS (
            {union_sql}
        ),
        filtered AS (
            SELECT * FROM flow_edges
            WHERE source_type IN ({node_type_list}) AND target_type IN ({node_type_list})
        ),
        ranked AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY source_type ORDER BY source_id) AS rn
            FROM filtered
        )
        SELECT source_id, source_type, target_id, target_type, type FROM ranked WHERE rn <= :limit
        """

        result = await self.db.execute(text(query), {"limit": limit})

        nodes_map: Dict = {}
        edges: List[Edge] = []
        for s_id, s_type, t_id, t_type, e_type in result:
            if (s_type, s_id) not in nodes_map:
                nodes_map[(s_type, s_id)] = Node(id=s_id, type=s_type, label=f"{s_type} {s_id}")
            if (t_type, t_id) not in nodes_map:
                nodes_map[(t_type, t_id)] = Node(id=t_id, type=t_type, label=f"{t_type} {t_id}")
            edges.append(Edge(id=f"{s_id}-{t_id}-{e_type}", source=s_id, target=t_id, type=e_type))

        return GraphSubgraphResponse(nodes=list(nodes_map.values()), edges=edges)

    async def get_full_graph(self, node_limit: int = 20, type_filter: Optional[List[str]] = None) -> GraphSubgraphResponse:
        """Returns a sampled view of the full graph, up to node_limit entities per type."""
        all_node_types = [
            "Customer", "SalesOrder", "SalesOrderItem",
            "Delivery", "DeliveryItem",
            "Invoice", "InvoiceItem",
            "JournalEntry", "Payment",
            "Product", "Address",
        ]
        active_types = type_filter if type_filter else all_node_types

        # Collect a sample of IDs per type
        type_to_query: Dict[str, str] = {
            "SalesOrder":     "SELECT sales_order::text FROM sales_order_headers LIMIT :limit",
            "SalesOrderItem": "SELECT (sales_order || '-' || sales_order_item)::text FROM sales_order_items LIMIT :limit",
            "Delivery":       "SELECT delivery_document::text FROM outbound_delivery_headers LIMIT :limit",
            "DeliveryItem":   "SELECT (delivery_document || '-' || delivery_document_item)::text FROM outbound_delivery_items LIMIT :limit",
            "Invoice":        "SELECT billing_document::text FROM billing_document_headers LIMIT :limit",
            "InvoiceItem":    "SELECT (billing_document || '-' || billing_document_item)::text FROM billing_document_items LIMIT :limit",
            "JournalEntry":   "SELECT DISTINCT accounting_document::text FROM journal_entry_items_accounts_receivable LIMIT :limit",
            "Payment":        "SELECT DISTINCT accounting_document::text FROM payments_accounts_receivable LIMIT :limit",
            "Product":        "SELECT product::text FROM products LIMIT :limit",
            "Customer":       "SELECT business_partner::text FROM business_partners LIMIT :limit",
            "Address":        "SELECT (business_partner || '-' || address_id)::text FROM business_partner_addresses LIMIT :limit",
        }

        sampled_ids: Dict[str, set] = {}
        for node_type in active_types:
            if node_type not in type_to_query:
                continue
            res = await self.db.execute(text(type_to_query[node_type]), {"limit": node_limit})
            sampled_ids[node_type] = {row[0] for row in res}

        nodes_map: Dict = {}
        for node_type, ids in sampled_ids.items():
            for nid in ids:
                nodes_map[(node_type, nid)] = Node(id=nid, type=node_type, label=f"{node_type} {nid}")

        # Fetch all edges and keep only those where both endpoints are in our sample
        all_edges_sql = self._get_edges_union_query()
        edge_result = await self.db.execute(text(f"SELECT source_id, source_type, target_id, target_type, type FROM ({all_edges_sql}) AS all_edges"))

        edges: List[Edge] = []
        for s_id, s_type, t_id, t_type, e_type in edge_result:
            if (s_type, s_id) in nodes_map and (t_type, t_id) in nodes_map:
                edges.append(Edge(id=f"{s_id}-{t_id}-{e_type}", source=s_id, target=t_id, type=e_type))

        return GraphSubgraphResponse(nodes=list(nodes_map.values()), edges=edges)

    async def get_entities(self, node_type: str, limit: int = 50) -> GraphEntityResponse:
        """Returns a sample of entity IDs and labels for the given node type."""
        type_to_query: Dict[str, tuple] = {
            "SalesOrder":     ("sales_order_headers",          "sales_order"),
            "SalesOrderItem": ("sales_order_items",            "sales_order || '-' || sales_order_item"),
            "Delivery":       ("outbound_delivery_headers",    "delivery_document"),
            "DeliveryItem":   ("outbound_delivery_items",      "delivery_document || '-' || delivery_document_item"),
            "Invoice":        ("billing_document_headers",     "billing_document"),
            "InvoiceItem":    ("billing_document_items",       "billing_document || '-' || billing_document_item"),
            "JournalEntry":   ("journal_entry_items_accounts_receivable", "accounting_document"),
            "Payment":        ("payments_accounts_receivable", "accounting_document"),
            "Product":        ("products",                     "product"),
            "Customer":       ("business_partners",            "business_partner"),
            "Address":        ("business_partner_addresses",   "business_partner || '-' || address_id"),
        }

        if node_type not in type_to_query:
            return GraphEntityResponse(type=node_type, entities=[])

        table, id_col = type_to_query[node_type]
        result = await self.db.execute(
            text(f"SELECT DISTINCT {id_col}::text FROM {table} LIMIT :limit"),
            {"limit": limit},
        )

        entities = [{"id": row[0], "label": f"{node_type} {row[0]}"} for row in result]
        return GraphEntityResponse(type=node_type, entities=entities)
