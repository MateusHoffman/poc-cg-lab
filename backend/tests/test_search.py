from app.search import rank_vehicles
from app.vector_store import VectorStore


def test_finds_polo_by_name():
    store = VectorStore(None)
    query = "Polo 2024"
    ranked = rank_vehicles(query, store.scores(query), 3)
    assert ranked[0]["model"] == "Polo"


def test_filters_suvs_by_price_and_transmission():
    store = VectorStore(None)
    query = "SUVs automáticos até 150 mil"
    ranked = rank_vehicles(query, store.scores(query), 6)
    assert ranked
    assert all(item["body"] == "suv" for item in ranked)
    assert all(item["price"] <= 150000 for item in ranked)
    assert all(item["transmission"] == "automatico" for item in ranked)
    assert all(item["model"] != "Compass" for item in ranked)


def test_refuses_vehicle_outside_inventory():
    store = VectorStore(None)
    query = "Quero um carro que voa movido a plutônio"
    assert rank_vehicles(query, store.scores(query)) == []
