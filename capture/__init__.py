"""Capture module for collecting inquiries from various platforms."""

from .facebook import FacebookCapture
from .instagram import InstagramCapture
from .email_capture import EmailCapture
from .base import BaseCaptureModule

__all__ = [
    "BaseCaptureModule",
    "FacebookCapture",
    "InstagramCapture",
    "EmailCapture",
]
