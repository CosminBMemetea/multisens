from setuptools import find_packages, setup

package_name = 'multisens_ingestion'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', [
            'launch/ingestion.launch.py',
        ]),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='MultiSens',
    maintainer_email='memetea.cosmin@gmail.com',
    description='MultiSens sensor ingestion nodes',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'rtsp_ingestion_node = multisens_ingestion.rtsp_ingestion_node:main',
        ],
    },
)
