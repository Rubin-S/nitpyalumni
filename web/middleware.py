"""Response security headers not covered by Django's SecurityMiddleware."""

# A strict script-src CSP is not feasible yet: templates use inline scripts and
# CDN assets. These directives block plugin content, <base> hijacking,
# clickjacking and off-site form posting without affecting existing pages.
CONTENT_SECURITY_POLICY = "; ".join([
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    "form-action 'self'",
])
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        response.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        return response
