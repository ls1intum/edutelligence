def test_authorized_home(client, authorized_headers):
    response = client.get("/", headers=authorized_headers)
    assert response.status_code == 200
    assert response.json() == {"message": "FastAPI server is running!"}


def test_unauthorized_home(client):
    response = client.get("/")
    assert response.status_code == 401


def test_invalid_token_home(client, invalid_headers):
    response = client.get("/", headers=invalid_headers)
    assert response.status_code == 401
