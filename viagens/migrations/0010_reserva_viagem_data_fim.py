from django.db import migrations, models


def preencher_data_fim(apps, schema_editor):
    ReservaViagem = apps.get_model("viagens", "ReservaViagem")
    for reserva in ReservaViagem.objects.only("pk", "data").iterator():
        ReservaViagem.objects.filter(pk=reserva.pk).update(data_fim=reserva.data)


class Migration(migrations.Migration):

    dependencies = [
        ("viagens", "0009_permissoes_de_perfil"),
    ]

    operations = [
        migrations.AddField(
            model_name="reservaviagem",
            name="data_fim",
            field=models.DateField(null=True),
        ),
        migrations.RunPython(preencher_data_fim, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="reservaviagem",
            name="data_fim",
            field=models.DateField(),
        ),
    ]
