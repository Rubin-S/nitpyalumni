import requests

class CloudflareDNSManager:
    """
    Cloudflare DNS Manager for A and CNAME records using API Token (recommended).
    Includes search functionality.
    """

    def __init__(self, zone_id: str, api_token: str):
        self.zone_id = zone_id
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }
        self.base_url = f"https://api.cloudflare.com/client/v4/zones/{self.zone_id}/dns_records"

    def create_record(self, record_type: str, name: str, content: str, ttl: int = 3600, proxied: bool = False, comment: str = None):
        data = {
            "type": record_type,
            "name": name,
            "content": content,
            "ttl": ttl,
            "proxied": proxied
        }
        if comment:
            data["comment"] = comment

        response = requests.post(self.base_url, headers=self.headers, json=data)
        return response.json()

    def list_records(self, record_type: str = None):
        params = {}
        if record_type:
            params["type"] = record_type

        response = requests.get(self.base_url, headers=self.headers, params=params)
        return response.json()

    def search_records(self, name: str = None, content: str = None, record_type: str = None):
        """
        Search DNS records by name, content, and/or type.
        All parameters are optional.
        """
        params = {}
        if name:
            params["name"] = name
        if content:
            params["content"] = content
        if record_type:
            params["type"] = record_type

        response = requests.get(self.base_url, headers=self.headers, params=params)
        return response.json()

    def update_record(self, record_id: str, record_type: str, name: str, content: str, ttl: int = 3600, proxied: bool = False, comment: str = None):
        data = {
            "type": record_type,
            "name": name,
            "content": content,
            "ttl": ttl,
            "proxied": proxied
        }
        if comment:
            data["comment"] = comment

        url = f"{self.base_url}/{record_id}"
        response = requests.put(url, headers=self.headers, json=data)
        return response.json()

    def delete_record(self, record_id: str):
        url = f"{self.base_url}/{record_id}"
        response = requests.delete(url, headers=self.headers)
        print(response.json())
        return response.json()
