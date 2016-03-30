try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup
from codecs import open
from os import path

PACKAGE_NAME = 'psaw'
HERE = path.abspath(path.dirname(__file__))
with open(path.join(HERE, 'README.rst'), encoding='utf-8') as f:
    README = f.read()

setup(
    name=PACKAGE_NAME,
    version='0.1.dev13',
    description='Searchanise API wrapper',
    long_description=README,
    url='https://github.com/LeartS/PSAW',
    author='Leonardo Donelli',
    author_email='learts92@gmail.com',
    license='MIT',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Libraries :: Python Modules'
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
    ],
    keywords='searchanise api wrapper',
    packages=[PACKAGE_NAME],
    install_requires=['requests'],
)
