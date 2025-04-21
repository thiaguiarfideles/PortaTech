from setuptools import setup, find_packages

setup(
    name="condominio",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        'flask',
        'flask-sqlalchemy',
        'flask-migrate',
        # outros requirements
    ],
)