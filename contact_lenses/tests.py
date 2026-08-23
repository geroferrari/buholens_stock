import datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from customers.models import Cliente
from prescriptions.models import Receta
from sales.models import Vendedor, Venta

from .models import PruebaLentesContacto


def _fecha(dias=0):
    """Datetime a N días de ahora (aware o naive según USE_TZ, como el modelo)."""
    return timezone.now() + datetime.timedelta(days=dias)


def _venta_confirmada(vendedor, total):
    return Venta.objects.create(
        vendedor=vendedor, estado=Venta.Estado.CONFIRMADA, total=Decimal(total),
    )


class PruebaModelTests(TestCase):
    def setUp(self):
        self.vendedor = Vendedor.objects.create(nombre="Guille")

    def test_estado_default_es_agendada(self):
        p = PruebaLentesContacto.objects.create(
            vendedor=self.vendedor, fecha_hora=_fecha(1), nombre_suelto="Juan",
        )
        self.assertEqual(p.estado, PruebaLentesContacto.Estado.AGENDADA)

    def test_nombre_cliente_cae_al_nombre_suelto(self):
        p = PruebaLentesContacto.objects.create(
            vendedor=self.vendedor, fecha_hora=_fecha(1), nombre_suelto="Walk In",
        )
        self.assertEqual(p.nombre_cliente, "Walk In")

    def test_nombre_cliente_usa_el_cliente_cargado(self):
        cliente = Cliente.objects.create(nombre="Ana", apellido="García")
        p = PruebaLentesContacto.objects.create(
            vendedor=self.vendedor, fecha_hora=_fecha(1), cliente=cliente,
        )
        self.assertEqual(p.nombre_cliente, "Ana García")

    def test_monto_venta_solo_cuenta_con_venta_confirmada(self):
        p = PruebaLentesContacto.objects.create(
            vendedor=self.vendedor, fecha_hora=_fecha(1), nombre_suelto="X",
        )
        self.assertIsNone(p.monto_venta)  # sin venta

        # Venta abierta (en el POS, sin confirmar): todavía no cuenta.
        p.venta = Venta.objects.create(
            vendedor=self.vendedor, estado=Venta.Estado.ABIERTA, total=Decimal("500"),
        )
        self.assertFalse(p.venta_confirmada)
        self.assertIsNone(p.monto_venta)

        # Venta confirmada: cuenta.
        p.venta = _venta_confirmada(self.vendedor, "1000")
        self.assertTrue(p.venta_confirmada)
        self.assertEqual(p.monto_venta, Decimal("1000"))


class AgendaYAgendarTests(TestCase):
    """Lo que un empleado (no admin) puede hacer: ver el calendario, agendar,
    reprogramar y cancelar."""

    def setUp(self):
        self.vendedor = Vendedor.objects.create(nombre="Guille")
        self.cliente = Cliente.objects.create(nombre="Juan", apellido="Prueba")
        self.user = User.objects.create_user("empleado", password="test12345")
        self.client.force_login(self.user)

    def _crear_prueba(self, **kwargs):
        defaults = dict(vendedor=self.vendedor, fecha_hora=_fecha(0), cliente=self.cliente)
        defaults.update(kwargs)
        return PruebaLentesContacto.objects.create(**defaults)

    def test_agendar_crea_la_prueba(self):
        fecha = (timezone.localdate() + datetime.timedelta(days=3)).isoformat()
        self.client.post(reverse("contact_lenses:prueba_nueva"), {
            "cliente": self.cliente.id, "vendedor": self.vendedor.id,
            "fecha_hora": f"{fecha}T10:00", "observaciones": "",
        })
        self.assertEqual(PruebaLentesContacto.objects.count(), 1)
        p = PruebaLentesContacto.objects.get()
        self.assertEqual(p.cliente_id, self.cliente.id)
        self.assertEqual(p.estado, PruebaLentesContacto.Estado.AGENDADA)

    def test_agendar_sin_cliente_es_rechazado(self):
        fecha = (timezone.localdate() + datetime.timedelta(days=3)).isoformat()
        self.client.post(reverse("contact_lenses:prueba_nueva"), {
            "cliente": "", "vendedor": self.vendedor.id,
            "fecha_hora": f"{fecha}T10:00", "observaciones": "",
        })
        self.assertEqual(PruebaLentesContacto.objects.count(), 0)

    def test_calendario_muestra_la_prueba(self):
        self._crear_prueba()
        resp = self.client.get(reverse("contact_lenses:agenda"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Juan Prueba")

    def test_form_de_agendar_renderiza(self):
        resp = self.client.get(reverse("contact_lenses:prueba_nueva"))
        self.assertEqual(resp.status_code, 200)

    def test_detalle_renderiza(self):
        p = self._crear_prueba()
        resp = self.client.get(reverse("contact_lenses:prueba_detalle", args=[p.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Juan Prueba")

    def test_empleado_puede_cancelar(self):
        p = self._crear_prueba()
        self.client.post(reverse("contact_lenses:marcar_cancelada", args=[p.pk]))
        p.refresh_from_db()
        self.assertEqual(p.estado, PruebaLentesContacto.Estado.CANCELADA)


class VentaDeLaPruebaTests(TestCase):
    """La prueba con venta crea/linkea una Venta real del POS (admin)."""

    def setUp(self):
        self.vendedor = Vendedor.objects.create(nombre="Guille")
        self.cliente = Cliente.objects.create(nombre="Juan", apellido="Prueba")
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.client.force_login(self.admin)

    def _crear_prueba(self):
        return PruebaLentesContacto.objects.create(
            vendedor=self.vendedor, fecha_hora=_fecha(0), cliente=self.cliente,
        )

    def test_iniciar_venta_crea_venta_linkeada_y_va_al_pos(self):
        p = self._crear_prueba()
        resp = self.client.post(reverse("contact_lenses:iniciar_venta", args=[p.pk]))
        p.refresh_from_db()
        self.assertIsNotNone(p.venta_id)
        self.assertEqual(p.estado, PruebaLentesContacto.Estado.REALIZADA)
        self.assertEqual(p.venta.cliente_id, self.cliente.id)
        self.assertEqual(p.venta.vendedor_id, self.vendedor.id)
        self.assertRedirects(
            resp, reverse("sales:pos", args=[p.venta_id]), fetch_redirect_response=False,
        )

    def test_iniciar_venta_dos_veces_reusa_la_abierta(self):
        p = self._crear_prueba()
        self.client.post(reverse("contact_lenses:iniciar_venta", args=[p.pk]))
        p.refresh_from_db()
        venta1 = p.venta_id
        self.client.post(reverse("contact_lenses:iniciar_venta", args=[p.pk]))
        p.refresh_from_db()
        self.assertEqual(p.venta_id, venta1)  # no creó otra
        self.assertEqual(Venta.objects.count(), 1)

    def test_realizada_sin_venta(self):
        p = self._crear_prueba()
        self.client.post(reverse("contact_lenses:marcar_realizada_sin_venta", args=[p.pk]))
        p.refresh_from_db()
        self.assertEqual(p.estado, PruebaLentesContacto.Estado.REALIZADA)
        self.assertIsNone(p.venta_id)


class PermisosEmpleadoTests(TestCase):
    """El empleado ve el calendario y agenda, pero NO toca la parte de plata:
    no registra ventas ni ve los montos."""

    def setUp(self):
        self.vendedor = Vendedor.objects.create(nombre="Guille")
        self.cliente = Cliente.objects.create(nombre="Juan", apellido="Prueba")
        self.empleado = User.objects.create_user("empleado", password="test12345")
        self.client.force_login(self.empleado)

    def _crear_prueba(self, **kwargs):
        defaults = dict(vendedor=self.vendedor, fecha_hora=_fecha(0), cliente=self.cliente)
        defaults.update(kwargs)
        return PruebaLentesContacto.objects.create(**defaults)

    def test_empleado_no_puede_iniciar_venta(self):
        p = self._crear_prueba()
        self.client.post(reverse("contact_lenses:iniciar_venta", args=[p.pk]))
        p.refresh_from_db()
        self.assertIsNone(p.venta_id)
        self.assertEqual(p.estado, PruebaLentesContacto.Estado.AGENDADA)  # sin cambios

    def test_empleado_no_ve_montos_en_el_calendario(self):
        self._crear_prueba(
            estado=PruebaLentesContacto.Estado.REALIZADA,
            venta=_venta_confirmada(self.vendedor, "12345"),
        )
        resp = self.client.get(reverse("contact_lenses:agenda"))
        self.assertNotContains(resp, "12345")


class AvisoPruebaAgendadaTests(TestCase):
    """Al agendar una prueba se le avisa al celular a quien la tiene que hacer.
    El aviso es 'mejor esfuerzo': si falla, la prueba se agenda igual."""

    def setUp(self):
        self.usuario_guille = User.objects.create_user("guille", password="test12345")
        self.vendedor = Vendedor.objects.create(nombre="Guille", usuario=self.usuario_guille)
        self.cliente = Cliente.objects.create(nombre="Juan", apellido="Prueba")
        self.empleado = User.objects.create_user("empleado", password="test12345")
        self.client.force_login(self.empleado)

    def _agendar(self, vendedor=None):
        fecha = (timezone.localdate() + datetime.timedelta(days=2)).isoformat()
        return self.client.post(reverse("contact_lenses:prueba_nueva"), {
            "cliente": self.cliente.id, "vendedor": (vendedor or self.vendedor).id,
            "fecha_hora": f"{fecha}T10:00", "observaciones": "",
        })

    @patch("notificaciones.services.enviar_push_a_vendedor")
    def test_avisa_a_la_persona_que_hace_la_prueba(self, mock_enviar):
        self._agendar()
        self.assertTrue(mock_enviar.called)
        self.assertEqual(mock_enviar.call_args.args[0], self.vendedor)

    @patch("notificaciones.services.enviar_push_a_vendedor")
    def test_no_se_avisa_a_si_mismo_si_no_tiene_celular_propio(self, mock_enviar):
        # Guille agenda su propia prueba y no tiene ningún celular registrado:
        # avisarle sería avisarse a sí mismo.
        self.client.force_login(self.usuario_guille)
        self._agendar()
        self.assertFalse(mock_enviar.called)

    @patch("notificaciones.services.enviar_push_a_vendedor")
    def test_vendedor_sin_usuario_vinculado_no_rompe(self, _mock):
        suelto = Vendedor.objects.create(nombre="Sin Usuario")
        self._agendar(vendedor=suelto)
        self.assertEqual(PruebaLentesContacto.objects.count(), 1)  # se agendó igual

    @patch("notificaciones.services.enviar_push_a_vendedor", side_effect=Exception("push caído"))
    def test_si_el_aviso_falla_la_prueba_igual_queda_agendada(self, _mock):
        self._agendar()
        self.assertEqual(PruebaLentesContacto.objects.count(), 1)


class RecordatorioDelDiaTests(TestCase):
    """El día de la prueba se le manda un recordatorio a quien la tiene que hacer."""

    def setUp(self):
        self.usuario = User.objects.create_user("guille", password="test12345")
        self.vendedor = Vendedor.objects.create(nombre="Guille", usuario=self.usuario)
        self.cliente = Cliente.objects.create(nombre="Juan", apellido="Prueba")

    def _prueba(self, dias=0, estado=PruebaLentesContacto.Estado.AGENDADA):
        return PruebaLentesContacto.objects.create(
            vendedor=self.vendedor, cliente=self.cliente, fecha_hora=_fecha(dias), estado=estado,
        )

    def _correr(self, **kwargs):
        from io import StringIO

        from django.core.management import call_command

        salida = StringIO()
        call_command("recordar_pruebas", stdout=salida, **kwargs)
        return salida.getvalue()

    @patch("notificaciones.services.enviar_push_a_vendedor", return_value=1)
    def test_avisa_las_pruebas_de_hoy(self, mock_enviar):
        prueba = self._prueba(dias=0)
        self._correr()
        self.assertTrue(mock_enviar.called)
        self.assertEqual(mock_enviar.call_args.args[0], self.vendedor)
        prueba.refresh_from_db()
        self.assertTrue(prueba.recordatorio_enviado)

    @patch("notificaciones.services.enviar_push_a_vendedor", return_value=1)
    def test_no_avisa_las_de_otros_dias(self, mock_enviar):
        self._prueba(dias=3)
        self._prueba(dias=-3)
        self._correr()
        self.assertFalse(mock_enviar.called)

    @patch("notificaciones.services.enviar_push_a_vendedor", return_value=1)
    def test_no_avisa_dos_veces_la_misma_prueba(self, mock_enviar):
        self._prueba(dias=0)
        self._correr()
        self._correr()  # segunda corrida del cron el mismo día
        self.assertEqual(mock_enviar.call_count, 1)

    @patch("notificaciones.services.enviar_push_a_vendedor", return_value=1)
    def test_no_avisa_pruebas_canceladas_ni_realizadas(self, mock_enviar):
        self._prueba(dias=0, estado=PruebaLentesContacto.Estado.CANCELADA)
        self._prueba(dias=0, estado=PruebaLentesContacto.Estado.REALIZADA)
        self._correr()
        self.assertFalse(mock_enviar.called)

    @patch("notificaciones.services.enviar_push_a_vendedor", return_value=0)
    def test_si_no_se_pudo_avisar_se_reintenta_despues(self, mock_enviar):
        # Sin dispositivos: no se marca como avisada, así el próximo cron reintenta.
        prueba = self._prueba(dias=0)
        self._correr()
        prueba.refresh_from_db()
        self.assertFalse(prueba.recordatorio_enviado)

    @patch("notificaciones.services.enviar_push_a_vendedor", return_value=1)
    def test_dry_run_no_manda_ni_marca(self, mock_enviar):
        prueba = self._prueba(dias=0)
        salida = self._correr(dry_run=True)
        self.assertFalse(mock_enviar.called)
        prueba.refresh_from_db()
        self.assertFalse(prueba.recordatorio_enviado)
        self.assertIn("simulacro", salida)


class RecetaEnPruebaTests(TestCase):
    """Al agendar una prueba se ofrece cargar la graduación del cliente, que
    queda linkeada a la prueba y visible en el detalle."""

    def setUp(self):
        self.vendedor = Vendedor.objects.create(nombre="Guille")
        self.cliente = Cliente.objects.create(nombre="Juan", apellido="Prueba")
        self.user = User.objects.create_user("empleado", password="test12345")
        self.client.force_login(self.user)

    def _agendar(self):
        fecha = (timezone.localdate() + datetime.timedelta(days=2)).isoformat()
        return self.client.post(reverse("contact_lenses:prueba_nueva"), {
            "cliente": self.cliente.id, "vendedor": self.vendedor.id,
            "fecha_hora": f"{fecha}T10:00", "observaciones": "",
        })

    def _datos_receta(self, **extra):
        base = {
            "cliente": self.cliente.id, "fecha_recibido": "2026-07-01", "fecha_entrega": "",
            "medico": "", "obra_social": "",
            "lejos_od_esfera": "", "lejos_od_cilindro": "", "lejos_od_eje": "", "lejos_od_adicion": "",
            "lejos_oi_esfera": "", "lejos_oi_cilindro": "", "lejos_oi_eje": "", "lejos_oi_adicion": "",
            "lejos_dnp": "", "lejos_tipo_cristal": "", "lejos_color_cristal": "", "lejos_tratamientos": "",
            "cerca_od_esfera": "", "cerca_od_cilindro": "", "cerca_od_eje": "",
            "cerca_oi_esfera": "", "cerca_oi_cilindro": "", "cerca_oi_eje": "",
            "cerca_dnp": "", "cerca_tipo_cristal": "", "cerca_color_cristal": "", "cerca_tratamientos": "",
            "es_bifocal_multifocal": "", "di_lejos": "", "di_cerca": "", "altura": "",
            "observaciones": "",
        }
        base.update(extra)
        return base

    def test_cliente_sin_receta_es_llevado_a_cargar_la_graduacion(self):
        resp = self._agendar()
        prueba = PruebaLentesContacto.objects.get()
        # Redirige al formulario de receta con la prueba en el query.
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("prescriptions:receta_nueva"), resp.url)
        self.assertIn(f"prueba={prueba.pk}", resp.url)

    def test_cliente_con_receta_va_directo_al_detalle(self):
        Receta.objects.create(cliente=self.cliente, fecha_recibido=timezone.localdate())
        resp = self._agendar()
        prueba = PruebaLentesContacto.objects.get()
        self.assertRedirects(resp, reverse("contact_lenses:prueba_detalle", args=[prueba.pk]))

    def test_cargar_receta_desde_la_prueba_la_linkea_y_vuelve(self):
        prueba = PruebaLentesContacto.objects.create(
            vendedor=self.vendedor, cliente=self.cliente, fecha_hora=_fecha(2),
        )
        url = reverse("prescriptions:receta_nueva") + f"?prueba={prueba.pk}"
        resp = self.client.post(url, self._datos_receta(lejos_od_esfera="-2.00"))
        self.assertRedirects(resp, reverse("contact_lenses:prueba_detalle", args=[prueba.pk]))
        prueba.refresh_from_db()
        self.assertIsNotNone(prueba.receta_id)
        self.assertEqual(float(prueba.receta.lejos_od_esfera), -2.0)

    def test_detalle_muestra_la_graduacion(self):
        receta = Receta.objects.create(
            cliente=self.cliente, fecha_recibido=timezone.localdate(), lejos_od_esfera="-1.75",
        )
        prueba = PruebaLentesContacto.objects.create(
            vendedor=self.vendedor, cliente=self.cliente, fecha_hora=_fecha(2), receta=receta,
        )
        resp = self.client.get(reverse("contact_lenses:prueba_detalle", args=[prueba.pk]))
        self.assertContains(resp, "Graduación del cliente")
        # Muestra la tabla de graduación y linkea a la receta completa.
        self.assertContains(resp, "Ver receta completa")
        self.assertContains(resp, reverse("prescriptions:receta_detalle", args=[receta.pk]))

    def test_detalle_sin_receta_ofrece_cargarla(self):
        prueba = PruebaLentesContacto.objects.create(
            vendedor=self.vendedor, cliente=self.cliente, fecha_hora=_fecha(2),
        )
        resp = self.client.get(reverse("contact_lenses:prueba_detalle", args=[prueba.pk]))
        self.assertContains(resp, "no tiene una graduación cargada")
        self.assertContains(resp, f"?prueba={prueba.pk}")
