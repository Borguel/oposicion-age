"""Pruebas de marketing_utils.py: la sincronización de contactos con las
listas de marketing de Brevo. Se mockean requests.get/post -- lo que se
comprueba es que cada sincronización arma el payload correcto (listas a
añadir/a quitar, atributos) y que un fallo de red, de configuración o de
Brevo nunca se propaga hacia quien llama."""
from unittest.mock import MagicMock, patch

import pytest

import marketing_utils


@pytest.fixture(autouse=True)
def _limpiar_cache():
    marketing_utils._cache_listas.clear()
    yield
    marketing_utils._cache_listas.clear()


def _listas_existentes():
    """Respuesta de GET /contacts/lists con las 3 de oposición y las 4 de
    embudo ya creadas, para que las pruebas no tengan que pasar también por
    la rama de "crear lista"."""
    nombres = list(marketing_utils.LISTAS_OPOSICION.values()) + list(marketing_utils.LISTAS_ESTADO.values())
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"lists": [{"id": i, "name": nombre} for i, nombre in enumerate(nombres, start=1)]}
    mock.raise_for_status = MagicMock()
    return mock


def _contacto_ok():
    mock = MagicMock()
    mock.status_code = 204
    mock.text = ""
    return mock


def test_sin_api_key_no_llama_a_requests(monkeypatch):
    monkeypatch.delenv("BREVO_API_KEY", raising=False)
    with patch("marketing_utils.requests.get") as mock_get, patch("marketing_utils.requests.post") as mock_post:
        marketing_utils.sincronizar_contacto("u@example.com", estado="activo")
    mock_get.assert_not_called()
    mock_post.assert_not_called()


def test_sin_email_no_llama_a_requests(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    with patch("marketing_utils.requests.get") as mock_get, patch("marketing_utils.requests.post") as mock_post:
        marketing_utils.sincronizar_contacto("", estado="activo")
    mock_get.assert_not_called()
    mock_post.assert_not_called()


def test_sincroniza_estado_mueve_entre_listas_de_embudo(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    with patch("marketing_utils.requests.get", return_value=_listas_existentes()), \
         patch("marketing_utils.requests.post", return_value=_contacto_ok()) as mock_post:
        marketing_utils.sincronizar_contacto("u@example.com", nombre="Ana", estado="activo")

    payload = mock_post.call_args.kwargs["json"]
    assert payload["email"] == "u@example.com"
    assert payload["updateEnabled"] is True
    assert payload["attributes"] == {"NOMBRE": "Ana", "ESTADO_MARKETING": "activo"}

    id_activo = marketing_utils._cache_listas[marketing_utils.LISTAS_ESTADO["activo"]]
    assert payload["listIds"] == [id_activo]
    ids_otros_estados = {
        marketing_utils._cache_listas[nombre]
        for clave, nombre in marketing_utils.LISTAS_ESTADO.items()
        if clave != "activo"
    }
    assert set(payload["unlinkListIds"]) == ids_otros_estados


def test_sincroniza_oposicion_no_toca_las_listas_de_embudo(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    with patch("marketing_utils.requests.get", return_value=_listas_existentes()), \
         patch("marketing_utils.requests.post", return_value=_contacto_ok()) as mock_post:
        marketing_utils.sincronizar_contacto("u@example.com", oposicion="GACE")

    payload = mock_post.call_args.kwargs["json"]
    assert payload["attributes"] == {"OPOSICION": "GACE"}
    id_gace = marketing_utils._cache_listas[marketing_utils.LISTAS_OPOSICION["GACE"]]
    assert payload["listIds"] == [id_gace]
    assert "unlinkListIds" not in payload


def test_crea_la_lista_si_todavia_no_existe(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.setenv("BREVO_MARKETING_FOLDER_ID", "7")

    get_vacio = MagicMock()
    get_vacio.status_code = 200
    get_vacio.json.return_value = {"lists": []}
    get_vacio.raise_for_status = MagicMock()

    creada = MagicMock()
    creada.status_code = 201
    creada.json.return_value = {"id": 99}
    creada.raise_for_status = MagicMock()

    with patch("marketing_utils.requests.get", return_value=get_vacio), \
         patch("marketing_utils.requests.post", side_effect=[creada, _contacto_ok()]) as mock_post:
        marketing_utils.sincronizar_contacto("u@example.com", oposicion="AGE")

    primera_llamada = mock_post.call_args_list[0]
    assert primera_llamada.args[0] == marketing_utils.BREVO_LISTS_URL
    assert primera_llamada.kwargs["json"] == {"name": marketing_utils.LISTAS_OPOSICION["AGE"], "folderId": 7}

    payload_contacto = mock_post.call_args_list[1].kwargs["json"]
    assert payload_contacto["listIds"] == [99]


def test_error_http_de_brevo_no_lanza_excepcion(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    mock_error = MagicMock()
    mock_error.status_code = 400
    mock_error.text = "Bad Request"
    with patch("marketing_utils.requests.get", return_value=_listas_existentes()), \
         patch("marketing_utils.requests.post", return_value=mock_error):
        marketing_utils.sincronizar_contacto("u@example.com", estado="activo")  # no debe lanzar


def test_excepcion_de_red_no_se_propaga(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    with patch("marketing_utils.requests.get", side_effect=ConnectionError("caído")):
        marketing_utils.sincronizar_contacto("u@example.com", estado="activo")  # no debe lanzar
