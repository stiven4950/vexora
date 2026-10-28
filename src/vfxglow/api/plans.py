"""Catálogo de planes y paquetes de créditos (configs/plans.yaml) para la vista "Mi plan".

El servidor es la autoridad sobre los precios: la web los lee de aquí y nunca los inventa. Hoy
es una propuesta (`draft`): no hay cobros, suscripciones ni saldo todavía (docs/analisis_mejoras_y_seguridad.md,
§3.5), así que el plan de cada persona es `default_plan`.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class Plan(BaseModel):
    id: str
    title: str
    tagline: str
    badge: str | None = None
    highlighted: bool = False
    icon: str
    price_month: float
    # "Desde $99": el precio es el mínimo de un plan a medida.
    price_from: bool = False
    # Se contrata hablando con ventas, no con un botón de pago.
    contact: bool = False
    monthly_credits: int | None = None
    features: list[str]
    footnote: str | None = None
    footnote_icon: str | None = None
    # Sus videos llevan la marca de agua de Vexora (composite/watermark.py).
    watermark: bool = False
    # Puede guardar sus videos en la nube (si no, solo descargarlos antes de que venzan) y compartirlos.
    cloud_save: bool = False
    share: bool = False
    # Vistas al día por enlace compartido; None = sin tope.
    share_daily_views: int | None = None


class CreditPack(BaseModel):
    id: str
    credits: int
    price: float
    note: str


class Catalog(BaseModel):
    draft: bool = True
    currency: str = "USD"
    default_plan: str
    # Días que dura un video terminado que no se guardó en la nube.
    unsaved_days: int = 7
    plans: list[Plan]
    packs: list[CreditPack] = Field(default_factory=list)


@lru_cache(maxsize=4)
def load_catalog(path: Path, stamp: float) -> Catalog:
    """El catálogo leído una vez por versión del archivo (`stamp`: su fecha de modificación)."""
    catalog = Catalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    ids = [plan.id for plan in catalog.plans]
    if len(set(ids)) != len(ids) or catalog.default_plan not in ids:
        raise ValueError(f"{path.name}: ids de plan repetidos o default_plan desconocido")
    return catalog


def catalog(path: Path) -> Catalog:
    return load_catalog(path, path.stat().st_mtime)


GRANTS_ENV = "VEXORA_PLAN_GRANTS"


def grants() -> dict[str, str]:
    """Planes asignados a mano mientras no hay pagos (`VEXORA_PLAN_GRANTS="uid1:pro,uid2:ultra"`):
    para quienes prueban la app. Vive en el servidor; la web no puede cambiarlo."""
    pairs = (item.split(":", 1) for item in os.environ.get(GRANTS_ENV, "").split(",") if ":" in item)
    return {uid.strip(): plan.strip() for uid, plan in pairs}


def plan_of(path: Path, uid: str) -> Plan:
    """El plan de una persona. Sin suscripciones todavía: el asignado en VEXORA_PLAN_GRANTS o `default_plan`."""
    data = catalog(path)
    wanted = grants().get(uid, data.default_plan)
    return next((plan for plan in data.plans if plan.id == wanted), next(plan for plan in data.plans if plan.id == data.default_plan))
