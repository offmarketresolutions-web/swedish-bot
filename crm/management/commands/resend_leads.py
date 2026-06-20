"""Re-send failed lead deliveries (plan §9 — cron sweep, no Celery). Retries every
LeadDelivery whose status != success by re-dispatching its ServiceRequest's sinks."""
from django.core.management.base import BaseCommand

from crm import sinks
from crm.models import LeadDelivery, ServiceRequest


class Command(BaseCommand):
    help = "Retry lead deliveries that haven't succeeded."

    def handle(self, *args, **opts):
        sr_ids = (LeadDelivery.objects.exclude(status="success")
                  .values_list("service_request_id", flat=True).distinct())
        retried = 0
        for sr in ServiceRequest.objects.filter(id__in=list(sr_ids)):
            results = sinks.dispatch(sr)
            retried += 1
            self.stdout.write(f"ServiceRequest<{sr.pk}>: {results}")
        self.stdout.write(self.style.SUCCESS(f"Re-dispatched {retried} request(s)."))
