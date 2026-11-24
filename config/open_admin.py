"""The admin without a login. Guy is the one operator, and the stack listens
on the machine's own address alone (docker-compose binds the dashboard to
127.0.0.1:8003). He asked on 2026-11-02 for the admin open with no password,
and said on 2026-11-24 that it stays so when the stack moves to a host.

On the Mac that means a request that reaches /admin/ comes from the Mac. On
a host the private network's proxy hands the dashboard's port on, so the
admin is open, to read and to write every row, to every device on that
network: a machine or a person that is not Guy's is not let onto it while
this stands. The operator is a real user row so the admin's log of changes
has someone to name."""
from django.contrib.auth import get_user_model

OPERATOR = "guy"


def operator():
    User = get_user_model()
    user, created = User.objects.get_or_create(username=OPERATOR, defaults={"is_staff": True, "is_superuser": True})
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


class OpenAdminMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/admin/"):
            request.user = operator()
        return self.get_response(request)
