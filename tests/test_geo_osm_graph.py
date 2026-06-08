import pytest

from config.settings import load_settings
from fleet.geo.osm_graph import load_drive_graph


def test_world_settings_default_to_sample():
    s = load_settings({})
    assert s.world == "sample"
    assert s.osm_graphml_path.endswith(".graphml")
    assert s.urban_speed_kmh > 0


def test_load_drive_graph_missing_file_raises_clear_error():
    s = load_settings({"OSM_GRAPHML_PATH": "data/does_not_exist.graphml"})
    with pytest.raises(FileNotFoundError) as exc:
        load_drive_graph(s)
    assert "fetch_osm" in str(exc.value)        # points the user at the script
