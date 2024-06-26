"""Decouples the database initialization from flask app creation."""

from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from .models import Base

if TYPE_CHECKING:
    from flask import Flask
    from sqlalchemy.engine import Engine
    from sqlalchemy.schema import MetaData

logger = getLogger(__name__)


class DB:
    """Base de datos.

    Gestiona las sesiones y la conexión a la base de datos.
    El motivo de no usar Flask-SQLAlchemy es que no se puede
    desligar la creación de la base de datos de la creación
    de la aplicación Flask.

    Queremos poder usar los modelos sin asociarlos a la aplicación
    para poder ejecutar tests o utilidades que no necesiten la
    aplicación Flask.
    """

    app: Flask
    engine: Engine | None = None
    session_factory: sessionmaker
    session: scoped_session

    def init_app(self, app: Flask) -> None:
        """Initialize the database connection."""
        self.app = app

        if self.engine:
            logger.debug("Inicialización de la base de datos ya realizada. Ignorada.")
            return

        self.engine = create_engine(
            app.config["SQLALCHEMY_DATABASE_URI"],
            echo=False,
            future=True,
        )
        self.session_factory = sessionmaker(bind=self.engine)
        self.session = scoped_session(self.session_factory)
        app.teardown_appcontext(self.shutdown_session)

    def shutdown_session(self, _exception: BaseException | None = None) -> None:  # type: ignore[no-untyped-def]
        """Remove the session after the request is finished."""
        self.session.remove()

    def create_all(self) -> None:
        """Create all tables."""
        if not self.engine:
            msg = "DB engine is not initialized."
            raise RuntimeError(msg)

        logger.debug("Creando las tablas de la base de datos.")
        Base.metadata.create_all(bind=self.engine)

    def drop_all(self) -> None:
        """Drop all tables."""
        if not self.engine:
            msg = "DB engine is not initialized."
            raise RuntimeError(msg)
        logger.debug("Eliminando las tablas de la base de datos.")
        Base.metadata.drop_all(bind=self.engine)

    def init_db(self) -> None:
        """Initialize the database."""
        if not self.engine:
            msg = "DB engine is not initialized."
            raise RuntimeError(msg)
        self.create_all()

    @property
    def metadata(self) -> MetaData:
        """Return the metadata."""
        return Base.metadata


db = DB()
