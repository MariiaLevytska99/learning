from setuptools import setup, find_packages

setup(
    name='learning',
    version='0.1.0',
    description='Learning project',
    author='Mariia Levytska',
    author_email='mariia.levytska@mail.com',
    packages=["glance", "glance_web", "glance_plugins"],
    install_requires=[
        # Specify any dependencies required by your project
    ],
)
