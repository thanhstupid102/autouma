from enum import Enum


class Module(str, Enum):
    MASTER_DATA = "master-data"
    SETTINGS = "settings"
    BOT_CONFIG = "bot-config"


class TagBuilder:
    @staticmethod
    def name(module: Module) -> str:
        return module.value
