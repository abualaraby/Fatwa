"""Database module for Fatwa Management System."""

from .models import Ticket, TicketStatus, SourcePlatform
from .db import Database, get_database

__all__ = [
    "Ticket",
    "TicketStatus",
    "SourcePlatform",
    "Database",
    "get_database",
]
