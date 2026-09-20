"""Catalogue search and detail."""
from .factories import make_medicine, make_rule

URL = "/api/v1/medicines"


def test_search_matches_partial_name_or_code(client, session):
    make_medicine(session, code="MED00001", name="Amoxicillin 500")
    make_medicine(session, code="MED00002", name="Paracetamol 500")

    by_name = client.get(URL, params={"q": "moxi"}).json()
    by_code = client.get(URL, params={"q": "00002"}).json()

    assert [m["code"] for m in by_name["items"]] == ["MED00001"]
    assert [m["code"] for m in by_code["items"]] == ["MED00002"]


def test_search_is_case_insensitive_and_treats_wildcards_literally(client, session):
    make_medicine(session, code="MED00001", name="Amoxicillin 500")

    assert len(client.get(URL, params={"q": "AMOXI"}).json()["items"]) == 1
    assert client.get(URL, params={"q": "%"}).json()["items"] == []


def test_listing_paginates_by_cursor(client, session):
    for i in range(1, 6):
        make_medicine(session, code=f"MED0000{i}", name=f"Medicine {i}")

    first = client.get(URL, params={"limit": 2}).json()
    second = client.get(URL, params={"limit": 2, "cursor": first["next_cursor"]}).json()

    assert [m["name"] for m in first["items"]] == ["Medicine 1", "Medicine 2"]
    assert [m["name"] for m in second["items"]] == ["Medicine 3", "Medicine 4"]


def test_last_page_has_no_cursor(client, session):
    make_medicine(session)

    body = client.get(URL, params={"limit": 25}).json()

    assert body["next_cursor"] is None


def test_a_malformed_cursor_is_a_client_error(client, session):
    response = client.get(URL, params={"cursor": "not-a-cursor"})

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_CURSOR"


def test_detail_includes_the_rule_in_force(client, session):
    medicine = make_medicine(session)
    make_rule(session, medicine, start="2020-01-01", end="2024-01-01", per_dispense=10)
    current = make_rule(session, medicine, start="2024-01-01", per_dispense=42)

    body = client.get(f"{URL}/MED00001").json()

    assert body["current_rule"]["id"] == current.id
    assert body["current_rule"]["max_quantity_per_dispense"] == 42


def test_detail_without_any_rule_in_force(client, session):
    make_medicine(session)

    body = client.get(f"{URL}/MED00001").json()

    assert body["current_rule"] is None


def test_unknown_code_is_404_in_the_problem_shape(client, session):
    response = client.get(f"{URL}/NOPE")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert response.headers["content-type"].startswith("application/problem+json")
