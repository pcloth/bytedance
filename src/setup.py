#!/usr/bin/env python
# coding=utf-8

from setuptools import setup, find_packages
import re, ast

desc = open('README.rst', encoding='utf-8').read()
_version_re = re.compile(r'__version__\s+=\s+(.*)')

with open('bytedance/__init__.py', 'rb') as f:
    version = str(ast.literal_eval(_version_re.search(
        f.read().decode('utf-8')
    ).group(1)))


setup(
    name='bytedance',
    version=version,
    description=(
        'bytedance mini app sdk'
    ),
    long_description=desc,
    author='pcloth',
    author_email='pcloth@gmail.com',
    maintainer='pcloth',
    maintainer_email='pcloth@gmail.com',
    license='BSD License',
    packages=find_packages(),
    include_package_data=True, 
    exclude_package_date={'':['.gitignore']},
    keywords=['bytedance', 'douyin', 'toutiao', 'huoshan'],
    platforms=["all"],
    url='https://github.com/pcloth/bytedance',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Operating System :: OS Independent',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python',
        'Programming Language :: Python :: Implementation',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Topic :: Software Development :: Libraries'
    ],
)
