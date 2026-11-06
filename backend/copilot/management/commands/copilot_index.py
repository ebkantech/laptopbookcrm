from django.core.management.base import BaseCommand, CommandError

from copilot import llm, search


class Command(BaseCommand):
    help = "Build or refresh AI-Staff's search index. Only new or changed records are processed."

    def handle(self, *args, **options):
        try:
            counts = search.rebuild(report=self.stdout.write)
        except llm.LLMError as error:
            raise CommandError(f"{error} Finished records are kept: run this again to carry on.")
        self.stdout.write(self.style.SUCCESS(
            f"Done: {counts['indexed']} indexed, {counts['removed']} removed, {counts['total']} records in the CRM."))
