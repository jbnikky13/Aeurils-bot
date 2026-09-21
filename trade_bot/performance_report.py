"""Daily Telegram report backed by the paper-trade analytics engine."""
from .paper_analytics import format_report


def build_report():
    return format_report()
