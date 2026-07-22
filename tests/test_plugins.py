"""Manifest plugin marketplace and installation lifecycle."""


def test_marketplace_install_and_uninstall(client):
    snapshot = client.get("/api/plugins")
    assert snapshot.status_code == 200, snapshot.text
    body = snapshot.json()
    assert body["api_version"] == 1
    assert {item["status"] for item in body["contribution_points"]} >= {"stable", "planned"}
    assert len(body["coming_soon"]) >= 4
    assert {item["id"] for item in body["core"]} >= {
        "core.summary", "core.notes", "core.personal-notes", "core.mindmap"
    }
    assert {item["id"] for item in body["marketplace"]} >= {
        "gloss.critical-review",
        "gloss.implementation-blueprint",
        "gloss.evidence-table",
        "gloss.presentation-outline",
    }
    plugin = body["marketplace"][0]

    try:
        installed = client.post(f"/api/plugins/{plugin['id']}/install")
        assert installed.status_code == 200, installed.text
        assert installed.json()["id"] == plugin["id"]
        after = client.get("/api/plugins").json()
        assert plugin["id"] in {item["id"] for item in after["installed"]}
        market_item = next(item for item in after["marketplace"] if item["id"] == plugin["id"])
        assert market_item["installed"] is True
    finally:
        client.delete(f"/api/plugins/{plugin['id']}")

    assert plugin["id"] not in {
        item["id"] for item in client.get("/api/plugins").json()["installed"]
    }


def test_plugin_uninstall_removes_generated_cache(client):
    from app.library import store

    plugin_id = "example.cache-cleanup"
    manifest = {
        "id": plugin_id,
        "api_version": 1,
        "name": "Cache Cleanup",
        "version": "1.0.0",
        "author": "Test",
        "description": "Checks uninstall cleanup.",
        "permissions": ["paper:read", "ai:complete"],
        "prompt": "Summarize the paper.",
    }
    assert client.post("/api/plugins/install", json={"manifest": manifest}).status_code == 200
    store.cache_set("paper-a", f"plugin:{plugin_id}:1.0.0:prompt:zh", "cached")
    store.cache_set("paper-a", "summary:zh", "keep")

    assert client.delete(f"/api/plugins/{plugin_id}").status_code == 200
    assert store.cache_get("paper-a", f"plugin:{plugin_id}:1.0.0:prompt:zh") is None
    assert store.cache_get("paper-a", "summary:zh") == "keep"


def test_custom_manifest_install_is_declarative_and_validated(client):
    manifest = {
        "id": "example.my-reading-lens",
        "api_version": 1,
        "name": "My Reading Lens",
        "version": "1.2.0",
        "author": "Reader",
        "description": "Analyze the paper using my own checklist.",
        "tab_name": "My Lens",
        "permissions": ["paper:read", "ai:complete"],
        "prompt": "List three claims and the evidence supplied for each claim.",
    }
    installed = client.post("/api/plugins/install", json={"manifest": manifest})
    assert installed.status_code == 200, installed.text
    assert installed.json()["output"] == "markdown"
    assert installed.json()["contributes"]["paper_sidebar"]["tab_name"] == "My Lens"
    assert "entry" not in installed.json()
    try:
        assert manifest["id"] in {
            item["id"] for item in client.get("/api/plugins").json()["installed"]
        }
    finally:
        client.delete(f"/api/plugins/{manifest['id']}")

    invalid = {**manifest, "id": "../outside"}
    rejected = client.post("/api/plugins/install", json={"manifest": invalid})
    assert rejected.status_code == 400

    future = {**manifest, "id": "example.future", "api_version": 99}
    rejected = client.post("/api/plugins/install", json={"manifest": future})
    assert rejected.status_code == 400


def test_plugin_manifest_schema_and_template(client):
    schema = client.get("/api/plugins/schema")
    assert schema.status_code == 200
    assert schema.json()["properties"]["api_version"]["const"] == 1
    assert "paper_sidebar" in schema.json()["properties"]["contributes"]["properties"]

    template = client.get("/api/plugins/template")
    assert template.status_code == 200
    assert template.json()["api_version"] == 1
    assert template.json()["contributes"]["paper_sidebar"]["tab_name"]


def test_plugin_run_requires_installation(client, paper_id):
    response = client.post(
        f"/api/plugins/not-installed/papers/{paper_id}/run", json={}
    )
    assert response.status_code == 400
