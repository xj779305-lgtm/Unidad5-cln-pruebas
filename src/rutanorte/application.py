"""Application Services de RutaNorte (Unidad 3, Etapas 4 y 5).

Los servicios solo coordinan: cargan la orden, invocan el comportamiento del dominio,
guardan y devuelven el resultado. Las reglas viven en domain.py. Dependen de puertos
(Protocol), nunca de SQL, del almacen de archivos ni del canal de notificaciones.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from src.rutanorte.domain import (
    EstatusDelServicio,
    EvidenciaDeEntrega,
    Incidencia,
    OrdenDeServicio,
    PoliticaDeCargaDeAltoValor,
    TipoDeDiscrepancia,
)

# ---------------------------------------------------------------- puertos (ADR-03, ADR-05)


class OrdenDeServicioRepository(Protocol):
    def obtener_por_numero(self, numero: str) -> OrdenDeServicio: ...

    def guardar(self, orden: OrdenDeServicio) -> None: ...


class IUnidadDeTrabajo(Protocol):
    def iniciar(self) -> None: ...

    def confirmar(self) -> None: ...

    def revertir(self) -> None: ...


class IAlmacenDeEvidencias(Protocol):
    def guardar(self, contenido: bytes) -> str:
        """Guarda un archivo (foto o firma) y devuelve su referencia."""
        ...


class INotificador(Protocol):
    def alertar(self, destino: str, numero_orden: str, mensaje: str) -> None: ...


# ---------------------------------------------------------------- servicios


class ServicioDeRecoleccion:
    """CU-02 registrarRecoleccion y CU-03 rechazarMercancia."""

    def __init__(
        self,
        ordenes: OrdenDeServicioRepository,
        politica: PoliticaDeCargaDeAltoValor,
        almacen: IAlmacenDeEvidencias,
        notificador: INotificador,
        unidad_de_trabajo: IUnidadDeTrabajo,
    ):
        self.ordenes = ordenes
        self.politica = politica
        self.almacen = almacen
        self.notificador = notificador
        self.uow = unidad_de_trabajo

    def registrar_recoleccion(
        self, numero, tipo_inspeccionado, peso_inspeccionado, controles_confirmados, responsable, ahora=None
    ) -> EstatusDelServicio:
        self.uow.iniciar()
        try:
            orden = self.ordenes.obtener_por_numero(numero)
            orden.registrar_recoleccion(
                tipo_inspeccionado,
                peso_inspeccionado,
                self.politica,
                controles_confirmados,
                responsable,
                ahora,
            )
            self.ordenes.guardar(orden)
            self.uow.confirmar()
        except Exception:
            self.uow.revertir()
            raise
        return orden.estatus

    def rechazar_mercancia(
        self,
        numero: str,
        tipo_discrepancia: TipoDeDiscrepancia,
        fotos: list[bytes],
        observaciones: str,
        responsable: str,
        ahora: datetime | None = None,
    ) -> Incidencia:
        self.uow.iniciar()
        try:
            orden = self.ordenes.obtener_por_numero(numero)
            referencias = [self.almacen.guardar(foto) for foto in fotos]
            incidencia = orden.rechazar_mercancia(
                tipo_discrepancia, referencias, observaciones, responsable, ahora
            )
            self.ordenes.guardar(orden)
            self.uow.confirmar()
        except Exception:
            self.uow.revertir()
            raise
        # El aviso sale solo despues del commit: no se anuncia algo que no se guardo.
        self.notificador.alertar(
            "Operaciones", numero, f"Mercancía rechazada en origen: {tipo_discrepancia.value}"
        )
        return incidencia


class ServicioDeEntrega:
    """CU-04 registrarEntrega."""

    def __init__(
        self,
        ordenes: OrdenDeServicioRepository,
        almacen: IAlmacenDeEvidencias,
        unidad_de_trabajo: IUnidadDeTrabajo,
    ):
        self.ordenes = ordenes
        self.almacen = almacen
        self.uow = unidad_de_trabajo

    def registrar_entrega(
        self,
        numero: str,
        receptor_nombre: str,
        receptor_identificacion: str,
        foto: bytes | None,
        firma: bytes | None,
        latitud: float | None,
        longitud: float | None,
        responsable: str,
        ahora: datetime | None = None,
    ) -> EstatusDelServicio:
        ahora = ahora or datetime.now(UTC)
        self.uow.iniciar()
        try:
            orden = self.ordenes.obtener_por_numero(numero)
            foto_ref = self.almacen.guardar(foto) if foto else None
            firma_ref = self.almacen.guardar(firma) if firma else None
            evidencia = EvidenciaDeEntrega(
                receptor_nombre, receptor_identificacion, foto_ref, firma_ref, latitud, longitud, ahora
            )
            orden.registrar_entrega(evidencia, responsable, ahora)
            self.ordenes.guardar(orden)
            self.uow.confirmar()
        except Exception:
            self.uow.revertir()
            raise
        return orden.estatus
