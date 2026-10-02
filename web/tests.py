import re
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from web.models import UserData, Website
from web.views import (
    validate_subdomain_and_content,
    custom_bad_request,
    custom_permission_denied,
    custom_page_not_found,
    custom_server_error,
)

class SubdomainValidationTests(TestCase):
    def test_valid_a_record(self):
        name, rtype, content, err = validate_subdomain_and_content("john-doe", "A", "192.0.2.1")
        self.assertIsNone(err)
        self.assertEqual(name, "john-doe")
        self.assertEqual(rtype, "A")
        self.assertEqual(content, "192.0.2.1")

    def test_valid_cname_record(self):
        name, rtype, content, err = validate_subdomain_and_content("portfolio", "CNAME", "johndoe.github.io")
        self.assertIsNone(err)
        self.assertEqual(name, "portfolio")
        self.assertEqual(rtype, "CNAME")

    def test_valid_aaaa_record(self):
        name, rtype, content, err = validate_subdomain_and_content("ipv6site", "AAAA", "2001:db8::1")
        self.assertIsNone(err)
        self.assertEqual(rtype, "AAAA")

    def test_reserved_subdomain_rejected(self):
        for reserved in ["admin", "api", "www", "mail", "portal"]:
            name, rtype, content, err = validate_subdomain_and_content(reserved, "A", "192.0.2.1")
            self.assertIsNotNone(err)
            self.assertIn("reserved", err)

    def test_invalid_characters_rejected(self):
        invalid_names = ["-startdash", "enddash-", "has_underscore", "has.dot", "has space"]
        for bad_name in invalid_names:
            name, rtype, content, err = validate_subdomain_and_content(bad_name, "A", "192.0.2.1")
            self.assertIsNotNone(err)

    def test_invalid_ip_for_a_record_rejected(self):
        name, rtype, content, err = validate_subdomain_and_content("myhost", "A", "not-an-ip")
        self.assertIsNotNone(err)
        self.assertIn("Invalid IPv4", err)


class RollNumberRegexTests(TestCase):
    PATTERN = r'^[A-Z]{2}\d{2}[A-Z]{1}\d{4}$'

    def test_valid_roll_numbers(self):
        valid_rolls = ["CS20B1001", "EC19B1024", "ME21B2005", "EE22B1033"]
        for roll in valid_rolls:
            self.assertIsNotNone(re.match(self.PATTERN, roll))

    def test_invalid_roll_numbers(self):
        invalid_rolls = ["cs20b1001", "CS201001", "CS20B100", "INVALID", ""]
        for roll in invalid_rolls:
            self.assertIsNone(re.match(self.PATTERN, roll))


class CustomErrorHandlerTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_custom_404_returns_status_404(self):
        request = self.factory.get('/nonexistent-page')
        response = custom_page_not_found(request)
        self.assertEqual(response.status_code, 404)

    def test_custom_403_returns_status_403(self):
        request = self.factory.get('/forbidden-page')
        response = custom_permission_denied(request)
        self.assertEqual(response.status_code, 403)

    def test_custom_500_returns_status_500(self):
        request = self.factory.get('/server-error-page')
        response = custom_server_error(request)
        self.assertEqual(response.status_code, 500)

    def test_custom_400_returns_status_400(self):
        request = self.factory.get('/bad-request-page')
        response = custom_bad_request(request)
        self.assertEqual(response.status_code, 400)
