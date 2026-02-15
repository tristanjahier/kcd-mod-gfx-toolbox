from . import helpers


def pytest_configure(config):
    # Use this pytest hook to set the project root dir.
    helpers._PROJECT_ROOT_PATH = config.rootpath
