"""Pruebas de integracion de RutaNorte (E9): base de datos (commit/rollback) y mocks.

Usan SQLite en memoria (no es un motor productivo; el motor real esta pendiente, H-04) y
Mock para el almacen de evidencias y el notificador, asi que no se guarda ni se envia nada real.
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.rutanorte.application import ServicioDeEntrega, ServicioDeRecoleccion
from src.rutanorte.domain import (
    EstatusDelServicio,
    EvidenciaDeEntrega,
    EvidenciaIncompleta,
    MercanciaDeclarada,
    OrdenDeServicio,
    OrdenNoEncontrada,
    PoliticaDeCargaDeAltoValor,
    TipoDeDiscrepancia,
)
from src.rutanorte.repository import Base, OrdenDeServicioSqlRepository, UnidadDeTrabajoSql

AHORA = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
E = EstatusDelServicio
POLITICA = PoliticaDeCargaDeAltoValor(Decimal(100000))


def crear_motor():
    motor = create_engine("sqlite://")
    Base.metadata.create_all(motor)
    return motor


def orden_en(estatus, numero="OS-500"):
    mercancia = MercanciaDeclarada("Autopartes", Decimal(1500), Decimal(50000))
    return OrdenDeServicio(numero, "F-001", "Eco-12", "OP-7", mercancia, estatus)


def evidencia_completa():
    return EvidenciaDeEntrega("Ana Pérez", "INE-123", "foto-1", "firma-1", 25.67, -100.31, AHORA)


def sembrar(motor, orden):
    with Session(motor) as sesion:
        OrdenDeServicioSqlRepository(sesion).guardar(orden)
        sesion.commit()


def leer(motor, numero="OS-500"):
    with Session(motor) as sesion:
        return OrdenDeServicioSqlRepository(sesion).obtener_por_numero(numero)


# ------------------------------------------------ CP-14 Persistencia: commit y rollback


def test_cp14_commit_guarda_la_orden_completa_y_rollback_no_deja_nada():
    motor = crear_motor()
    orden = orden_en(E.LLEGADA_A_DESTINO)
    orden.registrar_entrega(evidencia_completa(), "OP-7", AHORA)
    sembrar(motor, orden)  # commit

    guardada = leer(motor)
    assert guardada.estatus is E.ENTREGADO
    assert guardada.evidencia == evidencia_completa()
    assert [b.evento for b in guardada.bitacora] == ["EntregaRealizada"]
    assert guardada.mercancia.peso_kg == Decimal(1500)

    with Session(motor) as sesion:  # rollback
        OrdenDeServicioSqlRepository(sesion).guardar(orden_en(E.UNIDAD_ASIGNADA, "OS-501"))
        sesion.rollback()
    with pytest.raises(OrdenNoEncontrada):
        leer(motor, "OS-501")


# ------------------------------------------------ CP-15 Mock del notificador


def test_cp15_rechazo_notifica_a_operaciones_una_vez_y_despues_del_commit():
    motor = crear_motor()
    sembrar(motor, orden_en(E.UNIDAD_ASIGNADA))
    almacen = Mock()
    almacen.guardar.side_effect = ["foto-1", "foto-2"]
    notificador = Mock()
    with Session(motor) as sesion:
        servicio = ServicioDeRecoleccion(
            OrdenDeServicioSqlRepository(sesion),
            POLITICA,
            almacen,
            notificador,
            UnidadDeTrabajoSql(sesion),
        )
        incidencia = servicio.rechazar_mercancia(
            "OS-500", TipoDeDiscrepancia.TIPO, [b"a", b"b"], "caja distinta", "OP-7", AHORA
        )
    assert incidencia.fotos == ("foto-1", "foto-2")
    notificador.alertar.assert_called_once_with(
        "Operaciones", "OS-500", "Mercancía rechazada en origen: tipo"
    )
    guardada = leer(motor)
    assert guardada.detenida
    assert len(guardada.incidencias) == 1


def test_rechazo_sin_fotos_hace_rollback_y_no_notifica():
    motor = crear_motor()
    sembrar(motor, orden_en(E.UNIDAD_ASIGNADA))
    notificador = Mock()
    with Session(motor) as sesion:
        servicio = ServicioDeRecoleccion(
            OrdenDeServicioSqlRepository(sesion), POLITICA, Mock(), notificador, UnidadDeTrabajoSql(sesion)
        )
        with pytest.raises(EvidenciaIncompleta):
            servicio.rechazar_mercancia("OS-500", TipoDeDiscrepancia.TIPO, [], "x", "OP-7", AHORA)
    notificador.alertar.assert_not_called()
    assert not leer(motor).detenida


# ------------------------------------------------ CP-16 Mock del almacen de evidencias que falla


def test_cp16_si_el_almacen_falla_la_orden_no_pasa_a_entregado():
    motor = crear_motor()
    sembrar(motor, orden_en(E.LLEGADA_A_DESTINO))
    almacen = Mock()
    almacen.guardar.side_effect = TimeoutError("almacen sin respuesta")
    with Session(motor) as sesion:
        servicio = ServicioDeEntrega(
            OrdenDeServicioSqlRepository(sesion), almacen, UnidadDeTrabajoSql(sesion)
        )
        with pytest.raises(TimeoutError):
            servicio.registrar_entrega(
                "OS-500", "Ana Pérez", "INE-123", b"foto", b"firma", 25.67, -100.31, "OP-7", AHORA
            )
    guardada = leer(motor)
    assert guardada.estatus is E.LLEGADA_A_DESTINO
    assert guardada.evidencia is None


# ------------------------------------------------ pruebas de apoyo del servicio


def test_entrega_correcta_por_el_servicio_guarda_evidencia_y_estatus():
    motor = crear_motor()
    sembrar(motor, orden_en(E.LLEGADA_A_DESTINO))
    almacen = Mock()
    almacen.guardar.side_effect = ["foto-1", "firma-1"]
    with Session(motor) as sesion:
        servicio = ServicioDeEntrega(
            OrdenDeServicioSqlRepository(sesion), almacen, UnidadDeTrabajoSql(sesion)
        )
        estatus = servicio.registrar_entrega(
            "OS-500", "Ana Pérez", "INE-123", b"foto", b"firma", 25.67, -100.31, "OP-7", AHORA
        )
    assert estatus is E.ENTREGADO
    assert leer(motor).evidencia == evidencia_completa()


def test_entrega_sin_firma_por_el_servicio_hace_rollback():
    motor = crear_motor()
    sembrar(motor, orden_en(E.LLEGADA_A_DESTINO))
    almacen = Mock()
    almacen.guardar.return_value = "foto-1"
    with Session(motor) as sesion:
        servicio = ServicioDeEntrega(
            OrdenDeServicioSqlRepository(sesion), almacen, UnidadDeTrabajoSql(sesion)
        )
        with pytest.raises(EvidenciaIncompleta):
            servicio.registrar_entrega(
                "OS-500", "Ana Pérez", "INE-123", b"foto", None, 25.67, -100.31, "OP-7", AHORA
            )
    almacen.guardar.assert_called_once_with(b"foto")
    assert leer(motor).estatus is E.LLEGADA_A_DESTINO


def test_recoleccion_por_el_servicio_actualiza_el_estatus():
    motor = crear_motor()
    sembrar(motor, orden_en(E.UNIDAD_ASIGNADA))
    with Session(motor) as sesion:
        servicio = ServicioDeRecoleccion(
            OrdenDeServicioSqlRepository(sesion), POLITICA, Mock(), Mock(), UnidadDeTrabajoSql(sesion)
        )
        estatus = servicio.registrar_recoleccion(
            "OS-500", "Autopartes", Decimal(1500), False, "OP-7", AHORA
        )
    assert estatus is E.RECOLECTADO
    assert leer(motor).bitacora[-1].evento == "MercanciaRecolectada"


def test_recoleccion_con_discrepancia_por_el_servicio_hace_rollback():
    motor = crear_motor()
    sembrar(motor, orden_en(E.UNIDAD_ASIGNADA))
    with Session(motor) as sesion:
        servicio = ServicioDeRecoleccion(
            OrdenDeServicioSqlRepository(sesion), POLITICA, Mock(), Mock(), UnidadDeTrabajoSql(sesion)
        )
        with pytest.raises(Exception, match="Discrepancia"):
            servicio.registrar_recoleccion("OS-500", "Autopartes", Decimal(1400), False, "OP-7", AHORA)
    assert leer(motor).estatus is E.UNIDAD_ASIGNADA


def test_si_el_commit_falla_se_revierte_y_no_se_notifica():
    """CU-03, escenario de error: el commit falla despues de guardar los cambios.

    Se lee dentro de la MISMA sesion: sin rollback seguiria viendo el cambio sin confirmar.
    """
    motor = crear_motor()
    sembrar(motor, orden_en(E.UNIDAD_ASIGNADA))
    almacen = Mock()
    almacen.guardar.return_value = "foto-1"
    notificador = Mock()
    with Session(motor) as sesion:
        unidad_de_trabajo = UnidadDeTrabajoSql(sesion)
        unidad_de_trabajo.confirmar = Mock(side_effect=RuntimeError("el commit fallo"))
        servicio = ServicioDeRecoleccion(
            OrdenDeServicioSqlRepository(sesion), POLITICA, almacen, notificador, unidad_de_trabajo
        )
        with pytest.raises(RuntimeError, match="commit"):
            servicio.rechazar_mercancia(
                "OS-500", TipoDeDiscrepancia.TIPO, [b"a"], "caja distinta", "OP-7", AHORA
            )
        en_la_misma_sesion = OrdenDeServicioSqlRepository(sesion).obtener_por_numero("OS-500")
        assert not en_la_misma_sesion.detenida
        assert en_la_misma_sesion.incidencias == []
    notificador.alertar.assert_not_called()
