from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("admin_service_net", "0002_delete_lineadminproxy_routeadminproxy"),
        (
            "exchange_agreement",
            "0013_remove_contractinvitation_unique_pending_contract_invitation_per_email_role_and_more",
        ),
    ]
    run_before = [
        ("exchange_agreement", "0014_remove_trip_route_remove_trip_stops_and_more"),
    ]

    operations = [
        migrations.DeleteModel(
            name="RouteAdminProxy",
        ),
        migrations.DeleteModel(
            name="StopAdminProxy",
        ),
        migrations.DeleteModel(
            name="TripAdminProxy",
        ),
    ]
