"""Dispatch module for sending replies back to original platforms."""

from .facebook_reply import FacebookDispatch
from .instagram_reply import InstagramDispatch
from .email_reply import EmailDispatch
from .dispatcher import Dispatcher

__all__ = [
    "FacebookDispatch",
    "InstagramDispatch",
    "EmailDispatch",
    "Dispatcher",
]
