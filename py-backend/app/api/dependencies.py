from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.agents.graph import ZoeGraph
from app.db import Account
from app.memory.conversation_logger import ConversationLogger


@dataclass
class AppServices:
    zoe_graph: ZoeGraph | None
    conversation_logger: ConversationLogger


def get_services(request: Request) -> AppServices:
    return request.app.state.services


def ensure_account(session: Session, user_id: int) -> Account:
    account = session.query(Account).filter(Account.id == user_id).first()
    if not account:
        raise HTTPException(status_code=401, detail="invalid userId")
    return account
