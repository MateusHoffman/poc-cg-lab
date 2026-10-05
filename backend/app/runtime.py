from __future__ import annotations

import os
from dataclasses import dataclass, field

from app.flags import FlagClient
from app.session_store import SessionStore
from app.vector_store import VectorStore

DEFAULT_DSN = "postgresql://admin:adminpassword@localhost:5434/cglab"
DEFAULT_DYNAMO = "http://localhost:8000"


@dataclass
class Runtime:
    vector: VectorStore
    sessions: SessionStore
    flags: FlagClient
    cache: dict = field(default_factory=dict)

    @classmethod
    def local(cls) -> Runtime:
        return cls(VectorStore(None), SessionStore(None), FlagClient())

    @classmethod
    def from_env(cls) -> Runtime:
        return cls(
            VectorStore(os.getenv("DATABASE_URL", DEFAULT_DSN)),
            SessionStore(os.getenv("DYNAMODB_ENDPOINT", DEFAULT_DYNAMO)),
            FlagClient(),
        )
