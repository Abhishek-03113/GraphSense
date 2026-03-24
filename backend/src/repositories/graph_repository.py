from typing import Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from src.domain.graph_models import Node, Edge, GraphSummaryResponse, GraphSubgraphResponse, GraphEntityResponse
from src.domain.flow_definitions import FLOW_DEFINITIONS
from src.utils.logger import get_logger

logger = get_logger(__name__)


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

    # SQL helper: normalize an item-number column by stripping leading zeros.
    # Cross-document FK references use short numbers (e.g. '10') while source
    # tables use zero-padded numbers (e.g. '000010').  Wrapping every item
    # column with _norm() produces a canonical composite ID that matches
    # regardless of which table the value originates from.
    @staticmethod
    def _norm(col: str) -> str:
        """Returns a SQL expression that strips leading zeros from *col*."""
        return f"REGEXP_REPLACE({col}::text, '^0+', '')"

    def _composite(self, doc_col: str, item_col: str) -> str:
        """Returns a SQL expression for a normalized composite ID: 'doc-item'."""
        return f"({doc_col}::text || '-' || {self._norm(item_col)})"

    def _get_edges_union_query(self) -> str:
        """
        Derives all graph edges from foreign-key relationships in the schema.
        Each UNION ALL block represents one edge type in the O2C graph model.

        All composite IDs (doc-item) are normalized via _composite() so that
        cross-document references match regardless of zero-padding differences.
        """
        so_item = self._composite("soi.sales_order", "soi.sales_order_item")
        del_item = self._composite("odi.delivery_document", "odi.delivery_document_item")
        del_ref = self._composite("odi.reference_sd_document", "odi.reference_sd_document_item")
        inv_item = self._composite("bdi.billing_document", "bdi.billing_document_item")
        inv_ref = self._composite("bdi.reference_sd_document", "bdi.reference_sd_document_item")
        addr_id = self._composite("bpa.business_partner", "bpa.address_id")

        return f"""
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
            soi.sales_order::text       AS source_id,
            'SalesOrder'::text          AS source_type,
            {so_item}::text             AS target_id,
            'SalesOrderItem'::text      AS target_type,
            'HAS_ITEM'::text            AS type
        FROM sales_order_items soi

        UNION ALL

        -- ── SalesOrderItem --[INCLUDES]--> Product ───────────────────────
        SELECT
            {so_item}::text             AS source_id,
            'SalesOrderItem'::text      AS source_type,
            soi.material::text          AS target_id,
            'Product'::text             AS target_type,
            'INCLUDES'::text            AS type
        FROM sales_order_items soi
        WHERE soi.material IS NOT NULL

        UNION ALL

        -- ── Delivery --[HAS_ITEM]--> DeliveryItem ────────────────────────
        SELECT
            odi.delivery_document::text     AS source_id,
            'Delivery'::text                AS source_type,
            {del_item}::text                AS target_id,
            'DeliveryItem'::text            AS target_type,
            'HAS_ITEM'::text                AS type
        FROM outbound_delivery_items odi

        UNION ALL

        -- ── DeliveryItem --[FULFILLS]--> SalesOrderItem ──────────────────
        -- Cross-document link: ties delivery fulfilment back to the sales order item
        SELECT
            {del_item}::text                AS source_id,
            'DeliveryItem'::text            AS source_type,
            {del_ref}::text                 AS target_id,
            'SalesOrderItem'::text          AS target_type,
            'FULFILLS'::text                AS type
        FROM outbound_delivery_items odi
        WHERE odi.reference_sd_document IS NOT NULL

        UNION ALL

        -- ── Invoice --[HAS_ITEM]--> InvoiceItem ──────────────────────────
        SELECT
            bdi.billing_document::text      AS source_id,
            'Invoice'::text                 AS source_type,
            {inv_item}::text                AS target_id,
            'InvoiceItem'::text             AS target_type,
            'HAS_ITEM'::text                AS type
        FROM billing_document_items bdi

        UNION ALL

        -- ── InvoiceItem --[BILLS_FOR]--> DeliveryItem ────────────────────
        -- Cross-document link: ties billing line back to the delivery item it covers
        SELECT
            {inv_item}::text                AS source_id,
            'InvoiceItem'::text             AS source_type,
            {inv_ref}::text                 AS target_id,
            'DeliveryItem'::text            AS target_type,
            'BILLS_FOR'::text               AS type
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
            bpa.business_partner::text      AS source_id,
            'Customer'::text                AS source_type,
            {addr_id}::text                 AS target_id,
            'Address'::text                 AS target_type,
            'HAS_ADDRESS'::text             AS type
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
            count = result.scalar()
            node_counts[node_type] = count
            logger.debug("get_summary | node_type=%-20s count=%d", node_type, count)

        edges_union = self._get_edges_union_query()
        result = await self.db.execute(
            text(f"SELECT type, COUNT(*) FROM ({edges_union}) AS all_edges GROUP BY type ORDER BY type")
        )
        edge_counts: Dict[str, int] = {row[0]: row[1] for row in result}
        for edge_type, count in edge_counts.items():
            logger.debug("get_summary | edge_type=%-20s count=%d", edge_type, count)

        logger.info(
            "get_summary | total_nodes=%d total_edges=%d",
            sum(node_counts.values()),
            sum(edge_counts.values()),
        )
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
        logger.debug("get_subgraph | root=%s:%s depth=%d — executing query", root_type, root_id, depth)
        result = await self.db.execute(text(subgraph_query), params)

        nodes_map: Dict = {}
        edges: List[Edge] = []

        # Ensure root is always present even when it has no edges
        nodes_map[(root_type, root_id)] = Node(
            id=f"{root_type}:{root_id}", type=root_type, label=f"{root_type} {root_id}"
        )

        for s_id, s_type, t_id, t_type, e_type in result:
            s_node_id = f"{s_type}:{s_id}"
            t_node_id = f"{t_type}:{t_id}"
            if (s_type, s_id) not in nodes_map:
                nodes_map[(s_type, s_id)] = Node(
                    id=s_node_id, type=s_type, label=f"{s_type} {s_id}"
                )
            if (t_type, t_id) not in nodes_map:
                nodes_map[(t_type, t_id)] = Node(
                    id=t_node_id, type=t_type, label=f"{t_type} {t_id}"
                )
            edges.append(Edge(
                id=f"{s_node_id}-{t_node_id}-{e_type}",
                source=s_node_id,
                target=t_node_id,
                type=e_type,
            ))

        logger.info(
            "get_subgraph | root=%s:%s depth=%d → nodes=%d edges=%d",
            root_type, root_id, depth, len(nodes_map), len(edges),
        )
        return GraphSubgraphResponse(nodes=list(nodes_map.values()), edges=edges)

    def _get_individual_edge_queries(self) -> Dict[str, str]:
        """Returns a mapping of edge_type -> SQL SELECT for that edge type.
        Uses normalized composite IDs (leading zeros stripped) for consistency."""
        so_item = self._composite("soi.sales_order", "soi.sales_order_item")
        del_item = self._composite("odi.delivery_document", "odi.delivery_document_item")
        del_ref = self._composite("odi.reference_sd_document", "odi.reference_sd_document_item")
        inv_item = self._composite("bdi.billing_document", "bdi.billing_document_item")
        inv_ref = self._composite("bdi.reference_sd_document", "bdi.reference_sd_document_item")
        addr_id = self._composite("bpa.business_partner", "bpa.address_id")

        return {
            "PLACED": """
                SELECT soh.sold_to_party::text AS source_id, 'Customer'::text AS source_type,
                       soh.sales_order::text AS target_id, 'SalesOrder'::text AS target_type, 'PLACED'::text AS type
                FROM sales_order_headers soh WHERE soh.sold_to_party IS NOT NULL
            """,
            "HAS_ITEM_SO": f"""
                SELECT soi.sales_order::text AS source_id, 'SalesOrder'::text AS source_type,
                       {so_item}::text AS target_id,
                       'SalesOrderItem'::text AS target_type, 'HAS_ITEM'::text AS type
                FROM sales_order_items soi
            """,
            "INCLUDES": f"""
                SELECT {so_item}::text AS source_id,
                       'SalesOrderItem'::text AS source_type, soi.material::text AS target_id,
                       'Product'::text AS target_type, 'INCLUDES'::text AS type
                FROM sales_order_items soi WHERE soi.material IS NOT NULL
            """,
            "HAS_ITEM_DEL": f"""
                SELECT odi.delivery_document::text AS source_id, 'Delivery'::text AS source_type,
                       {del_item}::text AS target_id,
                       'DeliveryItem'::text AS target_type, 'HAS_ITEM'::text AS type
                FROM outbound_delivery_items odi
            """,
            "FULFILLS": f"""
                SELECT {del_item}::text AS source_id,
                       'DeliveryItem'::text AS source_type,
                       {del_ref}::text AS target_id,
                       'SalesOrderItem'::text AS target_type, 'FULFILLS'::text AS type
                FROM outbound_delivery_items odi WHERE odi.reference_sd_document IS NOT NULL
            """,
            "HAS_ITEM_INV": f"""
                SELECT bdi.billing_document::text AS source_id, 'Invoice'::text AS source_type,
                       {inv_item}::text AS target_id,
                       'InvoiceItem'::text AS target_type, 'HAS_ITEM'::text AS type
                FROM billing_document_items bdi
            """,
            "BILLS_FOR": f"""
                SELECT {inv_item}::text AS source_id,
                       'InvoiceItem'::text AS source_type,
                       {inv_ref}::text AS target_id,
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
            "HAS_ADDRESS": f"""
                SELECT bpa.business_partner::text AS source_id, 'Customer'::text AS source_type,
                       {addr_id}::text AS target_id,
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

        logger.debug("get_flow | flow_id=%s limit=%d — executing query", flow_id, limit)
        result = await self.db.execute(text(query), {"limit": limit})

        nodes_map: Dict = {}
        edges: List[Edge] = []
        for s_id, s_type, t_id, t_type, e_type in result:
            s_node_id = f"{s_type}:{s_id}"
            t_node_id = f"{t_type}:{t_id}"
            if (s_type, s_id) not in nodes_map:
                nodes_map[(s_type, s_id)] = Node(id=s_node_id, type=s_type, label=f"{s_type} {s_id}")
            if (t_type, t_id) not in nodes_map:
                nodes_map[(t_type, t_id)] = Node(id=t_node_id, type=t_type, label=f"{t_type} {t_id}")
            edges.append(Edge(id=f"{s_node_id}-{t_node_id}-{e_type}", source=s_node_id, target=t_node_id, type=e_type))

        logger.info(
            "get_flow | flow_id=%s limit=%d → nodes=%d edges=%d",
            flow_id, limit, len(nodes_map), len(edges),
        )
        return GraphSubgraphResponse(nodes=list(nodes_map.values()), edges=edges)

    async def get_full_graph(self, node_limit: int = 20, type_filter: Optional[List[str]] = None) -> GraphSubgraphResponse:
        """
        Returns a sampled knowledge graph using edge-first sampling.

        Strategy: sample edges per edge-type (up to `node_limit` each), then
        collect all referenced nodes.  This guarantees every edge has both
        endpoints present and cross-document links (FULFILLS, BILLS_FOR,
        GENERATES, CLEARS) are always represented.
        """
        all_node_types = {
            "Customer", "SalesOrder", "SalesOrderItem",
            "Delivery", "DeliveryItem",
            "Invoice", "InvoiceItem",
            "JournalEntry", "Payment",
            "Product", "Address",
        }
        active_types = set(type_filter) if type_filter else all_node_types

        edge_queries = self._get_individual_edge_queries()

        # Build a UNION ALL of all edge types, each limited to `node_limit` rows,
        # filtered to only include edges whose both endpoints are in active_types.
        node_type_list = ", ".join(f"'{t}'" for t in active_types)
        sampled_parts: List[str] = []
        for key, sql in edge_queries.items():
            sampled_parts.append(f"""
                (SELECT source_id, source_type, target_id, target_type, type
                 FROM ({sql}) AS _{key}
                 WHERE source_type IN ({node_type_list})
                   AND target_type IN ({node_type_list})
                 LIMIT :limit)
            """)

        if not sampled_parts:
            return GraphSubgraphResponse(nodes=[], edges=[])

        full_query = " UNION ALL ".join(sampled_parts)
        logger.debug("get_full_graph | node_limit=%d type_filter=%s — executing edge-first sampling", node_limit, type_filter)
        result = await self.db.execute(text(full_query), {"limit": node_limit})

        nodes_map: Dict = {}
        edges: List[Edge] = []
        for s_id, s_type, t_id, t_type, e_type in result:
            s_node_id = f"{s_type}:{s_id}"
            t_node_id = f"{t_type}:{t_id}"
            if (s_type, s_id) not in nodes_map:
                nodes_map[(s_type, s_id)] = Node(
                    id=s_node_id, type=s_type, label=f"{s_type} {s_id}"
                )
            if (t_type, t_id) not in nodes_map:
                nodes_map[(t_type, t_id)] = Node(
                    id=t_node_id, type=t_type, label=f"{t_type} {t_id}"
                )
            edges.append(Edge(
                id=f"{s_node_id}-{t_node_id}-{e_type}",
                source=s_node_id, target=t_node_id, type=e_type,
            ))

        logger.info(
            "get_full_graph | node_limit=%d type_filter=%s → nodes=%d edges=%d",
            node_limit, type_filter, len(nodes_map), len(edges),
        )
        return GraphSubgraphResponse(nodes=list(nodes_map.values()), edges=edges)

    async def get_entities(self, node_type: str, limit: int = 50) -> GraphEntityResponse:
        """Returns a sample of entity IDs and labels for the given node type."""
        norm = self._norm
        type_to_query: Dict[str, tuple] = {
            "SalesOrder":     ("sales_order_headers",          "sales_order"),
            "SalesOrderItem": ("sales_order_items",            f"sales_order || '-' || {norm('sales_order_item')}"),
            "Delivery":       ("outbound_delivery_headers",    "delivery_document"),
            "DeliveryItem":   ("outbound_delivery_items",      f"delivery_document || '-' || {norm('delivery_document_item')}"),
            "Invoice":        ("billing_document_headers",     "billing_document"),
            "InvoiceItem":    ("billing_document_items",       f"billing_document || '-' || {norm('billing_document_item')}"),
            "JournalEntry":   ("journal_entry_items_accounts_receivable", "accounting_document"),
            "Payment":        ("payments_accounts_receivable", "accounting_document"),
            "Product":        ("products",                     "product"),
            "Customer":       ("business_partners",            "business_partner"),
            "Address":        ("business_partner_addresses",   f"business_partner || '-' || {norm('address_id')}"),
        }

        if node_type not in type_to_query:
            return GraphEntityResponse(type=node_type, entities=[])

        table, id_col = type_to_query[node_type]
        result = await self.db.execute(
            text(f"SELECT DISTINCT {id_col}::text FROM {table} LIMIT :limit"),
            {"limit": limit},
        )

        entities = [{"id": row[0], "label": f"{node_type} {row[0]}"} for row in result]
        logger.info("get_entities | node_type=%s limit=%d → returned=%d", node_type, limit, len(entities))
        return GraphEntityResponse(type=node_type, entities=entities)
