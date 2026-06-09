from fleet.scenarios import build_sample_state
s = build_sample_state()
print('C001 orders:', s.customers['C001'].orders)
print('sum:', sum(s.customers['C001'].orders.values()))
print('all customers orders sums:', {cid: sum(c.orders.values()) for cid,c in s.customers.items()})
print('total_orders_pending:', s.total_orders_pending())
