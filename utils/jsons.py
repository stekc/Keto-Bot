import json


class JSONObject(object):
    def __init__(self, path: str) -> None:
        self.path = path  # TODO: not sure if pathlib is better but using str for now

    @staticmethod
    def __load__(data):
        return data

    def load_json(self):
        with open(self.path, "r") as f:
            result = JSONObject.__load__(json.loads(f.read()))
        return result


class ConfigJSON(JSONObject):
    def __init__(self) -> None:
        super().__init__("config/config.json")


class SocialsJSON(JSONObject):
    def __init__(self) -> None:
        super().__init__("config/socials.json")


class TrackingJSON(JSONObject):
    def __init__(self) -> None:
        super().__init__("config/tracking.json")
