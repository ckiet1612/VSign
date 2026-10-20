"""No proxy/redirect support; connect to a validated IP but verify the URL host."""
import http.client
import socket
import ssl
from urllib.parse import urlsplit

from app.integrations import validate_url, public_address


class UnsafeTarget(ValueError):
    pass


def resolve_public(host):
    answers=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    addresses=[row[4][0] for row in answers]
    if not addresses or any(not public_address(ip) for ip in addresses):
        raise UnsafeTarget('Nonpublic DNS answer')
    return addresses[0]


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self,host,address):
        super().__init__(host,443,timeout=8,context=ssl.create_default_context())
        self.address=address

    def connect(self):
        sock=socket.create_connection((self.address,443),timeout=self.timeout)
        try:
            self.sock=self._context.wrap_socket(sock,server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def post_webhook(url,body,headers):
    parsed=urlsplit(validate_url(url))
    address=resolve_public(parsed.hostname)
    connection=PinnedHTTPSConnection(parsed.hostname,address)
    try:
        connection.request('POST',parsed.path or '/',body=body,headers={
            'Content-Type':'application/json','User-Agent':'VSign-Webhooks/1',**headers})
        return connection.getresponse().status
    finally:
        connection.close()
