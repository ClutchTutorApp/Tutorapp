from django.db import migrations, models


def copy_is_online_to_status(apps, schema_editor):
    TutorProfile = apps.get_model('api', 'TutorProfile')

    for tutor_profile in TutorProfile.objects.all():
        tutor_profile.status = 'online' if tutor_profile.is_online else 'offline'
        tutor_profile.save(update_fields=['status'])


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0009_university_course_relations'),
    ]

    operations = [
        migrations.AddField(
            model_name='tutorprofile',
            name='status',
            field=models.CharField(
                choices=[
                    ('offline', 'Offline'),
                    ('online', 'Online'),
                    ('busy', 'Busy'),
                    ('in_session', 'In_session'),
                ],
                default='offline',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='tutorprofile',
            name='last_active_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(copy_is_online_to_status, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='tutorprofile',
            name='is_online',
        ),
    ]
