from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def create_session_factory(url="sqlite:///llm_grader.db"):
    options = {}
    if url.startswith("sqlite:"):
        options = {"connect_args": {"check_same_thread": False}}
        if url.startswith("sqlite:///:memory:"):
            options["poolclass"] = StaticPool
    engine = create_engine(url, future=True, **options)
    return engine, sessionmaker(engine, expire_on_commit=False)


def init_database(engine):
    # Importing registers the confirmed-basis immutability guard on ORM flushes.
    from .. import authoring_confirmation  # noqa: F401
    Base.metadata.create_all(engine)
