"""Infraestructura: persistencia relacional de la OrdenDeServicio (Unidad 3, Etapa 5).

El dominio no conoce SQL ni el ORM. Los importes se guardan como texto para conservar
Decimal exacto en SQLite, y las fechas como ISO 8601.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from src.rutanorte.domain import (
    EntradaDeBitacora,
    EstatusDelServicio,
    EvidenciaDeEntrega,
    Incidencia,
    MercanciaDeclarada,
    OrdenDeServicio,
    OrdenNoEncontrada,
    TipoDeDiscrepancia,
    TipoDeIncidencia,
)


class Base(DeclarativeBase):
    pass


class OrdenRow(Base):
    __tablename__ = "rn_ordenes"

    numero: Mapped[str] = mapped_column(primary_key=True)
    folio_cotizacion: Mapped[str]
    unidad_id: Mapped[str]
    operador_id: Mapped[str]
    tipo_mercancia: Mapped[str]
    peso_kg: Mapped[str]
    valor: Mapped[str]
    estatus: Mapped[str]
    detenida: Mapped[bool]
    bitacora: Mapped[list[BitacoraRow]] = relationship(
        cascade="all, delete-orphan", order_by="BitacoraRow.id"
    )
    incidencias: Mapped[list[IncidenciaRow]] = relationship(
        cascade="all, delete-orphan", order_by="IncidenciaRow.id"
    )
    evidencia: Mapped[EvidenciaRow | None] = relationship(
        cascade="all, delete-orphan", uselist=False
    )


class BitacoraRow(Base):
    __tablename__ = "rn_bitacora"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    numero_orden: Mapped[str] = mapped_column(ForeignKey("rn_ordenes.numero"))
    evento: Mapped[str]
    estatus: Mapped[str]
    fecha: Mapped[str]
    responsable: Mapped[str]


class IncidenciaRow(Base):
    __tablename__ = "rn_incidencias"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    numero_orden: Mapped[str] = mapped_column(ForeignKey("rn_ordenes.numero"))
    tipo: Mapped[str]
    tipo_discrepancia: Mapped[str]
    fotos: Mapped[str]
    observaciones: Mapped[str]


class EvidenciaRow(Base):
    __tablename__ = "rn_evidencias"

    numero_orden: Mapped[str] = mapped_column(ForeignKey("rn_ordenes.numero"), primary_key=True)
    receptor_nombre: Mapped[str]
    receptor_identificacion: Mapped[str]
    foto_ref: Mapped[str]
    firma_ref: Mapped[str]
    latitud: Mapped[float]
    longitud: Mapped[float]
    estampa: Mapped[str]


class OrdenDeServicioSqlRepository:
    """Guarda y recupera la orden completa (estatus, incidencias, bitacora y evidencia)."""

    def __init__(self, session: Session):
        self.session = session

    def obtener_por_numero(self, numero: str) -> OrdenDeServicio:
        row = self.session.get(OrdenRow, numero)
        if row is None:
            raise OrdenNoEncontrada(numero)
        evidencia = None
        if row.evidencia is not None:
            e = row.evidencia
            evidencia = EvidenciaDeEntrega(
                e.receptor_nombre,
                e.receptor_identificacion,
                e.foto_ref,
                e.firma_ref,
                e.latitud,
                e.longitud,
                datetime.fromisoformat(e.estampa),
            )
        return OrdenDeServicio(
            row.numero,
            row.folio_cotizacion,
            row.unidad_id,
            row.operador_id,
            MercanciaDeclarada(row.tipo_mercancia, Decimal(row.peso_kg), Decimal(row.valor)),
            EstatusDelServicio(row.estatus),
            bitacora=[
                EntradaDeBitacora(
                    b.evento,
                    EstatusDelServicio(b.estatus),
                    datetime.fromisoformat(b.fecha),
                    b.responsable,
                )
                for b in row.bitacora
            ],
            incidencias=[
                Incidencia(
                    TipoDeIncidencia(i.tipo),
                    TipoDeDiscrepancia(i.tipo_discrepancia),
                    tuple(i.fotos.split("|")) if i.fotos else (),
                    i.observaciones,
                )
                for i in row.incidencias
            ],
            evidencia=evidencia,
            detenida=row.detenida,
        )

    def guardar(self, orden: OrdenDeServicio) -> None:
        row = self.session.get(OrdenRow, orden.numero)
        if row is None:
            row = OrdenRow(numero=orden.numero)
            self.session.add(row)
        row.folio_cotizacion = orden.folio_cotizacion
        row.unidad_id = orden.unidad_id
        row.operador_id = orden.operador_id
        row.tipo_mercancia = orden.mercancia.tipo
        row.peso_kg = str(orden.mercancia.peso_kg)
        row.valor = str(orden.mercancia.valor)
        row.estatus = orden.estatus.value
        row.detenida = orden.detenida
        row.bitacora = [
            BitacoraRow(
                evento=b.evento,
                estatus=b.estatus.value,
                fecha=b.fecha.isoformat(),
                responsable=b.responsable,
            )
            for b in orden.bitacora
        ]
        row.incidencias = [
            IncidenciaRow(
                tipo=i.tipo.value,
                tipo_discrepancia=i.tipo_discrepancia.value,
                fotos="|".join(i.fotos),
                observaciones=i.observaciones,
            )
            for i in orden.incidencias
        ]
        ev = orden.evidencia
        row.evidencia = (
            EvidenciaRow(
                receptor_nombre=ev.receptor_nombre,
                receptor_identificacion=ev.receptor_identificacion,
                foto_ref=ev.foto_ref,
                firma_ref=ev.firma_ref,
                latitud=ev.latitud,
                longitud=ev.longitud,
                estampa=ev.estampa.isoformat(),
            )
            if ev is not None
            else None
        )


class UnidadDeTrabajoSql:
    """IUnidadDeTrabajo sobre una Session: commit al terminar, rollback ante error."""

    def __init__(self, session: Session):
        self.session = session

    def iniciar(self) -> None:
        if not self.session.in_transaction():
            self.session.begin()

    def confirmar(self) -> None:
        self.session.commit()

    def revertir(self) -> None:
        self.session.rollback()
