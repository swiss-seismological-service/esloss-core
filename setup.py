from setuptools import setup

setup(
    name='ebr',
    entry_points={
        'console_scripts': [
            'ebr=core.cli:cli'
        ],
    },
)
