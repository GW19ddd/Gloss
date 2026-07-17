"""Chat *session* management — creating/listing a conversation and reading its
messages. Creating a session does not call the LLM (only POST /api/chat does)."""


def test_chat_session_create_and_list(client, paper_id):
    assert client.get(f"/api/papers/{paper_id}/chats").json()["chats"] == []

    created = client.post(f"/api/papers/{paper_id}/chats", json={})
    assert created.status_code == 200
    chat = created.json()
    assert chat["id"]
    assert chat["paper_id"] == paper_id

    chats = client.get(f"/api/papers/{paper_id}/chats").json()["chats"]
    assert chat["id"] in [c["id"] for c in chats]


def test_new_chat_has_no_messages(client, paper_id):
    chat_id = client.post(f"/api/papers/{paper_id}/chats", json={}).json()["id"]
    r = client.get(f"/api/chats/{chat_id}/messages")
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert isinstance(msgs, list)
    assert msgs == []
