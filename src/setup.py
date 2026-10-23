#!/usr/bin/env python
# -*- coding: utf-8 -*-
from pathlib import Path
import ast
import os
import re

from setuptools import find_packages, setup

HERE = Path(__file__).resolve().parent
os.chdir(str(HERE))
source = (HERE / 'bytedance/__init__.py').read_text(encoding='utf-8')
version = ast.literal_eval(re.search(r'__version__\s*=\s*(.*)', source).group(1))

setup(
    name='bytedance',
    version=version,
    description='ByteDance / Douyin mini-app server SDK',
    long_description=(HERE / 'README.rst').read_text(encoding='utf-8'),
    long_description_content_type='text/x-rst',
    author='pcloth',
    author_email='pcloth@gmail.com',
    maintainer='pcloth',
    maintainer_email='pcloth@gmail.com',
    license='BSD License',
    packages=find_packages(),
    package_data={'bytedance': ['contracts.json']},
    include_package_data=True,
    python_requires='>=3.6',
    install_requires=['requests>=2.27.1,<3'],
    extras_require={
        'redis': ['redis>=3.5.3,<6'],
        'crypto': ['cryptography>=3.4.8'],
    },
    keywords=['bytedance', 'douyin', 'toutiao', 'miniapp'],
    platforms=['all'],
    url='https://github.com/pcloth/bytedance',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Operating System :: OS Independent',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.12',
        'Topic :: Software Development :: Libraries',
    ],
)
