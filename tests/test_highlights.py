"""Manual highlight CRUD — user-created annotations, no LLM involved."""


def _make_highlight(client, paper_id, **overrides):
    body = {
        "page": 0,
        "rects": [[72.0, 72.0, 300.0, 90.0]],
        "text": "Attention",
        "color": "yellow",
    }
    body.update(overrides)
    return client.post(f"/api/papers/{paper_id}/highlights", json=body)


def test_highlight_create_list_patch_delete(client, paper_id):
    # Starts empty.
    assert client.get(f"/api/papers/{paper_id}/highlights").json()["highlights"] == []

    created = _make_highlight(client, paper_id)
    assert created.status_code == 200, created.text
    hl = created.json()
    hid = hl["id"]
    assert hl["page"] == 0
    assert hl["color"] == "yellow"
    assert hl["kind"] == "user"

    # Appears in the list.
    listed = client.get(f"/api/papers/{paper_id}/highlights").json()["highlights"]
    assert [h["id"] for h in listed] == [hid]

    # Patch a field.
    patched = client.patch(f"/api/highlights/{hid}", json={"color": "green"})
    assert patched.status_code == 200
    after = client.get(f"/api/papers/{paper_id}/highlights").json()["highlights"][0]
    assert after["color"] == "green"

    # Delete it.
    assert client.delete(f"/api/highlights/{hid}").status_code == 200
    assert client.get(f"/api/papers/{paper_id}/highlights").json()["highlights"] == []


def test_highlight_requires_page_and_rects(client, paper_id):
    r = client.post(f"/api/papers/{paper_id}/highlights", json={"text": "x"})
    assert r.status_code == 422
