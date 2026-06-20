"""Enable pg_trgm + a GIN trigram index on Machine.search_text for fuzzy
machine identification (plan §8)."""
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("kb", "0001_initial")]

    operations = [
        TrigramExtension(),
        migrations.AddIndex(
            model_name="machine",
            index=GinIndex(
                name="kb_machine_search_trgm",
                fields=["search_text"],
                opclasses=["gin_trgm_ops"],
            ),
        ),
    ]
