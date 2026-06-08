from fleet.geo.roster import HCM_CUSTOMERS


def test_roster_is_substantial_and_unique():
    assert len(HCM_CUSTOMERS) >= 15
    ids = [c[0] for c in HCM_CUSTOMERS]
    assert len(ids) == len(set(ids))           # unique ids


def test_roster_rows_are_well_formed():
    for cid, ctype, lat, lng, name, orders, prio, tw_s, tw_e, sla_h in HCM_CUSTOMERS:
        assert cid.startswith("C") and isinstance(name, str) and name
        assert 10.6 < lat < 11.0 and 106.5 < lng < 106.9   # within HCM
        assert isinstance(orders, dict) and orders
        assert 1 <= prio <= 4
        assert tw_s < tw_e and sla_h >= tw_e
