from .exceptions import PSAWException

def requires_private_key(method):
    def wrapper(self, *args, **kwargs):
        if not self.private_key:
            raise PSAWException(
                'The {} method requires a private key'.format(method.__name__))
        return method(self, *args, **kwargs)
    return wrapper

def requires_api_key(method):
    def wrapper(self, *args, **kwargs):
        if not self.api_key:
            raise PSAWException(
                'The {} method requires an API key'.format(method.__name__))
        return method(self, *args, **kwargs)
    return wrapper
