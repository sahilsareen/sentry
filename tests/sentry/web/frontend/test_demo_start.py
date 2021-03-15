from sentry.utils.compat import mock

from django.test.utils import override_settings
from exam import fixture

from sentry.testutils import TestCase


class AuthLoginTest(TestCase):
    @fixture
    def path(self):
        return "/demo/start/"

<<<<<<< Updated upstream
    @override_settings(DEMO_MODE=True, ROOT_URLCONF="sentry.demo.urls")
    @mock.patch("sentry.web.frontend.demo_start.auth.login")
    @mock.patch("sentry.demo.demo_org_manager.assign_demo_org")
    def test_basic(self, mock_assign_demo_org, mock_auth_login):

        user = self.create_user()
        org = self.create_organization()

        mock_assign_demo_org.return_value = (org, user)
        resp = self.client.post(self.path)
        assert resp.status_code == 302

        mock_auth_login.assert_called_once_with(mock.ANY, user)

    @override_settings(DEMO_MODE=False, ROOT_URLCONF="sentry.demo.urls")
=======
    @override_settings(DEMO_MODE=True, DEMO_ORG_OWNER_EMAIL=org_owner_email)
    @mock.patch("sentry.web.frontend.demo_start.generate_random_name", return_value=org_name)
    def test_basic(self, mock_generate_name):
        owner = User.objects.create(email=org_owner_email)
        resp = self.client.post(self.path)
        assert resp.status_code == 302

        org = Organization.objects.get(name=org_name)
        assert org.flags.demo_mode
        slug = slugify(org_name)
        email = create_fake_email(slug, "demo")
        user = User.objects.get(email=email)
        assert user.flags.demo_mode

        assert OrganizationMember.objects.filter(
            user=user, organization=org, role="member"
        ).exists()
        assert OrganizationMember.objects.filter(
            user=owner, organization=org, role="owner"
        ).exists()

        assert len(Project.objects.filter(organization=org)) == 2
        assert not ProjectKey.objects.filter(project__organization=org).exists()

    @override_settings(DEMO_MODE=True, DEMO_ORG_OWNER_EMAIL=org_owner_email)
    @mock.patch("sentry.web.frontend.demo_start.generate_random_name", return_value=org_name)
    def test_no_owner(self, mock_generate_name):
        with pytest.raises(Exception):
            self.client.post(self.path)

        # verify we are using atomic transactions
        assert not Organization.objects.filter(name=org_name).exists()

    @override_settings(DEMO_MODE=False)
>>>>>>> Stashed changes
    def test_disabled(self):
        resp = self.client.post(self.path)
        assert resp.status_code == 404
