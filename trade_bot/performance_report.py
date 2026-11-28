"""Daily Telegram report backed by paper analytics and prospective FV1."""
from .paper_analytics import format_report
from .fv1_runtime import build_fv1_report, build_token_report

def build_report():
    return format_report() + "\n\n" + build_fv1_report() + "\n\n" + build_token_report()
