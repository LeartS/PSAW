import requests
try:
    from lxml import etree
except ImportError:
    import xml.etree.ElementTree as etree


class SearchaniseException(Exception):

    def __init__(self, message):
        super(SearchaniseException, self).__init__(message)


class Searchanise(object):

    def __init__(self, private_key=None, max_products_per_feed=200):
        self.base_url = 'http://searchanise.com/api/'
        self.max_products_per_feed = 200
        self.private_key = private_key
        self.api_version = 1.2

    def _parse_response(self, response):
        root = etree.fromstring(response.content)
        if root.tag == 'errors':
            raise SearchaniseException('\n'.join(error.text for error in root))
        return root

    def _send_request(self, operation, method='post', data=None):
        """
        Returns the XML root node as an ElementTree node
        """
        data = data if data else {}
        assert method in ('post', 'get'), "Invalid request method"
        r = getattr(requests, method)(self.base_url + operation, data=data)
        return self._parse_response(r)

    def register(self, store_url, admin_email, parent_private_key=None):
        parameters = {
            'url': store_url,
            'email': admin_email,
            'version': self.api_version,
        }
        result = self._send_request('signup', data=parameters)
        return result[0].text, result[1].text
