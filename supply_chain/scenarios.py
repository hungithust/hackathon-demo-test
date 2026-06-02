"""Synthetic disruption scenarios + scripted fallback reasoning.

Each scenario carries: the event text, the anomaly signal (with a fake stat so it
looks like real detection), the context dict passed to the agent, which network
node it hits, and a scripted reasoning/action used when the live LLM is unavailable.
"""

SCENARIOS = {
    "Supplier Delay": {
        "icon": "📦",
        "event": "Supplier A reports a 3-day delay on a raw-material shipment.",
        "anomaly": "Supplier A lead-time = 6d (baseline 3d, +100%, Z-score 3.4) → ANOMALY",
        "detector": "Isolation Forest + Z-score on supplier lead-time stream",
        "context": {
            "affected_supplier": "Supplier A",
            "open_orders_on_A": 12,
            "inventory_cover_days": 2,
            "backup_supplier": "Supplier B (capacity 70%, lead-time 3d, +4% unit cost)",
        },
        "node_hit": ("suppliers", "A"),
        "scripted": {
            "reasoning": [
                "Observe: Supplier A lead-time doubled; inventory cover is only 2 days vs a 6-day delay.",
                "Think: Stockout risk on 12 open orders within 48h. An alternate source is needed now.",
                "Act: Query backup suppliers → Supplier B has 70% capacity at +4% cost, same 3d lead-time.",
                "Plan: Move 60% of volume to Supplier B (covers the gap), keep 40% on A for contract minimums.",
            ],
            "action": "Reroute 60% of Supplier A's open orders to Supplier B; keep 40% on A.",
            "impact": "Avoids stockout on 12 orders. Cost +4% on rerouted volume (~+1.6% total). On-time risk neutralized.",
            "needs_approval": True,
        },
    },
    "Demand Spike": {
        "icon": "📈",
        "event": "Warehouse North: sudden +180% demand surge for SKU-1024.",
        "anomaly": "SKU-1024 demand = 280 units/h (baseline 100, +180%, Z-score 4.1) → ANOMALY",
        "detector": "Z-score on demand stream + DBSCAN burst clustering",
        "context": {
            "affected_warehouse": "Warehouse North",
            "sku": "SKU-1024",
            "north_stock": 140,
            "south_stock": 900,
            "current_reorder_point": 200,
        },
        "node_hit": ("warehouses", "North"),
        "scripted": {
            "reasoning": [
                "Observe: SKU-1024 demand spiked +180% at North; North stock 140 will deplete in ~30 min.",
                "Think: South holds 900 units with low local demand → safe to rebalance.",
                "Act: Recompute EOQ + safety stock for the new demand profile → raise reorder point to 520.",
                "Plan: Transfer 400 units South→North immediately; trigger reorder of 600 units.",
            ],
            "action": "Transfer 400 units SKU-1024 (South→North); raise reorder point to 520; place reorder of 600.",
            "impact": "Prevents stockout at North; balances network inventory; reorder secures next 7 days.",
            "needs_approval": True,
        },
    },
    "Route Blockage": {
        "icon": "🚧",
        "event": "Highway QL1A blocked by flooding; 4 deliveries at risk.",
        "anomaly": "Route QL1A status = BLOCKED; 4 in-transit deliveries ETA breach → ANOMALY",
        "detector": "Traffic/weather rule + shortest-path graph re-check",
        "context": {
            "blocked_route": "QL1A (segment Km120-150)",
            "deliveries_at_risk": 4,
            "alt_route": "DT743 (+38 km, +45 min, clear)",
            "priority_orders": "2 of 4 are SLA-critical",
        },
        "node_hit": ("routes", "QL1A"),
        "scripted": {
            "reasoning": [
                "Observe: QL1A blocked; 4 deliveries will breach ETA.",
                "Think: Need an alternate path and prioritize the 2 SLA-critical orders.",
                "Act: Re-solve VRP on the remaining road graph → DT743 viable (+38km, +45min).",
                "Plan: Reroute all 4 via DT743; move 2 SLA-critical orders to the front of the queue.",
            ],
            "action": "Reroute 4 deliveries via DT743; re-prioritize 2 SLA-critical orders first.",
            "impact": "All 4 deliveries kept within SLA buffer; +45 min avg, minor fuel cost increase.",
            "needs_approval": False,
        },
    },
}
