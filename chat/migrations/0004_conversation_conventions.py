from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0003_message_sent_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='conversation',
            name='conventions',
            field=models.TextField(blank=True, default='', help_text='Standing rules for every report, one per line. Every reply reads them, under the line that says when the message was sent.'),
        ),
    ]
