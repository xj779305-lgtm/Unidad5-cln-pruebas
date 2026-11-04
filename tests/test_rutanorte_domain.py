"""Pruebas de dominio de RutaNorte Logistics (E9). Sin base de datos ni servicios externos.

Cada prueba cp01..cp13 corresponde a un caso de la matriz matriz_pruebas_rutanorte.csv.
"""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.rutanorte.domain import (
    ControlesDeAltoValorRequeridos,
    Cotizacion,
    CotizacionNoConfirmada,
    DatosInvalidos,
    DiscrepanciaDeMercancia,
    DisponibilidadDeOperador,
    DisponibilidadDeUnidad,
    EstatusDelServicio,
    EvidenciaDeEntrega,
    EvidenciaIncompleta,
    MercanciaDeclarada,
    OperacionNoPermitidaParaRol,
    Operador,
    OperadorNoDisponible,
    OrdenDeServicio,
    OrdenDetenida,
    PoliticaDeCargaDeAltoValor,
    Rol,
    TipoDeDiscrepancia,
    TransicionDeEstatusInvalida,
    Unidad,
    UnidadNoDisponible,
)

AHORA = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
UMBRAL = Decimal(100000)  # supuesto de prueba: el umbral real esta pendiente (H-01)
POLITICA = PoliticaDeCargaDeAltoValor(UMBRAL)
E = EstatusDelServicio


def mercancia(peso="1500", valor="50000", tipo="Autopartes"):
    return MercanciaDeclarada(tipo, Decimal(peso), Decimal(valor))


def orden_en(estatus, valor="50000"):
    return OrdenDeServicio("OS-500", "F-001", "Eco-12", "OP-7", mercancia(valor=valor), estatus)


def evidencia_completa():
    return EvidenciaDeEntrega("Ana Pérez", "INE-123", "foto-1", "firma-1", 25.67, -100.31, AHORA)


def cotizacion(estatus=E.CONFIRMADO):
    return Cotizacion("F-001", estatus, mercancia())


def eventos(orden):
    return [e.nombre for e in orden.pull_events()]


# ------------------------------------------------ R1 Evidencia de entrega completa (RN-03, CE-03)


def test_cp01_entrega_con_evidencia_completa_pasa_a_entregado():
    orden = orden_en(E.LLEGADA_A_DESTINO)
    orden.registrar_entrega(evidencia_completa(), "OP-7", AHORA)
    assert orden.estatus is E.ENTREGADO
    assert orden.evidencia == evidencia_completa()
    assert orden.bitacora[-1].evento == "EntregaRealizada"
    assert eventos(orden) == ["EntregaRealizada"]


def test_cp02_entrega_sin_firma_se_rechaza_y_no_cambia_nada():
    orden = orden_en(E.LLEGADA_A_DESTINO)
    sin_firma = replace(evidencia_completa(), firma_ref=None)
    with pytest.raises(EvidenciaIncompleta):
        orden.registrar_entrega(sin_firma, "OP-7", AHORA)
    assert orden.estatus is E.LLEGADA_A_DESTINO
    assert orden.evidencia is None
    assert orden.bitacora == []
    assert eventos(orden) == []


def test_cp03_no_se_puede_saltar_llegada_a_destino():
    orden = orden_en(E.EN_TRANSITO)
    with pytest.raises(TransicionDeEstatusInvalida):
        orden.registrar_entrega(evidencia_completa(), "OP-7", AHORA)
    assert orden.estatus is E.EN_TRANSITO
    assert orden.evidencia is None


# ------------------------------------------------ R2 Solo Operaciones genera la orden (RN-02)


def test_cp04_operaciones_genera_orden_de_cotizacion_confirmada():
    unidad, operador = Unidad("Eco-12"), Operador("OP-7")
    orden = OrdenDeServicio.generar("OS-500", cotizacion(), unidad, operador, Rol.OPERACIONES, AHORA)
    assert orden.estatus is E.UNIDAD_ASIGNADA
    assert orden.folio_cotizacion == "F-001"
    assert unidad.disponibilidad is DisponibilidadDeUnidad.ASIGNADA
    assert operador.disponibilidad is DisponibilidadDeOperador.ASIGNADO
    assert eventos(orden) == ["OrdenDeServicioGenerada", "UnidadAsignada"]


def test_cp05_ventas_no_puede_generar_la_orden():
    unidad = Unidad("Eco-12")
    with pytest.raises(OperacionNoPermitidaParaRol):
        OrdenDeServicio.generar("OS-500", cotizacion(), unidad, Operador("OP-7"), Rol.VENTAS, AHORA)
    assert unidad.disponibilidad is DisponibilidadDeUnidad.DISPONIBLE


def test_cp06_cotizacion_cotizada_no_genera_orden():
    unidad = Unidad("Eco-12")
    with pytest.raises(CotizacionNoConfirmada):
        OrdenDeServicio.generar(
            "OS-500", cotizacion(E.COTIZADO), unidad, Operador("OP-7"), Rol.OPERACIONES, AHORA
        )
    assert unidad.disponibilidad is DisponibilidadDeUnidad.DISPONIBLE


# ------------------------------------------------ R3 Carga de alto valor (US-12, G-12)


def test_cp07_alto_valor_con_controles_confirmados_se_recolecta():
    orden = orden_en(E.UNIDAD_ASIGNADA, valor="100000.01")
    orden.registrar_recoleccion("Autopartes", Decimal(1500), POLITICA, True, "OP-7", AHORA)
    assert orden.estatus is E.RECOLECTADO
    assert eventos(orden) == ["MercanciaRecolectada"]


def test_cp08_alto_valor_sin_controles_no_se_recolecta():
    orden = orden_en(E.UNIDAD_ASIGNADA, valor="250000")
    with pytest.raises(ControlesDeAltoValorRequeridos):
        orden.registrar_recoleccion("Autopartes", Decimal(1500), POLITICA, False, "OP-7", AHORA)
    assert orden.estatus is E.UNIDAD_ASIGNADA
    assert eventos(orden) == []


def test_cp09_valor_igual_al_umbral_no_es_alto_valor():
    orden = orden_en(E.UNIDAD_ASIGNADA, valor="100000")
    orden.registrar_recoleccion("Autopartes", Decimal(1500), POLITICA, False, "OP-7", AHORA)
    assert orden.estatus is E.RECOLECTADO
    assert POLITICA.controles_obligatorios(Decimal(100000)) == ()
    assert POLITICA.controles_obligatorios(Decimal("100000.01")) == ("unidad escolta", "doble firma")


# ------------------------------------------------ R4 La mercancia coincide con lo declarado (US-05)


def test_cp10_mercancia_que_coincide_se_recolecta():
    orden = orden_en(E.UNIDAD_ASIGNADA)
    orden.registrar_recoleccion("autopartes", Decimal(1500), POLITICA, False, "OP-7", AHORA)
    assert orden.estatus is E.RECOLECTADO
    assert orden.bitacora[-1].estatus is E.RECOLECTADO


def test_cp11_peso_distinto_es_discrepancia_y_no_se_recolecta():
    orden = orden_en(E.UNIDAD_ASIGNADA)
    with pytest.raises(DiscrepanciaDeMercancia) as error:
        orden.registrar_recoleccion("Autopartes", Decimal(1400), POLITICA, False, "OP-7", AHORA)
    assert error.value.tipo is TipoDeDiscrepancia.CANTIDAD
    assert orden.estatus is E.UNIDAD_ASIGNADA
    assert eventos(orden) == []


def test_cp12_diferencia_minima_de_peso_ya_es_discrepancia():
    orden = orden_en(E.UNIDAD_ASIGNADA)
    with pytest.raises(DiscrepanciaDeMercancia):
        orden.registrar_recoleccion("Autopartes", Decimal("1500.01"), POLITICA, False, "OP-7", AHORA)
    assert orden.estatus is E.UNIDAD_ASIGNADA


def test_tipo_distinto_es_discrepancia_de_tipo():
    orden = orden_en(E.UNIDAD_ASIGNADA)
    with pytest.raises(DiscrepanciaDeMercancia) as error:
        orden.registrar_recoleccion("Textiles", Decimal(1500), POLITICA, False, "OP-7", AHORA)
    assert error.value.tipo is TipoDeDiscrepancia.TIPO


# ------------------------------------------------ R5 (complementaria) Unidad averiada (US-07, G-14)


def test_cp13_unidad_averiada_no_se_asigna_y_no_se_modifica_nada():
    unidad = Unidad("Eco-12", DisponibilidadDeUnidad.AVERIADA)
    operador = Operador("OP-7")
    with pytest.raises(UnidadNoDisponible):
        OrdenDeServicio.generar("OS-500", cotizacion(), unidad, operador, Rol.OPERACIONES, AHORA)
    assert unidad.disponibilidad is DisponibilidadDeUnidad.AVERIADA
    assert operador.disponibilidad is DisponibilidadDeOperador.DISPONIBLE


# ------------------------------------------------ pruebas de apoyo (no son casos de la matriz)


def test_operador_indispuesto_no_se_asigna():
    operador = Operador("OP-7", DisponibilidadDeOperador.INDISPUESTO, es_comodin=True)
    unidad = Unidad("Eco-12")
    with pytest.raises(OperadorNoDisponible):
        OrdenDeServicio.generar("OS-500", cotizacion(), unidad, operador, Rol.OPERACIONES, AHORA)
    assert unidad.disponibilidad is DisponibilidadDeUnidad.DISPONIBLE


@pytest.mark.parametrize(("tipo", "peso", "valor"), [(" ", "10", "10"), ("Carga", "-1", "10")])
def test_mercancia_declarada_invalida(tipo, peso, valor):
    with pytest.raises(DatosInvalidos):
        MercanciaDeclarada(tipo, Decimal(peso), Decimal(valor))


def test_flujo_completo_deja_una_entrada_de_bitacora_por_cambio_de_estatus():
    unidad, operador = Unidad("Eco-12"), Operador("OP-7")
    orden = OrdenDeServicio.generar("OS-500", cotizacion(), unidad, operador, Rol.OPERACIONES, AHORA)
    orden.registrar_recoleccion("Autopartes", Decimal(1500), POLITICA, False, "OP-7", AHORA)
    orden.iniciar_traslado("OP-7", AHORA)
    orden.registrar_llegada("OP-7", AHORA)
    orden.registrar_entrega(evidencia_completa(), "OP-7", AHORA)
    assert [b.estatus for b in orden.bitacora] == [
        E.UNIDAD_ASIGNADA,
        E.RECOLECTADO,
        E.EN_TRANSITO,
        E.LLEGADA_A_DESTINO,
        E.ENTREGADO,
    ]


def test_orden_entregada_no_admite_otra_entrega_y_su_evidencia_es_inalterable():
    orden = orden_en(E.LLEGADA_A_DESTINO)
    orden.registrar_entrega(evidencia_completa(), "OP-7", AHORA)
    with pytest.raises(TransicionDeEstatusInvalida):
        orden.registrar_entrega(replace(evidencia_completa(), foto_ref="otra"), "OP-7", AHORA)
    with pytest.raises(FrozenInstanceError):
        orden.evidencia.foto_ref = "alterada"
    assert orden.evidencia.foto_ref == "foto-1"


def test_rechazo_detiene_la_orden_y_exige_fotos():
    orden = orden_en(E.UNIDAD_ASIGNADA)
    with pytest.raises(EvidenciaIncompleta):
        orden.rechazar_mercancia(TipoDeDiscrepancia.TIPO, [], "caja distinta", "OP-7", AHORA)
    assert not orden.detenida
    incidencia = orden.rechazar_mercancia(
        TipoDeDiscrepancia.TIPO, ["foto-1"], "caja distinta", "OP-7", AHORA
    )
    assert incidencia.fotos == ("foto-1",)
    assert orden.detenida
    assert orden.estatus is E.UNIDAD_ASIGNADA
    assert eventos(orden) == ["MercanciaRechazada"]
    with pytest.raises(OrdenDetenida):
        orden.registrar_recoleccion("Autopartes", Decimal(1500), POLITICA, False, "OP-7", AHORA)


def test_asignar_directamente_un_recurso_no_disponible_se_rechaza():
    with pytest.raises(UnidadNoDisponible):
        Unidad("Eco-12", DisponibilidadDeUnidad.AVERIADA).asignar()
    with pytest.raises(OperadorNoDisponible):
        Operador("OP-7", DisponibilidadDeOperador.INDISPUESTO).asignar()
