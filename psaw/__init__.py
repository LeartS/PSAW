import sys
import requests
import copy
try:
    from lxml import etree
except ImportError:
    import xml.etree.ElementTree as etree
import datetime
import pytz

from .exceptions import SearchaniseException, PSAWException
from .decorators import requires_api_key, requires_private_key

REQUIRED_ENTRY_FIELDS = {'id', 'title', 'summary', 'link'}
OPTIONAL_ENTRY_FIELDS = {'price', 'quantity', 'product_code', 'image_link'}
STANDARD_ENTRY_FIELDS = REQUIRED_ENTRY_FIELDS | OPTIONAL_ENTRY_FIELDS

NSMAP = {
    None: 'http://www.w3.org/2005/Atom',
    'cs': 'http://searchanise.com/ns/1.0'
}


class Searchanise(object):

    def __init__(self, api_key=None, private_key=None,
                 max_products_per_feed=200):
        self.base_url = 'http://searchanise.com/api/'
        self.max_products_per_feed = 200
        self.private_key = private_key
        self.api_version = 1.2
        self.prebuilt_custom_field_elements = {}
        self.products_queue = []

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
            'parent_private_key': parent_private_key,
        }
        result = self._send_request('signup', data=parameters)
        return result[0].text, result[1].text

    def set_keys(self, api_key, private_key):
        self.api_key = api_key
        self.private_key = private_key

    def get_prebuilt_custom_field_element(self, custom_field_name):
        """
        Returns the prebuilt etree element for the custom field with the
        optional attributes already prepared, or a bare element if there
        isn't any.
        """
        if custom_field_name in self.prebuilt_custom_field_elements:
            return copy.deepcopy(
                self.prebuilt_custom_field_elements[custom_field_name])
        return etree.Element('{{}}attribute'.format(NSMAP['cs']), nsmap=NSMAP)

    def prebuild_custom_fields_elements(self, custom_fields_params):
        """
        Prebuild custom field elements with the optional attributes already
        set so that we don't have to set them everytime.
        Theoretically the same custom field could have different attributes
        for different products, but we don't feel this does actually make sense.
        """
        for custom_field_name, params in custom_fields_params.items():
            el = etree.Element('{{}}attribute'.format(NSMAP['cs']), nsmap=NSMAP)
            el.set('name', custom_field_name)
            if params.get('text_search', False):
                el.set('text_search', 'Y')
                el.set('weight', str(params['weight']))
            if params.get('type', False):
                el.set('type', params['type'])
            self.prebuilt_custom_field_elements[custom_field_name] = el

    def build_custom_field(self, custom_field_name, custom_field_value):
        custom_field = self.get_prebuilt_custom_field_element(custom_field_name)

        # we must check if string type first because it's also iterable
        base_string_type = basestring if sys.version_info[0] < 3 else str
        if isinstance(custom_field_value, base_string_type):
            custom_field.text = str(custom_field_value or '')
            return custom_field
        # It's not string or similar, we can use duck typing now!
        try:
            for value in custom_field_value:
                etree.SubElement(custom_field, 'value').text = str(value or '')
        except TypeError: # not iterable
            custom_field.text = str(custom_field_value)
        return custom_field

    def build_product_entry(self, product_dict):
        """
        Build the XML entry for a product.

        Args:
            product_dict (dict): product data.
                It must have all REQUIRED_ENTRY_FIELDS keys, any subset
                (including none) of OPTIONAL_ENTRY_FIELDS keys, and
                any number of other additional keys, which we refer to as
                *custom fields*.

                The values of the standard fields (i.e. not custom) must be
                simple values of type text (str, unicode, bytes), int or float.
                The values of custom fields can be of 3 kinds:

                    * a simple int, text or float value.
                      examples: ``12``, ``15.0``, ``'food'``
                    * a list or tuple of simple values for multi-valued ones
                      (e.g. a list of string for tags).
                      example: ``['tag1', 'tag2', 'tag3']``
                    * a dictionary in the form below if you need to specify
                      some custom fields parameters like text_search and weight.
                      example::

                          {
                              'type': 'int', # required, 'text' 'int' or 'float'
                              'values': [1, 2], # required, list/tuple
                              'text_search': True, # required, boolean
                              'weight': 12 # only if text_search is True, int.
                          }
        """
        keys_set = set(product_dict.keys())
        if not REQUIRED_ENTRY_FIELDS <= keys_set:
            raise PSAWException(
                'At least one of the supplied products is missing a'
                ' required field.')

        # Root entry element
        entry = etree.Element('entry')

        # standard fields: they have their own tag
        for field in keys_set & STANDARD_ENTRY_FIELDS:
            etree.SubElement(entry, field).text = str(product_dict[field] or '')
        # custom fields: generic tag
        for field in keys_set - STANDARD_ENTRY_FIELDS:
            custom_field = self.build_custom_field(field, product_dict[field])
            entry.append(custom_field)

        return entry

    @requires_private_key
    def delete(self, product_identifier):
        data = {'private_key': self.private_key, 'id': product_identifier}
        self._send_request('delete', data=data)

    @requires_private_key
    def delete_all(self):
        data = {'private_key': self.private_key, 'all': 1}
        self._send_request('delete', data=data)

    def add(self, product):
        """
        Add a single product to the queue of products to be sent to searchanise
        at the next ``.update()``
        """
        self.products_queue.append(product)

    def set_custom_fields_params(custom_fields_params):
        self.prebuild_custom_fields_elements(custom_fields_params)

    @requires_private_key
    def update(self, products=None, custom_fields_params=None):
        """
        Sends an update command to searchanise.

        Args:
            products (iterable): List/tuple of products data dicts,
                which should be in the format explained by
                ``build_product_entry``
            custom_fields_params (dict): Additional params for custom fields
                like search_text and weight.
                example: {'custom_field1': {'search_text': True, weight: 3}}
        """
        if products:
            for product in products:
                self.add(product)
        if custom_fields_params:
            self.set_custom_fields_params(custom_fields_params)

        timestamp = datetime.datetime.now(pytz.utc)
        feed = etree.Element('{{}}feed'.format(NSMAP[None]), nsmap=NSMAP)
        etree.SubElement(feed, 'title').text = 'Searchanise data feed'
        etree.SubElement(feed, 'updated').text = timestamp.isoformat()
        etree.SubElement(feed, 'id').text = 'boh'

        for product in self.products_queue:
            feed.append(self.build_product_entry(product))

        data = {
            'private_key': self.private_key,
            'data': etree.tostring(feed),
        }
        self._send_request('update', data=data)
        self.products_queue = []
