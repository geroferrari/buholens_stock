import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from .models import SuscripcionPush
from .services import enviar_push_a_usuario, push_configurado

SUB = {
    "endpoint": "https://push.example.com/abc123",
    "keys": {"p256dh": "clave-p256dh", "auth": "clave-auth"},
}
CON_CLAVES = override_settings(
    VAPID_PUBLIC_KEY="publica", VAPID_PRIVATE_KEY="privada", VAPID_CONTACTO="soporte@optica.local",
)


class SuscripcionPushTests(TestCase):
    """Alta/baja de la suscripción que genera el navegador."""

    def setUp(self):
        self.usuario = User.objects.create_user("empleado", password="test12345")
        self.client.login(username="empleado", password="test12345")

    def _suscribir(self, datos=SUB):
        return self.client.post(
            "/notificaciones/suscribir/", data=json.dumps(datos), content_type="application/json",
        )

    def test_suscribir_guarda_el_dispositivo(self):
        self.assertEqual(self._suscribir().status_code, 200)
        suscripcion = SuscripcionPush.objects.get()
        self.assertEqual(suscripcion.usuario, self.usuario)
        self.assertEqual(suscripcion.endpoint, SUB["endpoint"])

    def test_suscribir_dos_veces_el_mismo_dispositivo_no_duplica(self):
        self._suscribir()
        self._suscribir()
        self.assertEqual(SuscripcionPush.objects.count(), 1)

    def test_datos_invalidos_son_rechazados(self):
        self.assertEqual(self._suscribir({"cualquier": "cosa"}).status_code, 400)

    def test_desuscribir_borra_el_dispositivo(self):
        self._suscribir()
        self.client.post(
            "/notificaciones/desuscribir/",
            data=json.dumps({"endpoint": SUB["endpoint"]}), content_type="application/json",
        )
        self.assertEqual(SuscripcionPush.objects.count(), 0)

    def test_requiere_estar_logueado(self):
        self.client.logout()
        self.assertEqual(self._suscribir().status_code, 302)

    def test_estado_informa_si_ESTE_dispositivo_esta_suscripto(self):
        # El estado es por dispositivo (endpoint), no por usuario: la misma
        # persona puede tener avisos en el celular y no en la computadora.
        url = f"/notificaciones/estado/?endpoint={SUB['endpoint']}"
        self.assertFalse(self.client.get(url).json()["suscripto"])
        self._suscribir()
        self.assertTrue(self.client.get(url).json()["suscripto"])
        # Otro dispositivo del mismo usuario sigue sin suscribir.
        self.assertFalse(
            self.client.get("/notificaciones/estado/?endpoint=https://push.example.com/otro").json()["suscripto"]
        )

    def test_estado_devuelve_las_personas_para_elegir(self):
        from sales.models import Vendedor

        Vendedor.objects.create(nombre="Vero")
        nombres = [v["nombre"] for v in self.client.get("/notificaciones/estado/").json()["vendedores"]]
        self.assertIn("Vero", nombres)

    def test_suscribir_guarda_de_quien_es_el_dispositivo(self):
        from sales.models import Vendedor

        vero = Vendedor.objects.create(nombre="Vero")
        datos = dict(SUB, vendedor_id=vero.id)
        self.assertEqual(self._suscribir(datos).status_code, 200)
        self.assertEqual(SuscripcionPush.objects.get().vendedor, vero)


class EnvioPushTests(TestCase):
    """El envío es 'mejor esfuerzo': nunca debe romper al que lo llama."""

    def setUp(self):
        self.usuario = User.objects.create_user("guille", password="test12345")
        self.suscripcion = SuscripcionPush.objects.create(
            usuario=self.usuario, endpoint="https://push.example.com/x", p256dh="a", auth="b",
        )

    @override_settings(VAPID_PUBLIC_KEY="", VAPID_PRIVATE_KEY="")
    def test_sin_claves_vapid_el_push_queda_desactivado(self):
        # Explícito: no depende de si el .env local tiene claves cargadas.
        self.assertFalse(push_configurado())
        self.assertEqual(enviar_push_a_usuario(self.usuario, "Título", "Cuerpo"), 0)

    @CON_CLAVES
    @patch("pywebpush.webpush")
    def test_envia_a_cada_dispositivo(self, mock_webpush):
        self.assertEqual(enviar_push_a_usuario(self.usuario, "Título", "Cuerpo"), 1)
        self.assertTrue(mock_webpush.called)

    @CON_CLAVES
    @patch("pywebpush.webpush", side_effect=Exception("se cayó el servicio de push"))
    def test_si_el_envio_falla_no_explota(self, _mock):
        self.assertEqual(enviar_push_a_usuario(self.usuario, "Título", "Cuerpo"), 0)

    @CON_CLAVES
    @patch("pywebpush.webpush")
    def test_avisa_al_celular_de_esa_persona_aunque_compartan_login(self, mock_webpush):
        """El caso importante: Vero y Patri usan el MISMO usuario pero cada una
        tiene su celular. El aviso de Vero no le tiene que llegar a Patri."""
        from notificaciones.services import enviar_push_a_vendedor
        from sales.models import Vendedor

        mostrador = User.objects.create_user("mostrador", password="test12345")
        vero = Vendedor.objects.create(nombre="Vero", usuario=mostrador)
        patri = Vendedor.objects.create(nombre="Patri", usuario=mostrador)
        SuscripcionPush.objects.create(
            usuario=mostrador, vendedor=vero, endpoint="https://push.example.com/vero", p256dh="a", auth="b")
        SuscripcionPush.objects.create(
            usuario=mostrador, vendedor=patri, endpoint="https://push.example.com/patri", p256dh="a", auth="b")

        self.assertEqual(enviar_push_a_vendedor(vero, "Título", "Cuerpo"), 1)
        enviados = [c.kwargs["subscription_info"]["endpoint"] for c in mock_webpush.call_args_list]
        self.assertEqual(enviados, ["https://push.example.com/vero"])  # a Patri no le llegó

    @CON_CLAVES
    @patch("pywebpush.webpush")
    def test_si_no_declaro_de_quien_es_el_celular_usa_el_del_usuario(self, mock_webpush):
        from notificaciones.services import enviar_push_a_vendedor
        from sales.models import Vendedor

        vendedor = Vendedor.objects.create(nombre="Guille", usuario=self.usuario)
        # self.suscripcion es del usuario y no declaró vendedor: sirve de fallback.
        self.assertEqual(enviar_push_a_vendedor(vendedor, "Título", "Cuerpo"), 1)
        self.assertTrue(mock_webpush.called)

    @CON_CLAVES
    def test_suscripcion_caducada_se_da_de_baja_sola(self):
        from pywebpush import WebPushException

        error = WebPushException("gone")
        error.response = type("Resp", (), {"status_code": 410})()
        with patch("pywebpush.webpush", side_effect=error):
            self.assertEqual(enviar_push_a_usuario(self.usuario, "Título", "Cuerpo"), 0)
        self.assertFalse(SuscripcionPush.objects.filter(pk=self.suscripcion.pk).exists())
