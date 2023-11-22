from setuptools import setup, find_packages

setup(
    name='glance',
    version='0.13.0',
    description='glance package',
    author='Mariia Levytska',
    author_email='mariia.levytska99@mail.com',
    packages=find_packages(),
    install_requires=[
        'cachetools==4.2.4',
        'click==7.1.2',
        'debtcollector==2.2.0',
        'decorator==5.1.1',
        'numpy==1.22.4',
        'pandas==1.4.1',
        'PyYAML==6.0',
        'requests==2.25.0',
        'setuptools==59.5.0',
        'simplekv==0.14.1',
        'six==1.16.0',
        'storefact==0.10.0',
    ],
)
