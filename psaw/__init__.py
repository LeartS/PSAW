import copy
import datetime
import logging
import pytz
import sys
from lxml import etree

import requests

from psaw.decorators import requires_api_key, requires_private_key
from psaw.exceptions import SearchaniseException, PSAWException

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

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
        self.api_key = api_key
        self.private_key = private_key
        self.api_version = 1.2
        self._prebuilt_custom_field_elements = {}
        self._products_queue = []

    def _parse_response(self, response):
        logger.debug('Received response: %s', response.content)
        root = etree.fromstring(response.content)
        if root.tag == 'errors':
            raise SearchaniseException('\n'.join(error.text for error in root))
        return root

    def _send_request(self, operation, method='post', data=None):
        """
        Returns the XML root node as an ElementTree node
        """
        logger.debug('Sending request %s: %s', self.base_url + operation, data)
        data = data if data else {}
        assert method in ('post', 'get'), "Invalid request method"
        r = getattr(requests, method)(self.base_url + operation, data=data)
        return self._parse_response(r)

    def _sanitize_text(self, element_value):
        if element_value is None or element_value is False:
            return ''
        try:
            _ = element_value + 0.0
            return str(element_value)
        except TypeError:
            return etree.CDATA(element_value)

    def _get_prebuilt_custom_field_element(self, custom_field_name):
        """
        Returns the prebuilt etree element for the custom field with the
        optional attributes already prepared, or a bare element if there
        isn't any.
        """
        if custom_field_name not in self._prebuilt_custom_field_elements:
            self._prebuild_custom_fields_elements({custom_field_name: {}})
        return copy.deepcopy(
            self._prebuilt_custom_field_elements[custom_field_name])

    def _prebuild_custom_fields_elements(self, custom_fields_params):
        """
        Prebuild custom field elements with the optional attributes already
        set so that we don't have to set them everytime.
        Theoretically the same custom field could have different attributes
        for different products, but I think this doesn't make sense
        """
        for custom_field_name, params in custom_fields_params.items():
            complete_field_name = '{' + NSMAP['cs'] + '}attribute'
            el = etree.Element(complete_field_name, nsmap=NSMAP)
            el.set('name', custom_field_name)
            if params.get('text_search', False):
                el.set('text_search', 'Y')
                el.set('weight', str(params['weight']))
            if params.get('type', False):
                el.set('type', params['type'])
            self._prebuilt_custom_field_elements[custom_field_name] = el

    def _build_custom_field(self, custom_field_name, custom_field_value):
        custom_field = self._get_prebuilt_custom_field_element(custom_field_name)

        # we must check if string type first because it's also iterable
        base_string_type = basestring if sys.version_info[0] < 3 else str
        if isinstance(custom_field_value, base_string_type):
            custom_field.text = self._sanitize_text(custom_field_value)
            return custom_field
        # It's not string or similar, we can use duck typing now!
        try:
            for value in custom_field_value:
                str_value = self._sanitize_text(value)
                etree.SubElement(custom_field, 'value').text = str_value
        except TypeError: # not iterable
            custom_field.text = self._sanitize_text(custom_field_value)
        return custom_field

    def _build_product_entry(self, product_dict):
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

                          'my_custom_field': {
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
        entry = etree.Element('entry', nsmap=NSMAP)

        # required standard fields: simple tag
        for field in keys_set & REQUIRED_ENTRY_FIELDS:
            if field == 'link':
                # the link value needs to be passed in the href attribute
                etree.SubElement(entry, field, href=product_dict[field])
                continue
            etree.SubElement(entry, field).text = self._sanitize_text(
                product_dict[field])
        # optional standard field: prefix
        for field in keys_set & OPTIONAL_ENTRY_FIELDS:
            complete_field = '{' + NSMAP['cs'] + '}' + field
            etree.SubElement(entry, complete_field).text = self._sanitize_text(
                product_dict[field])
        # custom fields: generic tag with prefix
        for field in keys_set - STANDARD_ENTRY_FIELDS:
            custom_field = self._build_custom_field(field, product_dict[field])
            entry.append(custom_field)

        return entry

    def register(self, store_url, admin_email, parent_private_key=None):
        logger.info('Registering store: %s %s', store_url, admin_email)
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

    @requires_private_key
    def delete(self, product_identifier):
        logger.info('Deleting product %s', product_identifier)
        data = {'private_key': self.private_key, 'id': product_identifier}
        return self._send_request('delete', data=data)

    @requires_private_key
    def delete_all(self):
        logger.info('Deleting all products')
        data = {'private_key': self.private_key, 'all': 1}
        return self._send_request('delete', data=data)

    def add(self, product):
        """
        Add a single product to the queue of products to be sent to searchanise
        at the next ``.update()``
        """
        self._products_queue.append(product)

    def set_custom_fields_params(self, custom_fields_params):
        self._prebuild_custom_fields_elements(custom_fields_params)

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

        if not self._products_queue:
            # nothing to send, skip update request
            return

        logger.info('Sending update request for %d products',
                    len(self._products_queue))

        timestamp = datetime.datetime.now(pytz.utc)
        feed = etree.Element('{{}}feed'.format(NSMAP[None]), nsmap=NSMAP)
        etree.SubElement(feed, 'title').text = 'Searchanise data feed'
        etree.SubElement(feed, 'updated').text = timestamp.isoformat()
        etree.SubElement(feed, 'id').text = 'boh'

        for product in self._products_queue:
            feed.append(self._build_product_entry(product))

        data = {
            'private_key': self.private_key,
            'data': etree.tostring(feed),
        }
        self._send_request('update', data=data)
        self._products_queue = []

    def query(self, query_string=''):
        """
        Initialize a search query.

        Args:
            query_string (string): the ``q`` parameter of the
                Searchanise Search APIs

        Returns:
            A SearchaniseQuery object initialized with the supplied
            query string and bound to this instance.
        """
        logger.info('Querying with query_string: %s', query_string)
        return SearchaniseQuery(self, query_string)


class SearchaniseQuery(object):

    def __init__(self, searchanise_instance, query_string='',
                 output_format='json'):
        self.searchanise_instance = searchanise_instance
        self.query_string = query_string
        self.output_format = output_format
        self._restrict_by = {}
        self._query_by = {}

    @property
    def api_key(self):
        return self.searchanise_instance.api_key

    @property
    def private_key(self):
        return self.searchanise_instance.private_key

    def _get_query_params(self):

        def format_params(p_dict, name):
            return dict(
                ('{}[{}]'.format(name, a), v) for a, v in p_dict.iteritems()
            )

        query_params = {}
        # Filtering/Condition params: queryBy, restrictBy
        conditions = [
            ('restrictBy', self._restrict_by),
            ('queryBy', self._query_by),
        ]
        for cond_name, cond_dict in conditions:
            query_params.update(format_params(cond_dict, cond_name))
        # standard query param
        query_params['q'] = self.query_string
        # api keys
        query_params['api_key'] = self.api_key
        return query_params

    def restrict_by(self, **kwargs):
        for attribute, value in kwargs.items():
            self._restrict_by[attribute] = value
        return self

    def query_by(self, **kwargs):
        for attribute, value in kwargs.items():
            self._query_by[attribute] = value
        return self

    @requires_api_key
    def execute(self):
        params = self._get_query_params()
        res = requests.get('http://searchanise.com/search', params=params)
        return res.json()
