"""Daily Telegram report backed by paper analytics and prospective FV1."""
from .paper_analytics import format_report
from .fv1_runtime import build_fv1_report, build_token_report

def build_report():
    # Telegram sendMessage has a 4096-character limit; preserve all three
    # sections within a conservative single-message budget.
    sections=[
        format_report()[:1450],
        build_fv1_report()[:1250],
        build_token_report()[:1050],
    ]
    return "\n\n".join(section for section in sections if section)[:3900]
