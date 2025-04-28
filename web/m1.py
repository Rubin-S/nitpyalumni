from django.shortcuts import render
from django.http import Http404
from django.middleware.csrf import CsrfViewMiddleware
from django.core.exceptions import DisallowedHost

class ForceErrorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # If the response status is 404, render custom 404 page
        if response.status_code == 404:
            return render(request, 'error.html', {'error_message': 'Page Not Found', 'error_code': 404})

        # If the response status is 403 (forbidden), render custom 403 page
        if response.status_code == 403:
            return render(request, 'error.html', {'error_message': "You're not authorized", 'error_code': 403})

        # If the response status is 500, render custom 500 page
        if response.status_code == 500:
            return render(request, 'error.html', {'error_message': '500 Server Error', 'error_code': 500})

        return response

    # Optionally, you can force specific errors for testing purposes
    def process_exception(self, request, exception):
        # Handle Http404 exceptions with a custom response
        if isinstance(exception, Http404):
            return render(request, 'error.html', {'error_message': 'Page Not Found', 'error_code': 404})
        
        # Handle CSRF token error with a custom response
        elif isinstance(exception, CsrfViewMiddleware):
            return render(request, 'error.html', {'error_message': 'CSRF token missing or incorrect', 'error_code': 403})
        
        # Handle any other forbidden (403) exceptions
        elif isinstance(exception, PermissionError):  # Custom handling for other 403 errors
            return render(request, 'error.html', {'error_message': "You're not authorized", 'error_code': 403})
        
        # Handle all other exceptions as server errors
        elif isinstance(exception, DisallowedHost):
            return render(request, 'error.html', {'error_message': 'Sorry, this host is not allowed to access this site.', 'error_code': 400})
        
        # Handle all other exceptions as 500 internal server error
        elif isinstance(exception, Exception):
            return render(request, 'error.html', {'error_message': '500 Server Error', 'error_code': 500})

        return None
