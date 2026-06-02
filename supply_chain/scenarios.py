"""Synthetic disruption scenarios + scripted fallback reasoning.

Each scenario carries:
  - event:      the disruption text
  - anomaly:    the detection signal (with a fake stat so it looks real)
  - detector:   which detection method fired
  - context:    dict passed to the agent for reasoning
  - node_hit:   which network node turns red
  - scripted:   fallback reasoning/action when the live LLM is unavailable
  - dispatch:   concrete commands sent DOWN to node staff after execution
                (workflow step 4 — serves the indirect users: warehouse,
                 driver, supplier, retail staff)
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
        "dispatch": [
            "→ Procurement: issue replacement PO #PO-8842 to Supplier B (60% volume)",
            "→ Supplier A: confirm reduced order (40% volume)",
            "→ Warehouse North: update inbound schedule (ETA restored via B)",
        ],
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
        "dispatch": [
            "→ Warehouse South: release 400 units SKU-1024 for transfer",
            "→ Warehouse North: receive transfer, update reorder point = 520",
            "→ Procurement: place reorder PO #PO-8843 (600 units)",
        ],
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
        "node_hit": ("retail", "Store-HN"),
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
        "dispatch": [
            "→ Drivers #12, #15, #18, #21: reroute via DT743",
            "→ Dispatch: re-prioritize SLA-critical orders #4471, #4472",
            "→ Customers (2): push updated ETA (+45 min)",
        ],
    },
    "Retail Stockout": {
        "icon": "🏪",
        "event": "Retail store Store-HCM reports a sudden stockout of SKU-2210.",
        "anomaly": "Store-HCM SKU-2210 on-shelf = 0 (demand +95%, Z-score 3.0) → ANOMALY",
        "detector": "POS feed threshold + Z-score on retail sell-through",
        "context": {
            "affected_store": "Store-HCM",
            "sku": "SKU-2210",
            "dc_central_stock": 1200,
            "distance_to_store": "18 km",
            "replenishment_sla": "4h",
        },
        "node_hit": ("retail", "Store-HCM"),
        "scripted": {
            "reasoning": [
                "Observe: Store-HCM is out of SKU-2210 while sell-through is up +95%.",
                "Think: Lost sales accruing; DC-Central holds 1,200 units 18 km away.",
                "Act: Check DC capacity and a same-day delivery slot → available within 4h SLA.",
                "Plan: Ship 250 units from DC-Central to Store-HCM now; flag SKU for safety-stock review.",
            ],
            "action": "Ship 250 units SKU-2210 from DC-Central to Store-HCM (within 4h SLA).",
            "impact": "Restores on-shelf availability same day; recovers ~95% of at-risk sales.",
            "needs_approval": False,
        },
        "dispatch": [
            "→ Distribution Center Central: pick & ship 250 units SKU-2210 to Store-HCM",
            "→ Store-HCM staff: expect replenishment within 4h",
            "→ Inventory planning: flag SKU-2210 for safety-stock review",
        ],
    },
}
