"""La conexión y la publicación en TikTok, incluidos los caminos que fallan."""

from __future__ import annotations

import pytest

from app.services import tiktok


# --------------------------------------------------------------------------
# Errores traducidos
# --------------------------------------------------------------------------
def test_los_errores_dicen_que_tocar():
    assert "clave o el secreto" in tiktok.traducir_error("invalid_client")
    assert "Redirect URI" in tiktok.traducir_error("invalid_request")
    assert "Scopes" in tiktok.traducir_error("invalid_scope")
    assert "borrador" in tiktok.traducir_error(
        "unaudited_client_can_only_post_to_private_accounts"
    )

    # uno que no conocemos: se dice tal cual, sin inventar
    suelto = tiktok.traducir_error("algo_raro", "ha pasado algo")
    assert "algo_raro" in suelto and "ha pasado algo" in suelto
    assert tiktok.traducir_error("", "")


class _Respuesta:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = str(payload)

    def json(self):
        return self._payload


def test_el_error_de_la_api_llega_con_su_codigo():
    with pytest.raises(tiktok.TikTokRechazo) as caja:
        tiktok._json(
            _Respuesta({"error": {"code": "access_token_invalid", "message": "x", "log_id": "9"}})
        )
    assert caja.value.codigo == "access_token_invalid"
    assert caja.value.log_id == "9"
    assert "vuelve a conectar" in str(caja.value).lower()


def test_el_error_del_canje_de_token_tambien():
    """El endpoint de tokens contesta distinto: error y error_description sueltos."""
    with pytest.raises(tiktok.TikTokRechazo) as caja:
        tiktok._json(
            _Respuesta(
                {
                    "error": "invalid_client",
                    "error_description": "Client key or secret is incorrect",
                    "log_id": "7",
                }
            )
        )
    assert caja.value.codigo == "invalid_client"
    assert "Client key" in str(caja.value)


def test_una_respuesta_correcta_pasa_sin_ruido():
    assert tiktok._json(_Respuesta({"data": {"ok": 1}, "error": {"code": "ok"}}))["data"]


# --------------------------------------------------------------------------
# PKCE
# --------------------------------------------------------------------------
def test_la_autorizacion_lleva_pkce(monkeypatch):
    monkeypatch.setattr(tiktok.settings, "tiktok_client_key", "awclave", raising=False)
    monkeypatch.setattr(tiktok.settings, "tiktok_client_secret", "secreto", raising=False)

    url = tiktok.build_auth_url("estado-1")
    assert "code_challenge_method=S256" in url
    assert "client_key=awclave" in url

    verificador = tiktok._verificadores["estado-1"]
    assert len(verificador) == 64
    # TikTok pide el reto en hexadecimal, no en base64url como el resto del mundo
    assert tiktok.reto_de(verificador) in url.replace("%3D", "=")
    assert len(tiktok.reto_de(verificador)) == 64


# --------------------------------------------------------------------------
# Privacidad admitida
# --------------------------------------------------------------------------
def test_se_usa_una_privacidad_que_la_cuenta_admita(monkeypatch):
    monkeypatch.setattr(
        tiktok,
        "fetch_creator_info",
        lambda _c: {"privacy_level_options": ["SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS"]},
    )
    assert tiktok.privacidad_valida({}, "PUBLIC_TO_EVERYONE") == "MUTUAL_FOLLOW_FRIENDS"
    assert tiktok.privacidad_valida({}, "SELF_ONLY") == "SELF_ONLY"

    # si TikTok no contesta, se intenta con lo pedido en vez de bloquearse
    def falla(_c):
        raise tiktok.TikTokError("sin conexión")

    monkeypatch.setattr(tiktok, "fetch_creator_info", falla)
    assert tiktok.privacidad_valida({}, "PUBLIC_TO_EVERYONE") == "PUBLIC_TO_EVERYONE"


# --------------------------------------------------------------------------
# Publicar de verdad (con TikTok de mentira)
# --------------------------------------------------------------------------
class ClienteFalso:
    """Un TikTok de juguete: apunta las llamadas y contesta lo que se le diga."""

    llamadas: list[str] = []
    rechazo_directo: str = ""

    def __init__(self, *_a, **_k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def post(self, url, **_kw):
        ClienteFalso.llamadas.append(url)
        if "creator_info" in url:
            return _Respuesta({"data": {"privacy_level_options": ["PUBLIC_TO_EVERYONE"]}})
        if url.endswith("/post/publish/video/init/"):
            if ClienteFalso.rechazo_directo:
                return _Respuesta(
                    {"error": {"code": ClienteFalso.rechazo_directo, "message": "no"}}
                )
            return _Respuesta({"data": {"publish_id": "p1", "upload_url": "https://subir"}})
        if url.endswith("/post/publish/inbox/video/init/"):
            return _Respuesta({"data": {"publish_id": "p2", "upload_url": "https://subir"}})
        if "status/fetch" in url:
            estado = "SEND_TO_USER_INBOX" if "p2" in str(_kw.get("json")) else "PUBLISH_COMPLETE"
            return _Respuesta({"data": {"status": estado, "share_url": "https://t/1"}})
        raise AssertionError(f"llamada inesperada: {url}")

    def put(self, _url, **_kw):
        return _Respuesta({}, status=200)


@pytest.fixture
def tiktok_de_mentira(monkeypatch, tmp_path):
    ClienteFalso.llamadas = []
    ClienteFalso.rechazo_directo = ""
    monkeypatch.setattr(tiktok.httpx, "Client", ClienteFalso)
    monkeypatch.setattr(tiktok.settings, "dry_run", False, raising=False)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"0" * 2048)
    return clip


def test_publicar_directo_cuando_se_puede(tiktok_de_mentira):
    resultado = tiktok.publish_video(
        {"access_token": "t", "expires_at": 9e12},
        video_path=tiktok_de_mentira,
        caption="hola",
    )
    assert resultado["mode"] == "direct"
    assert resultado["status"] == "PUBLISH_COMPLETE"
    assert resultado["notice"] == ""
    assert any(u.endswith("/post/publish/video/init/") for u in ClienteFalso.llamadas)


def test_si_la_app_no_esta_revisada_el_clip_va_a_la_bandeja(tiktok_de_mentira):
    """Antes se perdía el clip; ahora se deja como borrador y se avisa."""
    ClienteFalso.rechazo_directo = "unaudited_client_can_only_post_to_private_accounts"

    resultado = tiktok.publish_video(
        {"access_token": "t", "expires_at": 9e12},
        video_path=tiktok_de_mentira,
        caption="hola",
    )
    assert resultado["mode"] == "draft"
    assert resultado["status"] == "SEND_TO_USER_INBOX"
    assert "borrador" in resultado["notice"]
    assert any("inbox" in u for u in ClienteFalso.llamadas)


def test_un_error_que_no_tiene_arreglo_se_propaga(tiktok_de_mentira):
    ClienteFalso.rechazo_directo = "spam_risk_user_banned_from_posting"
    with pytest.raises(tiktok.TikTokRechazo):
        tiktok.publish_video(
            {"access_token": "t", "expires_at": 9e12},
            video_path=tiktok_de_mentira,
            caption="hola",
        )


# --------------------------------------------------------------------------
# Mientras la app no esté revisada
# --------------------------------------------------------------------------
def test_cuando_solo_cabe_lo_privado_se_va_a_la_bandeja():
    """Publicar «sólo para mí» no lo ve nadie y hay que ir a cambiarlo a mano;
    en la bandeja se publica en público con un toque."""
    assert tiktok.mejor_en_la_bandeja(["SELF_ONLY"], "PUBLIC_TO_EVERYONE") is True

    # si la cuenta admite público, se publica y punto
    assert tiktok.mejor_en_la_bandeja(
        ["PUBLIC_TO_EVERYONE", "SELF_ONLY"], "PUBLIC_TO_EVERYONE"
    ) is False
    # si lo que has pedido es justo privado, se respeta
    assert tiktok.mejor_en_la_bandeja(["SELF_ONLY"], "SELF_ONLY") is False
    # y sin respuesta de TikTok no se desvía nada
    assert tiktok.mejor_en_la_bandeja([], "PUBLIC_TO_EVERYONE") is False


class ClienteSinRevisar(ClienteFalso):
    """TikTok de juguete con la app aún sin auditar: sólo admite privado."""

    def post(self, url, **kw):
        if "creator_info" in url:
            ClienteFalso.llamadas.append(url)
            return _Respuesta({"data": {"privacy_level_options": ["SELF_ONLY"]}})
        return super().post(url, **kw)


def test_sin_revisar_el_clip_acaba_en_la_bandeja(monkeypatch, tmp_path):
    ClienteFalso.llamadas = []
    ClienteFalso.rechazo_directo = ""
    monkeypatch.setattr(tiktok.httpx, "Client", ClienteSinRevisar)
    monkeypatch.setattr(tiktok.settings, "dry_run", False, raising=False)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"0" * 2048)

    resultado = tiktok.publish_video(
        {"access_token": "t", "expires_at": 9e12},
        video_path=clip,
        caption="hola",
        privacy_level="PUBLIC_TO_EVERYONE",
    )

    assert resultado["mode"] == "draft"
    assert "bandeja" in resultado["notice"]
    # ni se intenta la publicación directa: se va derecho a la bandeja
    assert not any(u.endswith("/post/publish/video/init/") for u in ClienteFalso.llamadas)
    assert any("inbox" in u for u in ClienteFalso.llamadas)
