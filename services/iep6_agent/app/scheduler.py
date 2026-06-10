"""APScheduler jobs: daily insight reports + periodic proactive-alert polling."""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.agent import insights
from app.core.config import settings
from app.core.database import AsyncSessionLocal

log = logging.getLogger(__name__)
_scheduler = AsyncIOScheduler()


def start() -> None:
    _scheduler.add_job(
        insights.run_all_insights, CronTrigger(hour=settings.INSIGHTS_CRON_HOUR, minute=0),
        args=[AsyncSessionLocal], id="daily_insights", replace_existing=True,
    )
    _scheduler.add_job(
        insights.run_all_weekly_insights,
        CronTrigger(day_of_week="mon", hour=settings.INSIGHTS_CRON_HOUR, minute=15),
        args=[AsyncSessionLocal], id="weekly_insights", replace_existing=True,
    )
    _scheduler.add_job(
        insights.run_all_alerts, IntervalTrigger(seconds=settings.ALERT_POLL_INTERVAL_S),
        args=[AsyncSessionLocal], id="alert_poll", replace_existing=True,
    )
    _scheduler.start()
    log.info("IEP6 scheduler started (daily @%02d:00 UTC, weekly Mon @%02d:15, alerts every %ds)",
             settings.INSIGHTS_CRON_HOUR,
             settings.INSIGHTS_CRON_HOUR, settings.ALERT_POLL_INTERVAL_S)


def shutdown() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
