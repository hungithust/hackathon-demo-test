from fleet.intake.resolver import resolve_target
from fleet.scenarios import build_sample_state
from fleet.contracts.state import EventType


def test_resolves_vehicle_by_number():
    state = build_sample_state()
    assert resolve_target("xe 3 bi hong giua duong", EventType.VEHICLE_BREAKDOWN, state) == "V003"


def test_resolves_customer_by_id():
    state = build_sample_state()
    assert resolve_target("kho cua C001 het hang", EventType.INVENTORY_SHORTAGE, state) == "C001"


def test_resolves_customer_by_name_accent_folded():
    state = build_sample_state()
    # "BigC Q.1" is C001's name; report typed without exact case/accents
    assert resolve_target("bigc q.1 can them hang gap", EventType.URGENT_ORDER, state) == "C001"


def test_resolves_flooded_edge_prefers_flood_prone():
    state = build_sample_state()
    edge_id = resolve_target("duong vao C001 bi ngap", EventType.FLOODED_AREA, state)
    assert edge_id == "DEPOT->C001#2"   # the flood-prone parallel edge


def test_resolves_traffic_edge_prefers_open():
    state = build_sample_state()
    edge_id = resolve_target("ket xe tren duong toi C001", EventType.TRAFFIC, state)
    assert edge_id == "DEPOT->C001"     # the open edge


def test_unresolved_returns_none():
    state = build_sample_state()
    assert resolve_target("khong khop voi gi ca", EventType.VEHICLE_BREAKDOWN, state) is None
