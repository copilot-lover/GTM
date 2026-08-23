from app.routers import (
    auth,
    companies,
    dashboard,
    feed,
    dialer,
    health,
    hiring_intent,
    leads,
    outreach,
    pipeline_admin,
    scrape,
)

routes = [
    health.router,
    auth.router,
    companies.router,
    leads.router,
    pipeline_admin.router,
    outreach.router,
    dialer.router,
    hiring_intent.router,
    dashboard.router,
    feed.router,
    scrape.router,
]
