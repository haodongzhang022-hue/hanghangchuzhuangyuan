from setuptools import setup, find_packages

setup(
    name="hanghang-router",
    version="0.1.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=["pyyaml>=6.0"],
    entry_points={
        "console_scripts": [
            "hanghang=hanghang.cli.main:main",
        ],
    },
    python_requires=">=3.9",
)
