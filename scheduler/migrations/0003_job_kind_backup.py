from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scheduler', '0002_session_grace'),
    ]

    operations = [
        migrations.AlterField(
            model_name='job',
            name='kind',
            field=models.CharField(choices=[('reply', 'Reply'), ('collect', 'Collect'), ('assess', 'Assess'), ('digest', 'Digest'), ('heartbeat', 'Heartbeat'), ('backup', 'Backup')], max_length=10),
        ),
    ]
