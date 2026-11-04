"""Dominio de RutaNorte Logistics (Unidad 3): reglas de la OrdenDeServicio.

Los nombres siguen el lenguaje ubicuo G-01 a G-23 de la Unidad 2 y el DDD de la Unidad 3.
Las reglas viven aqui, no en los servicios ni en la infraestructura.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

# ---------------------------------------------------------------- errores de negocio


class ErrorDeDominio(Exception):
    """Base de los errores de negocio, explicados en terminos del dominio."""


class DatosInvalidos(ErrorDeDominio):
    """Un valor viola una regla de un Value Object (por ejemplo, peso negativo)."""


class CotizacionNoConfirmada(ErrorDeDominio):
    """Solo una cotizacion 'Confirmado' genera una orden (US-03, US-04)."""


class OperacionNoPermitidaParaRol(ErrorDeDominio):
    """Solo Operaciones genera o modifica ordenes confirmadas (RN-02)."""


class UnidadNoDisponible(ErrorDeDominio):
    """Una unidad averiada o ya asignada no se asigna (US-07, G-14, OP-07)."""


class OperadorNoDisponible(ErrorDeDominio):
    """Un operador indispuesto o ya asignado no se asigna (US-08)."""


class TransicionDeEstatusInvalida(ErrorDeDominio):
    """El estatus solo avanza por las transiciones validas de G-16."""


class EvidenciaIncompleta(ErrorDeDominio):
    """No hay entrega sin evidencia completa (RN-03, CE-03, US-13)."""


class DiscrepanciaDeMercancia(ErrorDeDominio):
    """La mercancia recibida no coincide con la declarada (G-13, US-05, US-09)."""

    def __init__(self, tipo: TipoDeDiscrepancia):
        super().__init__(f"Discrepancia de mercancia: {tipo.value}")
        self.tipo = tipo


class ControlesDeAltoValorRequeridos(ErrorDeDominio):
    """Una carga de alto valor exige unidad escolta y doble firma (US-12, G-12)."""


class OrdenDetenida(ErrorDeDominio):
    """Una orden con mercancia rechazada no avanza hasta que Operaciones resuelva (US-09)."""


class OrdenNoEncontrada(ErrorDeDominio):
    """No existe una orden con ese numero."""


# ---------------------------------------------------------------- enumeraciones


class EstatusDelServicio(StrEnum):
    """G-16: etapas ordenadas del envio."""

    SOLICITADO = "Solicitado"
    COTIZADO = "Cotizado"
    CONFIRMADO = "Confirmado"
    UNIDAD_ASIGNADA = "Unidad asignada"
    RECOLECTADO = "Recolectado"
    EN_TRANSITO = "En tránsito"
    LLEGADA_A_DESTINO = "Llegada a destino"
    ENTREGADO = "Entregado"


class Rol(StrEnum):
    CLIENTE = "Cliente"
    VENTAS = "Ventas"
    OPERACIONES = "Operaciones"
    OPERADOR = "Operador"
    ATENCION_AL_CLIENTE = "Atención al Cliente"
    GERENTE_DE_OPERACIONES = "Gerente de Operaciones"


class TipoDeDiscrepancia(StrEnum):
    """G-13: cantidad, tipo o estado."""

    CANTIDAD = "cantidad"
    TIPO = "tipo"
    ESTADO = "estado"


class TipoDeIncidencia(StrEnum):
    AVERIA = "avería"
    MERCANCIA_RECHAZADA = "mercancía rechazada"
    DESTINATARIO_AUSENTE = "destinatario ausente"
    ENTREGA_CON_DANOS_O_FALTANTES = "entrega con danos o faltantes"


class DisponibilidadDeUnidad(StrEnum):
    DISPONIBLE = "disponible"
    ASIGNADA = "asignada"
    AVERIADA = "averiada"


class DisponibilidadDeOperador(StrEnum):
    DISPONIBLE = "disponible"
    ASIGNADO = "asignado"
    INDISPUESTO = "indispuesto"


# ---------------------------------------------------------------- value objects


@dataclass(frozen=True)
class MercanciaDeclarada:
    """G-10: tipo, peso y valor declarados. Se compara contra lo recibido."""

    tipo: str
    peso_kg: Decimal
    valor: Decimal

    def __post_init__(self):
        if not self.tipo.strip():
            raise DatosInvalidos("El tipo de mercancia es obligatorio")
        if self.peso_kg < 0 or self.valor < 0:
            raise DatosInvalidos("Peso y valor no pueden ser negativos")


@dataclass(frozen=True)
class EvidenciaDeEntrega:
    """G-20: foto, firma digital, datos de quien recibe, coordenadas y estampa de tiempo.

    Es frozen: una vez creada no se puede modificar (RN-03, inalterable).
    """

    receptor_nombre: str
    receptor_identificacion: str
    foto_ref: str | None
    firma_ref: str | None
    latitud: float | None
    longitud: float | None
    estampa: datetime | None

    def esta_completa(self) -> bool:
        textos = (self.receptor_nombre, self.receptor_identificacion, self.foto_ref, self.firma_ref)
        hay_textos = all(t is not None and t.strip() for t in textos)
        hay_datos = None not in (self.latitud, self.longitud, self.estampa)
        return hay_textos and hay_datos


@dataclass(frozen=True)
class EntradaDeBitacora:
    """G-18: evento, estatus, fecha y responsable. No se modifica."""

    evento: str
    estatus: EstatusDelServicio
    fecha: datetime
    responsable: str


@dataclass(frozen=True)
class Incidencia:
    tipo: TipoDeIncidencia
    tipo_discrepancia: TipoDeDiscrepancia
    fotos: tuple[str, ...]
    observaciones: str


@dataclass(frozen=True)
class EventoDeDominio:
    """Un hecho que ya ocurrio, por eso su nombre esta en pasado."""

    nombre: str
    numero_orden: str
    ocurrio_en: datetime


# ---------------------------------------------------------------- politica (Domain Service)


class PoliticaDeCargaDeAltoValor:
    """G-12 / US-12: evalua si una carga supera el umbral y devuelve los controles.

    El umbral NO esta definido en la Unidad 2 (pendiente H-01), por eso se recibe como
    configuracion y nunca se fija dentro de la regla.
    """

    CONTROLES = ("unidad escolta", "doble firma")

    def __init__(self, umbral: Decimal):
        self.umbral = umbral

    def es_alto_valor(self, valor: Decimal) -> bool:
        return valor > self.umbral  # "supera el umbral": igual al umbral NO es alto valor

    def controles_obligatorios(self, valor: Decimal) -> tuple[str, ...]:
        return self.CONTROLES if self.es_alto_valor(valor) else ()


# ---------------------------------------------------------------- aggregates auxiliares


@dataclass
class Cotizacion:
    """Aggregate Cotizacion (version minima: lo necesario para generar la orden)."""

    folio: str
    estatus: EstatusDelServicio
    mercancia: MercanciaDeclarada

    def esta_confirmada(self) -> bool:
        return self.estatus is EstatusDelServicio.CONFIRMADO


class Unidad:
    def __init__(self, codigo: str, disponibilidad=DisponibilidadDeUnidad.DISPONIBLE):
        self.codigo = codigo
        self.disponibilidad = disponibilidad

    def puede_asignarse(self) -> bool:
        return self.disponibilidad is DisponibilidadDeUnidad.DISPONIBLE

    def asignar(self) -> None:
        if not self.puede_asignarse():
            raise UnidadNoDisponible(self.codigo)
        self.disponibilidad = DisponibilidadDeUnidad.ASIGNADA


class Operador:
    def __init__(
        self, identificador: str, disponibilidad=DisponibilidadDeOperador.DISPONIBLE, es_comodin=False
    ):
        self.identificador = identificador
        self.disponibilidad = disponibilidad
        self.es_comodin = es_comodin  # G-07: atributo, no subclase (LSP)

    def puede_asignarse(self) -> bool:
        return self.disponibilidad is DisponibilidadDeOperador.DISPONIBLE

    def asignar(self) -> None:
        if not self.puede_asignarse():
            raise OperadorNoDisponible(self.identificador)
        self.disponibilidad = DisponibilidadDeOperador.ASIGNADO


# ---------------------------------------------------------------- aggregate OrdenDeServicio

_SIGUIENTE = {
    EstatusDelServicio.UNIDAD_ASIGNADA: EstatusDelServicio.RECOLECTADO,
    EstatusDelServicio.RECOLECTADO: EstatusDelServicio.EN_TRANSITO,
    EstatusDelServicio.EN_TRANSITO: EstatusDelServicio.LLEGADA_A_DESTINO,
    EstatusDelServicio.LLEGADA_A_DESTINO: EstatusDelServicio.ENTREGADO,
}


class OrdenDeServicio:
    """Raiz del aggregate. Protege las invariantes 1 a 7 de la ficha del DDD.

    Cada metodo valida primero, cambia el estado despues y registra el evento al final:
    si una validacion falla, la orden conserva su estado y no se anuncia nada.
    """

    def __init__(
        self,
        numero: str,
        folio_cotizacion: str,
        unidad_id: str,
        operador_id: str,
        mercancia: MercanciaDeclarada,
        estatus: EstatusDelServicio,
        bitacora=None,
        incidencias=None,
        evidencia: EvidenciaDeEntrega | None = None,
        detenida: bool = False,
    ):
        self.numero = numero
        self.folio_cotizacion = folio_cotizacion
        self.unidad_id = unidad_id
        self.operador_id = operador_id
        self.mercancia = mercancia
        self.estatus = estatus
        self.bitacora = list(bitacora or [])
        self.incidencias = list(incidencias or [])
        self.evidencia = evidencia
        self.detenida = detenida
        self._eventos: list[EventoDeDominio] = []

    # ---- creacion (CU-01)

    @classmethod
    def generar(cls, numero, cotizacion, unidad, operador, rol, ahora=None):
        ahora = ahora or datetime.now(UTC)
        if rol is not Rol.OPERACIONES:
            raise OperacionNoPermitidaParaRol(f"El rol {rol.value} no puede generar ordenes")
        if not cotizacion.esta_confirmada():
            raise CotizacionNoConfirmada(cotizacion.folio)
        if not unidad.puede_asignarse():
            raise UnidadNoDisponible(unidad.codigo)
        if not operador.puede_asignarse():
            raise OperadorNoDisponible(operador.identificador)
        unidad.asignar()
        operador.asignar()
        orden = cls(
            numero,
            cotizacion.folio,
            unidad.codigo,
            operador.identificador,
            cotizacion.mercancia,
            EstatusDelServicio.UNIDAD_ASIGNADA,
        )
        orden._registrar("OrdenDeServicioGenerada", rol.value, ahora)
        orden._publicar("UnidadAsignada", ahora)
        return orden

    # ---- comportamiento del negocio

    def registrar_recoleccion(
        self, tipo_inspeccionado, peso_inspeccionado, politica, controles_confirmados, responsable, ahora=None
    ):
        """CU-02: valida la mercancia en origen y pasa a 'Recolectado'."""
        self._validar_transicion(EstatusDelServicio.RECOLECTADO)
        discrepancia = self._detectar_discrepancia(tipo_inspeccionado, peso_inspeccionado)
        if discrepancia is not None:
            raise DiscrepanciaDeMercancia(discrepancia)
        if politica.es_alto_valor(self.mercancia.valor) and not controles_confirmados:
            raise ControlesDeAltoValorRequeridos(", ".join(politica.CONTROLES))
        self._avanzar(EstatusDelServicio.RECOLECTADO, "MercanciaRecolectada", responsable, ahora)

    def rechazar_mercancia(self, tipo_discrepancia, fotos, observaciones, responsable, ahora=None):
        """CU-03: registra la incidencia y detiene el flujo (sin estatus propio, H-05)."""
        self._validar_transicion(EstatusDelServicio.RECOLECTADO)
        if not fotos:
            raise EvidenciaIncompleta("El rechazo requiere fotos")
        incidencia = Incidencia(
            TipoDeIncidencia.MERCANCIA_RECHAZADA, tipo_discrepancia, tuple(fotos), observaciones
        )
        self.incidencias.append(incidencia)
        self.detenida = True
        self._registrar("MercanciaRechazada", responsable, ahora)
        return incidencia

    def iniciar_traslado(self, responsable, ahora=None):
        """US-06 (dentro del aggregate, fuera de los CU seleccionados)."""
        self._validar_transicion(EstatusDelServicio.EN_TRANSITO)
        self._avanzar(EstatusDelServicio.EN_TRANSITO, "TrasladoIniciado", responsable, ahora)

    def registrar_llegada(self, responsable, ahora=None):
        """Supuesto: G-16 incluye 'Llegada a destino' aunque no hay historia (H-06)."""
        self._validar_transicion(EstatusDelServicio.LLEGADA_A_DESTINO)
        self._avanzar(
            EstatusDelServicio.LLEGADA_A_DESTINO, "LlegadaADestinoRegistrada", responsable, ahora
        )

    def registrar_entrega(self, evidencia, responsable, ahora=None):
        """CU-04: no pasa a 'Entregado' sin evidencia completa, y esta es inalterable."""
        self._validar_transicion(EstatusDelServicio.ENTREGADO)
        if not evidencia.esta_completa():
            raise EvidenciaIncompleta("Faltan datos de la evidencia de entrega")
        self.evidencia = evidencia
        self._avanzar(EstatusDelServicio.ENTREGADO, "EntregaRealizada", responsable, ahora)

    def pull_events(self) -> list[EventoDeDominio]:
        eventos, self._eventos = self._eventos, []
        return eventos

    # ---- internos

    def _validar_transicion(self, destino: EstatusDelServicio) -> None:
        if self.detenida:
            raise OrdenDetenida(self.numero)
        if _SIGUIENTE.get(self.estatus) is not destino:
            raise TransicionDeEstatusInvalida(f"{self.estatus.value} -> {destino.value}")

    def _detectar_discrepancia(self, tipo_inspeccionado, peso_inspeccionado):
        if tipo_inspeccionado.strip().casefold() != self.mercancia.tipo.strip().casefold():
            return TipoDeDiscrepancia.TIPO
        if peso_inspeccionado != self.mercancia.peso_kg:  # sin tolerancia: no esta definida
            return TipoDeDiscrepancia.CANTIDAD
        return None

    def _avanzar(self, destino, evento, responsable, ahora) -> None:
        self.estatus = destino
        self._registrar(evento, responsable, ahora)

    def _registrar(self, evento, responsable, ahora) -> None:
        ahora = ahora or datetime.now(UTC)
        self.bitacora.append(EntradaDeBitacora(evento, self.estatus, ahora, responsable))
        self._publicar(evento, ahora)

    def _publicar(self, nombre, ahora) -> None:
        self._eventos.append(EventoDeDominio(nombre, self.numero, ahora))
