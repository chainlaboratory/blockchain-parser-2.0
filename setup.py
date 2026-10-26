import re
from pathlib import Path

from setuptools import setup, find_namespace_packages

ROOT = Path(__file__).parent
version_file = ROOT / "blockchain_parser" / "__init__.py"
version_match = re.search(
    r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]',
    version_file.read_text(encoding="utf-8"),
    re.MULTILINE,
)
if version_match is None:
    raise RuntimeError("Unable to find __version__ in blockchain_parser/__init__.py")
__version__ = version_match.group(1)

setup(
    name='blockchain-parser-2',
    version=__version__,
    packages=find_namespace_packages(exclude=[
        'pip-package', 'pip-package.*',
        'examples', 'examples.*',
        '*.egg-info', '*.egg-info.*',
    ]),
    url='https://github.com/chainlaboratory/blockchain-parser-2.0',
    project_urls={
        'Source': 'https://github.com/chainlaboratory/blockchain-parser-2.0',
        'Upstream': 'https://github.com/alecalve/python-bitcoin-blockchain-parser',
    },
    author='Antoine Le Calvez',
    author_email='antoine@p2sh.info',
    description='Bitcoin blockchain parser',
    long_description=(ROOT / 'README.md').read_text(encoding='utf-8'),
    long_description_content_type='text/markdown',
    license='LGPL-3.0-or-later',
    license_files=['LICENSE'],
    python_requires='>=3.8',
    include_package_data=True,
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Programming Language :: Python :: 3',
        'Topic :: Software Development :: Libraries',
    ],
    install_requires=[
        'python-bitcoinlib==0.11.0',
        'plyvel==1.5.1',
        'ripemd-hash==1.0.1'
    ]
)
