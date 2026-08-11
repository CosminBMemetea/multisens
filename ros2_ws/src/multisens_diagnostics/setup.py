from setuptools import find_packages, setup

package_name = 'multisens_diagnostics'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='MultiSens',
    maintainer_email='memetea.cosmin@gmail.com',
    description='MultiSens global/system diagnostics',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'system_diagnostics_node = multisens_diagnostics.system_diagnostics_node:main',
        ],
    },
)
